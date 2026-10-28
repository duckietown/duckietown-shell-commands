import unittest
from unittest.mock import Mock, patch

from matrix.run import command as matrix_run
from matrix.run.configuration import DTCommandConfiguration


class MatrixTimeOfFlightTests(unittest.TestCase):
    def test_native_renderer_forwards_opt_in_only(self):
        for enabled in (False, True):
            arguments = ["--renderer-binary", "/renderer", "--os-family", "windows"]
            if enabled:
                arguments.append("--gym-async-tof")
            parser = DTCommandConfiguration.parser()
            parsed = parser.parse_args(arguments)
            shell = Mock()
            shell.profile.secrets.dt_token = "test-token"
            shell.get_billboard_names.return_value = []
            with self.subTest(enabled=enabled):
                with (
                    patch.object(matrix_run.os.path, "isfile", return_value=True),
                    patch.object(matrix_run, "create_renderer_log_path", return_value=None),
                    patch.object(matrix_run.DTShellDatabase, "open"),
                ):
                    configuration = matrix_run.configure_renderer_launch(shell, parsed, None)
                self.assertIsNotNone(configuration)
                self.assertEqual("--gym-async-tof" in configuration.app_config, enabled)

    def test_browser_rejected_before_engine_or_renderer_configuration(self):
        arguments = ["--standalone", "--sandbox", "--gym", "--browser", "--gym-async-tof"]
        parser = DTCommandConfiguration.parser()
        parsed = parser.parse_args(arguments)
        shell = Mock()
        with (
            patch.object(matrix_run.DTCommand, "_resolve_parsed", return_value=parsed),
            patch.object(matrix_run, "should_run_host_renderer_only", return_value=False),
            patch.object(matrix_run, "should_delegate_matrix_run", return_value=False),
            patch.object(matrix_run, "configure_renderer_launch") as configure,
            patch.object(matrix_run.dtslogger, "error") as error,
        ):
            matrix_run.DTCommand.command(shell, arguments)
        configure.assert_not_called()
        shell.include.matrix.engine.run.make_engine.assert_not_called()
        error.assert_called_once_with("You cannot use --gym-async-tof together with --browser.")