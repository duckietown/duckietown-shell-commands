from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from dt_shell import __version__
from dt_shell.exceptions import UserError
from matrix.run import command as run
from matrix.run.configuration import DTCommandConfiguration as RunConfiguration
from matrix.install import command as install
from matrix.install.configuration import DTCommandConfiguration as InstallConfiguration
from matrix.devel.release import command as publish
from matrix.devel.release.configuration import DTCommandConfiguration as PublishConfiguration


class MatrixPlanTests(unittest.TestCase):
    def test_command_set_requires_plan_aware_dts(self):
        from __command_set__.configuration import DTCommandSetConfiguration

        minimum = DTCommandSetConfiguration.minimum_shell_version()
        self.assertEqual((6, 3, 0), minimum)
        self.assertGreaterEqual(tuple(map(int, __version__.split("."))), minimum)

    def test_native_renderer_receives_a_plan_grant_not_the_identity_token(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "duckiematrix.x86_64"
            binary.write_bytes(b"fixture")
            parsed = RunConfiguration.parser().parse_args(
                ["--renderer-binary", str(binary), "--os-family", "linux"]
            )
            shell = MagicMock()
            shell.profile.secrets.dt_token = "DT2-identity-not-a-renderer-grant"
            shell.get_billboard_names.return_value = []
            with patch.object(
                run, "get_ente_authorization", return_value="DT2-use-ente-fixture"
            ) as authorization, patch.object(
                run, "should_run_linux_renderer_through_fex", return_value=False
            ):
                configuration = run.configure_renderer_launch(shell, parsed, None)
            authorization.assert_called_once_with(shell)
            arguments = configuration.app_config
            self.assertEqual("DT2-use-ente-fixture", arguments[arguments.index("--token") + 1])
            self.assertNotIn(shell.profile.secrets.dt_token, arguments)

    def test_denied_renderer_plan_stops_before_installation(self):
        shell = MagicMock()
        parsed = RunConfiguration.parser().parse_args([])
        with patch.object(
            run, "get_ente_authorization", side_effect=UserError("plan required")
        ), self.assertRaisesRegex(UserError, "plan required"):
            run.configure_renderer_launch(shell, parsed, None)
        shell.include.matrix.install.command.assert_not_called()

    def test_install_and_publication_check_the_plan_before_other_operations(self):
        for module, configuration in (
            (install, InstallConfiguration),
            (publish, PublishConfiguration),
        ):
            with self.subTest(command=module.__name__), patch.object(
                module.DTCommand, "parser", configuration.parser()
            ), patch.object(
                module, "get_ente_authorization", side_effect=UserError("plan required")
            ) as authorization:
                shell = MagicMock()
                with self.assertRaisesRegex(UserError, "plan required"):
                    module.DTCommand.command(shell, [])
                authorization.assert_called_once_with(shell)


if __name__ == "__main__":
    unittest.main()
