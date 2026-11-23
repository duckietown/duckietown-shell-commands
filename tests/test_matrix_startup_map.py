from threading import Event, Thread
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from matrix.engine.run.command import MatrixEngine
from matrix.run import command as renderer_command
from matrix.run.map_control import MapControl
from tests.matrix_fixtures import (
    EngineConfigurationFixture,
    MapControlFixture,
    RendererLaunchFixture,
)


class MatrixMaplessEngineTests(EngineConfigurationFixture):
    def test_only_combined_launcher_can_configure_an_engine_without_a_map(self):
        flags = ["--engine-name", "deferred-test-engine", "--gym", "--environments", "3", "--port-offset", "1000"]
        engine = MatrixEngine()
        self.assertFalse(engine.configure(self.shell, self.parser.parse_args(flags)))
        self.assertFalse(engine.configure(self.shell, self.parser.parse_args([*flags, "--embedded"]), defer_map=True))
        self.assertTrue(engine.configure(self.shell, self.parser.parse_args(flags), defer_map=True))
        command = engine.config["command"]
        self.assertNotIn("--map", command)
        for option, value in (("--mode", "gym"), ("--environments", "3"),
                              ("--matrix-websocket-bridge-control-out-port", "8503")):
            self.assertEqual(command[command.index(option) + 1], value)


class MatrixStartupMapControlTests(MapControlFixture):
    def open_startup_picker(self):
        container = self.engine.engine
        self.engine.engine = None
        self.engine.config = {**self.original, "command": self.original["command"][:-2]}
        client = container.client
        client.images.get.return_value = container.image
        with patch("matrix.run.map_control.get_client_OLD", return_value=client):
            self.control = MapControl(self.engine, self.folder)
        self.addCleanup(self.control.close)
        client.images.get.assert_called_once_with(self.original["image"])

        def start():
            self.engine.engine = container
            return True

        self.engine.start.side_effect = start
        self.engine.stop.side_effect = lambda: setattr(self.engine, "engine", None)
        return container

    def test_browser_waits_for_a_map_and_then_for_that_engine(self):
        container = self.open_startup_picker()
        engine_waiting, engine_exited, browser_done = Event(), Event(), Event()
        results = []

        def wait_for_engine_exit():
            engine_waiting.set()
            engine_exited.wait(4)

        def wait_for_browser():
            results.append(self.control.wait_for_engine())
            browser_done.set()

        container.wait.side_effect = wait_for_engine_exit
        browser_waiter = Thread(target=wait_for_browser)
        self.addCleanup(browser_waiter.join, 4)
        self.addCleanup(engine_exited.set)
        self.addCleanup(self.control.close)
        browser_waiter.start()

        catalog = self.control.status()
        self.assertTrue(catalog["awaiting_selection"])
        self.assertIsNone(catalog["current"])
        self.assertIsNone(catalog["factory"])
        self.assertEqual(self.control.preview({"embedded": True, "value": "loop"}), self.loop_layout)
        self.assertTrue(self.control.status()["awaiting_selection"])
        ticket = self.control.prepare({"embedded": True, "value": "empty"})["ticket"]
        self.assertFalse(browser_done.wait(0.05))
        self.engine.start.assert_not_called()
        self.engine.wait_until_healthy.assert_not_called()
        self.assertTrue(self.apply(ticket)["ready"])
        self.assertTrue(engine_waiting.wait(2))
        self.assertFalse(browser_done.is_set())
        self.assertTrue(self.control.status()["ready"])
        self.assertEqual(self.control.status()["current"], {"embedded": True, "value": "empty"})
        self.assertFalse(self.control.apply("unrelated-ticket").get("ready", False))
        self.engine.stop.assert_not_called()
        engine_exited.set()
        browser_waiter.join(3)
        self.assertEqual(results, [True])

    def test_invalid_or_failed_first_start_can_retry_with_a_custom_path(self):
        self.open_startup_picker()
        with self.assertRaisesRegex(ValueError, "could not be opened"):
            self.control.prepare({"embedded": False, "value": "missing"})
        with patch("matrix.run.map_control.monotonic", return_value=monotonic() - 61):
            expired = self.control.prepare({"embedded": True, "value": "empty"})["ticket"]
        self.assertFalse(self.control.apply(expired)["ready"])
        self.engine.start.assert_not_called()
        self.assertIsNone(self.control.status()["factory"])

        self.engine.wait_until_healthy.side_effect = [TimeoutError(), None, None]
        custom = {"embedded": False, "value": "work maps/loop"}
        first = self.control.prepare(custom)["ticket"]
        reply = self.apply(first)
        self.assertIn("Could not start the Engine", reply["error"])
        self.assertFalse(reply.get("ready", False))
        self.assertTrue(self.control.status()["awaiting_selection"])
        self.assertIsNone(self.engine.engine)
        self.assertIsNone(self.control.status()["factory"])

        second = self.control.prepare(custom)["ticket"]
        self.assertTrue(self.apply(second)["ready"])
        self.assertEqual(self.control.status()["current"], {"embedded": False, "value": str(self.custom)})
        mount, = self.engine.config["mounts"]
        self.assertEqual((mount["Source"], mount["Target"]), (str(self.custom), "/maps/loop"))
        self.assertTrue(mount["ReadOnly"])
        self.assertEqual(self.engine.config["image"], "sha256:original")
        self.assertEqual(self.control.status()["factory"], {"embedded": False, "value": str(self.custom)})
        self.assertEqual(self.engine.config["command"], self.original["command"])
        self.assertEqual(self.engine.config["ports"], self.original["ports"])
        self.assertEqual(self.engine.config["volumes"], self.original["volumes"])
        third = self.control.prepare({"embedded": True, "value": "empty"})["ticket"]
        self.assertTrue(self.apply(third)["ready"])
        self.assertEqual(self.control.status()["factory"], {"embedded": False, "value": str(self.custom)})
        self.assertEqual(self.control.status()["current"], {"embedded": True, "value": "empty"})


