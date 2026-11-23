from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from matrix.run import command as renderer_command
from tests.matrix_fixtures import RendererLaunchFixture


class MatrixRendererLaunchTests(RendererLaunchFixture):
    def test_native_spectator_camera_option_preserves_tutorial_behavior(self):
        for platform in ("linux", "macos", "windows"):
            for disabled in (False, True):
                with self.subTest(platform=platform, disabled=disabled):
                    flags = ["--no-spectator-cameras"] if disabled else []
                    parsed = self.parser.parse_args([
                        "--renderer-binary", "/test/renderer",
                        "--os-family", platform, *flags,
                    ])
                    with (
                        patch.object(renderer_command.os.path, "isfile", return_value=True),
                        patch.object(renderer_command.os.path, "exists", return_value=True),
                        patch.object(renderer_command, "create_renderer_log_path", return_value=None),
                        patch.object(renderer_command, "should_run_linux_renderer_through_fex", return_value=False),
                        patch.object(renderer_command, "is_arm64_windows_host", return_value=False),
                        patch.object(renderer_command.DTShellDatabase, "open"),
                    ):
                        configured = renderer_command.configure_renderer_launch(
                            self.shell, parsed, None,
                        )
                    self.assertIsNotNone(configured)
                    self.assertEqual("--no-spectator-cameras" in configured.app_config, disabled)
                    self.assertEqual("--tutorial" in configured.app_config, not disabled)

    def test_browser_passes_engine_ports_and_preserves_tutorial_behavior(self):
        for disabled in (False, True):
            with self.subTest(disabled=disabled):
                flags = ["--browser", "--engine", "::1", "--port-offset", "1000"]
                if disabled:
                    flags.append("--no-spectator-cameras")
                parsed = self.parser.parse_args(flags)
                configured = renderer_command.RendererLaunchConfiguration(
                    app_bin=None, app_config=[], app_path="/test/browser",
                    app_prefix=[], os_family="linux", renderer_log_path=None,
                )
                server = SimpleNamespace(
                    server=Mock(), display_host="localhost", port=8080,
                )
                with (
                    patch.object(renderer_command.DTCommand, "parser", self.parser),
                    patch.object(renderer_command, "should_delegate_matrix_run", return_value=False),
                    patch.object(renderer_command, "resolve_delegated_engine_host", return_value=None),
                    patch.object(renderer_command, "configure_renderer_launch", return_value=configured),
                    patch.object(renderer_command, "create_browser_http_server", return_value=server),
                    patch.object(renderer_command, "Thread"),
                    patch.object(renderer_command.os, "chdir"),
                    patch.object(renderer_command, "open_browser_url", return_value=True) as open_browser,
                ):
                    renderer_command.DTCommand.command(self.shell, flags, parsed=parsed)
                query = parse_qs(urlsplit(open_browser.call_args.args[0]).query)
                self.assertEqual(query["engine-hostname"], ["::1"])
                self.assertEqual(query["engine-ws-control-port"], ["8503"])
                self.assertEqual(query["port-offset"], ["1000"])
                self.assertEqual(query["no-spectator-cameras"], [str(disabled).lower()])
                self.assertEqual(query["tutorial"], [str(not disabled).lower()])

    def test_linux_renderer_restarts_with_validated_api_and_rolls_back_a_failed_boot(self):
        flags = self.parser.parse_args(["--force-vulkan"])
        launches = []
        database = Mock()
        common = ["/test/renderer", "-force-vulkan", "--engine-hostname", "localhost"]

        def launch(command, env):
            launches.append((command, env.copy()))
            return Mock(poll=lambda: 0), Mock()

        def join(process, stream, verbose):
            env = launches[-1][1]
            request = Path(env[renderer_command.graphics_control.GRAPHICS_RESTART_FILE])
            if len(launches) == 1:
                request.write_text("opengl")
            elif len(launches) == 3:
                request.write_text("auto")
            elif len(launches) == 4:
                (request.parent / "ready").touch()

        with (
            patch.object(renderer_command.DTShellDatabase, "open", return_value=database),
            patch.object(renderer_command, "launch_renderer_process", side_effect=launch),
            patch.object(renderer_command, "join_renderer", side_effect=join),
        ):
            renderer_command.run_with_graphics_restart(common, "/test/renderer", flags, {"TEST_ENGINE": "keep"})
        self.assertEqual([cmd[-1] for cmd, _ in launches], ["-force-vulkan", "-force-glcore", "-force-vulkan", "localhost"])
        self.assertTrue(all(env["TEST_ENGINE"] == "keep" for _, env in launches))
        self.assertIn("Restored", launches[2][1][renderer_command.graphics_control.GRAPHICS_RESTART_ERROR])
        database.set.assert_called_once_with("linux", "auto")

    def test_graphics_restart_restores_the_original_api_if_process_creation_fails(self):
        flags = self.parser.parse_args(["--force-vulkan"])
        launches = []
        database = Mock()

        def launch(command, env):
            launches.append((command, env.copy()))
            if command[-1] == "-force-glcore":
                raise OSError(13, "Renderer could not be started")
            return Mock(poll=lambda: 0), Mock()

        def join(process, stream, verbose):
            if len(launches) == 1:
                Path(launches[0][1][renderer_command.graphics_control.GRAPHICS_RESTART_FILE]).write_text("opengl")

        with (
            patch.object(renderer_command.DTShellDatabase, "open", return_value=database),
            patch.object(renderer_command, "launch_renderer_process", side_effect=launch),
            patch.object(renderer_command, "join_renderer", side_effect=join),
        ):
            renderer_command.run_with_graphics_restart(["/test/renderer"], "/test/renderer", flags, {})
        self.assertEqual([cmd[-1] for cmd, _ in launches], ["-force-vulkan", "-force-glcore", "-force-vulkan"])
        self.assertIn("Restored", launches[2][1][renderer_command.graphics_control.GRAPHICS_RESTART_ERROR])
        database.set.assert_not_called()

    def test_redundant_no_tutorial_option_is_rejected_before_launch(self):
        flags = ["--no-spectator-cameras", "--no-tutorial"]
        parsed = self.parser.parse_args(flags)
        with (
            patch.object(renderer_command.DTCommand, "parser", self.parser),
            patch.object(renderer_command, "should_delegate_matrix_run", return_value=False),
            patch.object(renderer_command, "resolve_delegated_engine_host", return_value=None),
            patch.object(renderer_command, "configure_renderer_launch") as configure,
            patch.object(renderer_command.dtslogger, "error") as error,
        ):
            renderer_command.DTCommand.command(self.shell, flags, parsed=parsed)
        configure.assert_not_called()
        error.assert_called_once_with(
            "You cannot use --no-spectator-cameras and --no-tutorial together."
        )
