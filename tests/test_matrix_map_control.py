from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import requests
from docker.errors import ContainerError

from matrix.run import command as renderer_command
from matrix.run.map_control import (
    MAP_CONTROL_HEADER,
    MAP_CONTROL_PATH,
    MAP_PREVIEW_PATH,
    MapControlHTTPServer,
)
from tests.matrix_fixtures import (
    MapControlFixture,
    RendererLaunchFixture,
)


class MatrixMapControlTests(MapControlFixture):
    def test_custom_preview_projects_tiles_without_changing_the_engine(self):
        (self.custom / "tiles.yaml").write_text(
            "tiles:\n  lot/road: {type: straight}\n  wing/hub: {type: 3way}\n"
        )
        (self.custom / "tile_maps.yaml").write_text(
            "tile_maps:\n  lot: {tile_size: {x: 2, y: 1}}\n  wing: {tile_size: {x: 1, y: 3}}\n"
        )
        (self.custom / "frames.yaml").write_text(
            "frames:\n"
            "  lot: {pose: {x: 10, y: 20, yaw: 1.5707963267948966}}\n"
            "  lot/road: {unit: tiles, pose: {x: 1, y: 2, yaw: -1.5707963267948966}}\n"
            "  reference: {pose: {x: -8, y: 4, yaw: -1.5707963267948966}}\n"
            "  wing/hub: {relative_to: reference, pose: {x: 2, y: -1}}\n"
        )
        before = self.control.status()
        source = {"embedded": False, "value": "work maps/loop"}
        road, hub = self.control.preview(source)["tiles"]
        self.assertEqual((road["kind"], road["width"], road["height"]), ("straight", 2, 1))
        self.assertAlmostEqual(road["x"], 7.5)
        self.assertAlmostEqual(road["y"], 23)
        self.assertAlmostEqual(road["yaw"], 0)
        self.assertEqual((hub["kind"], hub["width"], hub["height"]), ("3way", 1, 3))
        self.assertAlmostEqual(hub["x"], -9)
        self.assertAlmostEqual(hub["y"], 2)
        self.assertAlmostEqual(hub["yaw"], -1.5707963267948966)
        self.assertEqual(self.control.status(), before)
        self.probe.assert_called_once()  # Only the original embedded catalog probe.
        self.engine.stop.assert_not_called()
        self.engine.start.assert_not_called()

    def test_unavailable_preview_does_not_affect_map_validation(self):
        source = {"embedded": False, "value": str(self.custom)}
        self.assertEqual(self.control.preview(source), {"tiles": []})
        outside = self.folder / "other.yaml"
        outside.write_text("tiles: {}")
        (self.custom / "tiles.yaml").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "regular YAML layer files"):
            self.control.preview(source)
        self.assertIn("ticket", self.control.prepare(source))
        self.engine.stop.assert_not_called()
        self.engine.start.assert_not_called()

    def test_prepare_does_not_replace_engine_and_apply_keeps_launch_options(self):
        source = {"embedded": False, "value": "work maps/loop"}
        ticket = self.control.prepare(source)["ticket"]
        with self.assertRaisesRegex(ValueError, "already changing"):
            self.control.prepare({"embedded": True, "value": "empty"})
        self.engine.stop.assert_not_called()
        self.assertEqual(self.control.status()["current"], {"embedded": True, "value": "loop"})

        self.assertTrue(self.apply(ticket)["ready"])
        self.assertTrue(self.apply(ticket)["ready"])
        self.engine.start.assert_called_once()
        self.assertEqual(self.engine.config["command"], self.original["command"])
        self.assertEqual(self.engine.config["ports"], self.original["ports"])
        self.assertEqual(self.engine.config["volumes"], self.original["volumes"])
        mount, = self.engine.config["mounts"]
        self.assertEqual((mount["Source"], mount["Target"]), (str(self.custom), "/maps/loop"))
        self.assertTrue(mount["ReadOnly"])
        self.assertEqual(self.control.status()["current"], {"embedded": False, "value": str(self.custom)})
        self.assertIn("loop", self.control.status()["embedded_maps"])
        self.assertEqual(self.control.status()["factory"], {"embedded": True, "value": "loop"})

        ticket = self.control.prepare({"embedded": True, "value": "loop"})["ticket"]
        self.assertTrue(self.apply(ticket)["ready"])
        self.assertNotIn("mounts", self.engine.config)

    def test_invalid_and_unchanged_selections_leave_engine_running(self):
        for embedded, value in ((True, "loop"), (True, "not embedded"), (False, "missing")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.control.prepare({"embedded": embedded, "value": value})
        self.probe.side_effect = ContainerError(Mock(), 1, "probe", "test", b"bad layers")
        with self.assertRaisesRegex(ValueError, "rejected this map"):
            self.control.prepare({"embedded": False, "value": str(self.custom)})
        self.engine.stop.assert_not_called()

    def test_failed_replacement_restores_previous_map_before_reporting_ready(self):
        self.engine.wait_until_healthy.side_effect = [TimeoutError(), None]
        ticket = self.control.prepare({"embedded": True, "value": "empty"})["ticket"]
        reply = self.apply(ticket)
        self.assertTrue(reply["ready"])
        self.assertIn("previous map was restored", reply["error"])
        self.assertEqual(self.engine.config["command"], self.original["command"])
        self.assertEqual(self.control.status()["current"], {"embedded": True, "value": "loop"})
        self.assertEqual(self.engine.start.call_count, 2)

    def test_local_http_service_requires_launch_capability_and_same_origin(self):
        with MapControlHTTPServer(self.control) as server:
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                origin = f"http://127.0.0.1:{server.server_port}"
                url = origin + MAP_CONTROL_PATH
                headers = {MAP_CONTROL_HEADER: self.control.token, "Origin": origin}
                self.assertEqual(requests.get(url, timeout=3).status_code, 403)
                forged = dict(headers, Origin="https://other.invalid")
                self.assertEqual(requests.get(url, headers=forged, timeout=3).status_code, 403)
                catalog = requests.get(url, headers=headers, timeout=3)
                self.assertEqual(catalog.json()["embedded_maps"], ["empty", "loop", "sandbox"])
                self.assertTrue(catalog.json()["can_preview_maps"])
                self.assertEqual(catalog.headers["Cache-Control"], "no-store")

                # Previewing another map does not overwrite a prepared selection or apply it.
                ticket = self.control.prepare({"embedded": True, "value": "empty"})["ticket"]
                preview = origin + MAP_PREVIEW_PATH
                selection = {"embedded": True, "value": "loop"}
                self.assertEqual(requests.post(preview, json=selection, timeout=3).status_code, 403)
                self.assertEqual(requests.post(preview, json=selection, headers=forged, timeout=3).status_code, 403)
                self.assertEqual(requests.get(preview, headers=headers, timeout=3).status_code, 405)
                response = requests.post(preview, json=selection, headers=headers, timeout=3)
                self.assertEqual(response.json(), self.loop_layout)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                response = requests.post(preview, json={**selection, "value": "sandbox"}, headers=headers, timeout=3)
                self.assertEqual(response.status_code, 400)
                self.assertIn("planar", response.json()["error"])
                self.engine.stop.assert_not_called()
                self.engine.start.assert_not_called()
                self.assertTrue(self.apply(ticket)["ready"])
                self.assertEqual(self.control.status()["current"]["value"], "empty")
            finally:
                server.shutdown()
                thread.join()


class MatrixMapControlLaunchTests(RendererLaunchFixture):
    def test_standalone_browser_starts_map_control_unless_engine_builds_assets(self):
        flags = [
            "--standalone", "--embedded", "--map", "sandbox",
            "--verbose", "--version", "test", "--no-pull", "--browser",
        ]
        configured = renderer_command.RendererLaunchConfiguration(
            app_bin=None, app_config=[], app_path="/test/browser",
            app_prefix=[], os_family="linux", renderer_log_path=None,
        )
        for source, build_assets in ((flags, False), (flags, True),
                                     (["--standalone", "--sandbox", "--no-pull", "--browser"], False)):
            with self.subTest(source=source, build_assets=build_assets):
                command = ["--map", "sandbox"]
                if build_assets:
                    command.append("--build-assets")
                engine = Mock(config={"command": command})
                self.shell.include.matrix.engine.run.make_engine.return_value = engine
                server = SimpleNamespace(server=Mock(), display_host="localhost", port=8080)
                map_control = Mock(token="test-map-token")
                map_control.wait_for_engine.return_value = True
                with (
                    patch.object(renderer_command.DTCommand, "parser", self.parser),
                    patch.object(renderer_command, "should_run_host_renderer_only", return_value=False),
                    patch.object(renderer_command, "should_delegate_matrix_run", return_value=False),
                    patch.object(renderer_command, "resolve_delegated_engine_host", return_value=None),
                    patch.object(renderer_command, "configure_renderer_launch", return_value=configured),
                    patch.object(renderer_command, "create_browser_http_server", return_value=server),
                    patch.object(renderer_command, "MapControl", return_value=map_control) as make_map_control,
                    patch.object(renderer_command, "Thread"),
                    patch.object(renderer_command.os, "chdir"),
                    patch.dict(renderer_command.os.environ, {"DOCKER_HOST": ""}),
                    patch.object(renderer_command, "open_browser_url", return_value=True) as open_browser,
                ):
                    renderer_command.DTCommand.command(self.shell, source)
                engine.start.assert_called_once()
                engine.wait_until_healthy.assert_called_once_with(20)
                url = urlsplit(open_browser.call_args.args[0])
                self.assertNotIn("select-map", parse_qs(url.query))
                fragment = parse_qs(url.fragment)
                if build_assets:
                    make_map_control.assert_not_called()
                    self.assertIsNone(server.server.map_control)
                    self.assertNotIn("map-token", fragment)
                else:
                    make_map_control.assert_called_once_with(engine, Path.cwd())
                    self.assertIs(server.server.map_control, map_control)
                    self.assertEqual(fragment["map-token"], ["test-map-token"])