class MatrixStartupMapLaunchTests(RendererLaunchFixture):
    def test_mapless_browser_launch_reaches_the_picker_without_starting_an_engine(self):
        flags = ["--standalone", "--browser", "--no-pull"]
        engine = Mock(config={"command": ["--mode", "realtime"]})
        make_engine = self.shell.include.matrix.engine.run.make_engine
        make_engine.return_value = engine
        configured = renderer_command.RendererLaunchConfiguration(
            app_bin=None, app_config=[], app_path="/test/browser",
            app_prefix=[], os_family="linux", renderer_log_path=None,
        )
        server = SimpleNamespace(server=Mock(), display_host="localhost", port=8080)
        control = Mock(token="test-map-token")
        with (
            patch.object(renderer_command.DTCommand, "parser", self.parser),
            patch.object(renderer_command, "should_run_host_renderer_only", return_value=False),
            patch.object(renderer_command, "should_delegate_matrix_run", return_value=False),
            patch.object(renderer_command, "resolve_delegated_engine_host", return_value=None),
            patch.object(renderer_command, "configure_renderer_launch", return_value=configured),
            patch.object(renderer_command, "create_browser_http_server", return_value=server),
            patch.object(renderer_command, "MapControl", return_value=control),
            patch.object(renderer_command, "Thread"),
            patch.object(renderer_command.os, "chdir"),
            patch.dict(renderer_command.os.environ, {"DOCKER_HOST": ""}),
            patch.object(renderer_command, "open_browser_url", return_value=True) as open_browser,
        ):
            renderer_command.DTCommand.command(self.shell, flags)
        self.assertTrue(make_engine.call_args.kwargs["defer_map"])
        engine.start.assert_not_called()
        engine.wait_until_healthy.assert_not_called()
        self.assertIs(server.server.map_control, control)
        url = urlsplit(open_browser.call_args.args[0])
        self.assertEqual(parse_qs(url.query)["select-map"], ["true"])
        self.assertEqual(parse_qs(url.fragment)["map-token"], ["test-map-token"])
        control.wait_for_engine.assert_called_once()

    def test_mapless_native_launch_keeps_the_engine_and_picker_on_the_launcher_host(self):
        flags = ["--standalone", "--local", "--no-pull"]
        engine = Mock(config={"command": ["--mode", "realtime"]})
        self.shell.include.matrix.engine.run.make_engine.return_value = engine
        configured = renderer_command.RendererLaunchConfiguration(
            app_bin="/test/renderer", app_config=[], app_path="/test/renderer",
            app_prefix=[], os_family="linux", renderer_log_path=None,
        )
        control = Mock(token="test-map-token")
        with (
            patch.object(renderer_command.DTCommand, "parser", self.parser),
            patch.object(renderer_command, "should_run_host_renderer_only", return_value=False),
            patch.object(renderer_command, "should_delegate_matrix_run", return_value=True),
            patch.object(renderer_command, "resolve_delegated_engine_host", return_value="remote-host"),
            patch.object(renderer_command, "configure_renderer_launch", return_value=configured) as configure,
            patch.object(renderer_command, "MapControl", return_value=control),
            patch.object(renderer_command, "MapControlHTTPServer", return_value=Mock(server_port=8001)),
            patch.object(renderer_command, "Thread"),
            patch.object(renderer_command.os, "makedirs"),
            patch.object(renderer_command.time, "sleep"),
            patch.object(renderer_command, "launch_renderer_process", return_value=(Mock(), Mock())) as launch,
            patch.object(renderer_command, "join_renderer"),
            patch.object(renderer_command.graphics_control, "enabled", return_value=False),
            patch.dict(renderer_command.os.environ, {"DOCKER_HOST": ""}),
        ):
            renderer_command.DTCommand.command(self.shell, flags)
        engine.start.assert_not_called()
        engine.wait_until_healthy.assert_not_called()
        self.assertIsNone(configure.call_args.args[2])
        self.assertEqual(launch.call_args.args[0], ["/test/renderer", "--select-map"])
        self.assertEqual(launch.call_args.kwargs["env"][renderer_command.MAP_CONTROL_PORT_ENV], "8001")
        self.assertEqual(launch.call_args.kwargs["env"][renderer_command.MAP_CONTROL_TOKEN_ENV], control.token)

    def test_delegated_startup_picker_keeps_the_engine_under_the_guest_launcher(self):
        flags = ["--standalone", "--no-pull"]
        engine = Mock(config={"command": ["--mode", "realtime"]})
        self.shell.include.matrix.engine.run.make_engine.return_value = engine
        token = "b" * 64
        with (
            patch.object(renderer_command.DTCommand, "parser", self.parser),
            patch.object(renderer_command, "should_run_host_renderer_only", return_value=False),
            patch.object(renderer_command, "should_delegate_matrix_run", return_value=True),
            patch.object(renderer_command, "resolve_delegated_engine_host", return_value="localhost"),
            patch.object(renderer_command, "MapControl", return_value=Mock(token=token)),
            patch.object(renderer_command, "MapControlHTTPServer", return_value=Mock(server_port=8120)),
            patch.object(renderer_command, "Thread"),
            patch.dict(renderer_command.os.environ, {"DOCKER_HOST": ""}),
            patch.object(renderer_command, "delegate_matrix_run_to_host", return_value=0) as delegate,
        ):
            renderer_command.DTCommand.command(self.shell, flags)
        self.assertTrue(self.shell.include.matrix.engine.run.make_engine.call_args.kwargs["defer_map"])
        engine.start.assert_not_called()
        delegate.assert_called_once_with(flags, engine_host="localhost", renderer_only=True,
                                         map_control=f"8120:{token}:1")

    def test_delegated_startup_without_a_forwarded_capability_fails_before_launch(self):
        with (
            patch.object(renderer_command.DTCommand, "parser", self.parser),
            patch.object(renderer_command, "should_run_host_renderer_only", return_value=True),
            patch.object(renderer_command, "delegated_map_control", return_value=None),
            patch.object(renderer_command, "configure_renderer_launch") as configure,
            patch.object(renderer_command.dtslogger, "error") as error,
        ):
            renderer_command.DTCommand.command(self.shell, ["--standalone"])
        configure.assert_not_called()
        self.assertIn("did not forward startup map selection", error.call_args.args[0])

    def test_embedded_with_no_map_is_rejected_before_launch(self):
        for flags in (["--standalone", "--embedded"], ["--standalone", "--embedded", "--sandbox"]):
            with (
                self.subTest(flags=flags),
                patch.object(renderer_command.DTCommand, "parser", self.parser),
                patch.object(renderer_command, "should_delegate_matrix_run", return_value=False),
                patch.object(renderer_command, "resolve_delegated_engine_host", return_value=None),
                patch.object(renderer_command, "configure_renderer_launch") as configure,
                patch.object(renderer_command.dtslogger, "error") as error,
            ):
                renderer_command.DTCommand.command(self.shell, flags)
                configure.assert_not_called()
                self.shell.include.matrix.engine.run.make_engine.assert_not_called()
                error.assert_called_once_with("--embedded requires -m/--map.")
