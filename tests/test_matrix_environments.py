import unittest
from types import SimpleNamespace
from unittest.mock import patch

from matrix.engine.run.command import DTCommand as EngineCommand, MatrixEngine
from matrix.engine.run.configuration import DTCommandConfiguration as EngineConfiguration
from matrix.run.configuration import DTCommandConfiguration as MatrixConfiguration
from utils.host_runner import (
    HOST_RUNNER_MATRIX_RENDERER_ONLY_FORWARD_ENV,
    delegate_matrix_run_to_host,
)


class MatrixEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.parser = EngineConfiguration.parser()
        distro = SimpleNamespace(name="ente")
        profile = SimpleNamespace(distro=distro)
        self.shell = SimpleNamespace(profile=profile)
        self.arguments = [
            "--embedded", "--map", "loop",
            "--engine-name", "replication-test-engine",
        ]
        architecture = patch(
            "matrix.engine.run.command.get_endpoint_architecture",
            return_value="arm64",
        )
        architecture.start()
        self.addCleanup(architecture.stop)
        docker = patch(
            "matrix.engine.run.command.get_client_OLD",
            side_effect=AssertionError("Configuration must not access Docker."),
        )
        docker.start()
        self.addCleanup(docker.stop)

    def test_default_preserves_legacy_engine_command(self):
        for arguments in ([], ["--environments", "1"]):
            with self.subTest(arguments=arguments):
                parsed = self.parser.parse_args(self.arguments + arguments)
                engine = MatrixEngine()
                configured = engine.configure(self.shell, parsed)
                self.assertTrue(configured)
                self.assertNotIn("--environments", engine.config["command"])

    def test_replication_is_forwarded_in_realtime_and_gym(self):
        for arguments, mode in (([], "realtime"), (["--gym"], "gym")):
            with self.subTest(mode=mode):
                arguments = self.arguments + arguments + ["--environments", "3"]
                parsed = self.parser.parse_args(arguments)
                engine = MatrixEngine()
                configured = engine.configure(self.shell, parsed)
                self.assertTrue(configured)
                command = engine.config["command"]
                count_index = command.index("--environments")
                mode_index = command.index("--mode")
                self.assertEqual(command[count_index + 1], "3")
                self.assertEqual(command[mode_index + 1], mode)

    def test_invalid_counts_are_rejected(self):
        for count in (0, -1, True, 1.5):
            with self.subTest(count=count):
                parsed = self.parser.parse_args(self.arguments)
                parsed.environments = count
                engine = MatrixEngine()
                configured = engine.configure(self.shell, parsed)
                self.assertFalse(configured)
                self.assertIsNone(engine.config)

    def test_unsupported_replication_options_are_rejected(self):
        for arguments in (
            ["--renderers", "2"],
            ["--link", "map_0/vehicle_0", "physical_robot"],
            ["--build-assets"],
        ):
            with self.subTest(arguments=arguments):
                arguments = self.arguments + arguments + ["--environments", "2"]
                parsed = self.parser.parse_args(arguments)
                engine = MatrixEngine()
                configured = engine.configure(self.shell, parsed)
                self.assertFalse(configured)
                self.assertIsNone(engine.config)

    def test_replicated_sandbox_is_rejected_before_docker(self):
        for mode in ([], ["--gym"]):
            with self.subTest(mode=mode):
                arguments = ["--sandbox", "--environments", "2"] + mode
                parsed = self.parser.parse_args(arguments)
                engine = MatrixEngine()
                with patch("matrix.engine.run.command.dtslogger.error") as error:
                    configured = engine.configure(self.shell, parsed)
                self.assertFalse(configured)
                self.assertIsNone(engine.config)
                error.assert_called_once()
                call = error.call_args
                self.assertIn("--embedded --map loop", call.args[0])

    def test_single_environment_sandbox_preserves_legacy_map(self):
        for arguments in ([], ["--environments", "1"]):
            with self.subTest(arguments=arguments):
                arguments = [
                    "--sandbox", "--engine-name", "replication-test-engine",
                ] + arguments
                parsed = self.parser.parse_args(arguments)
                engine = MatrixEngine()
                configured = engine.configure(self.shell, parsed)
                self.assertTrue(configured)
                command = engine.config["command"]
                map_index = command.index("--map")
                self.assertEqual(command[map_index + 1], "sandbox")
                self.assertNotIn("--environments", command)

    def test_combined_command_preserves_environment_count(self):
        parser = MatrixConfiguration.parser()
        arguments = self.arguments + ["--standalone", "--environments", "3", "--gym"]
        parsed = parser.parse_args(arguments)
        with patch.object(EngineCommand, "parser", self.parser):
            engine = EngineCommand.make_engine(self.shell, parsed, use_defaults=True)
        self.assertIsNotNone(engine)
        command = engine.config["command"]
        count_index = command.index("--environments")
        self.assertEqual(command[count_index + 1], "3")


class MatrixEnvironmentDelegationTests(unittest.TestCase):
    def setUp(self):
        delegate = patch("utils.host_runner.delegate_command_to_host", return_value=0)
        self.delegate = delegate.start()
        self.addCleanup(delegate.stop)
        cwd = patch("utils.host_runner._host_runner_fallback_cwd", return_value="/host")
        cwd.start()
        self.addCleanup(cwd.stop)
        options = patch("utils.host_runner.get_current_dts_cli_options", return_value=[])
        options.start()
        self.addCleanup(options.stop)

    def test_renderer_only_delegation_omits_engine_replication_option(self):
        for arguments in (
            ["--environments", "3"],
            ["--environments=3"],
        ):
            with self.subTest(arguments=arguments):
                arguments = ["--standalone", *arguments, "--verbose"]
                delegate_matrix_run_to_host(arguments, renderer_only=True)
                call = self.delegate.call_args
                self.assertEqual(call.args[1], ["--standalone", "--verbose"])
                environment = call.kwargs["forwarded_env"]
                self.assertEqual(
                    environment[HOST_RUNNER_MATRIX_RENDERER_ONLY_FORWARD_ENV], "1"
                )

    def test_full_host_delegation_preserves_environment_option(self):
        arguments = ["--standalone", "--environments", "3"]
        delegate_matrix_run_to_host(arguments)
        call = self.delegate.call_args
        self.assertEqual(call.args[1], arguments)