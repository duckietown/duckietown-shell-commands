import base64
from contextlib import contextmanager
import importlib.util
import io
import http.client
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

from cryptography.hazmat.primitives import serialization
import dt_data_api
from dt_shell.exceptions import UserError
from dt_shell import __version__ as shell_version, renderer
from matrix.run import command as run
from matrix.run.configuration import DTCommandConfiguration as RunConfiguration
from matrix.install import command as install
from matrix.install.configuration import DTCommandConfiguration as InstallConfiguration
from matrix.devel.release import command as publish
from matrix.devel.release.configuration import (
    DTCommandConfiguration as PublishConfiguration,
)
from utils import duckiematrix_utils


SHELL_ROOT = Path(__file__).resolve().parents[2] / "duckietown-shell"
SPEC = importlib.util.spec_from_file_location(
    "renderer_test_fixtures", SHELL_ROOT / "lib/dt_shell_tests/test_renderer.py"
)
FIXTURES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURES)
RELEASE_SPEC = importlib.util.spec_from_file_location(
    "matrix_publisher_release_tools",
    SHELL_ROOT.parent / "duckiematrix/tools/renderer_release.py",
)
RELEASE_TOOLS = importlib.util.module_from_spec(RELEASE_SPEC)
RELEASE_SPEC.loader.exec_module(RELEASE_TOOLS)


class MatrixAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="matrix-authorization-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixture = FIXTURES.RendererFixture(self.root)
        self.build = self.fixture.release()
        self.identity = "DT2-IDENTITY-MUST-NOT-BE-IN-RENDERER-ARGUMENTS"
        self.shell = MagicMock()
        self.shell.profile.secrets.dt_token = self.identity
        self.shell.get_billboard_names.return_value = []
        for mock in (
            patch.object(run.DTCommand, "parser", RunConfiguration.parser()),
            patch.object(install.DTCommand, "parser", InstallConfiguration.parser()),
            patch.object(publish.DTCommand, "parser", PublishConfiguration.parser()),
            patch(
                "dt_shell.renderer._trust",
                return_value=(self.fixture.release_public, self.fixture.issuers),
            ),
            patch.object(
                run.DTShellDatabase,
                "open",
                return_value=SimpleNamespace(yaml=str(self.root / "billboards.yaml")),
            ),
            patch.object(run, "should_run_linux_renderer_through_fex", return_value=False),
            patch.object(run, "is_arm64_windows_host", return_value=False),
            patch.object(run, "should_delegate_matrix_run", return_value=False),
            patch.object(run, "host_runner_engine_host", return_value=None),
            patch.object(run, "should_run_host_renderer_only", return_value=False),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def test_command_set_version_floor_matches_the_new_shell_runtime(self):
        from __command_set__.configuration import DTCommandSetConfiguration

        minimum = DTCommandSetConfiguration.minimum_shell_version()
        self.assertEqual((6, 3, 1), minimum)
        self.assertLess((6, 2, 27), minimum)
        self.assertGreaterEqual(tuple(map(int, shell_version.split("."))), minimum)

    def test_configuration_passes_no_identity_and_requires_authenticated_artifacts(
        self,
    ):
        parsed = RunConfiguration.parser().parse_args(
            [
                "--renderer-binary",
                str(self.build / "duckiematrix.x86_64"),
                "--os-family",
                "linux",
            ]
        )
        config = run.configure_renderer_launch(self.shell, parsed, None)
        self.assertFalse(config.development)
        self.assertEqual("0.12.0", config.release["version"])
        self.assertNotIn("--token", config.app_config)
        self.assertNotIn(self.identity, config.app_config)
        (self.build / "duckiematrix.x86_64").write_bytes(b"altered")
        with self.assertRaises(UserError):
            run.configure_renderer_launch(self.shell, parsed, None)

    def test_unsigned_custom_builds_and_editor_choose_developer_permission(self):
        (self.build / renderer.RENDERER_MANIFEST).unlink()
        parsed = RunConfiguration.parser().parse_args(
            [
                "--renderer-binary",
                str(self.build / "duckiematrix.x86_64"),
                "--os-family",
                "linux",
            ]
        )
        config = run.configure_renderer_launch(self.shell, parsed, None)
        self.assertTrue(config.development)
        self.assertIsNone(config.release)
        editor = run.configure_renderer_launch(
            self.shell,
            RunConfiguration.parser().parse_args(["--renderer-editor"]),
            None,
        )
        self.assertTrue(editor.development)
        self.assertIsNone(editor.app_bin)

    def test_fex_prefix_preserves_authorization_configuration(self):
        parsed = RunConfiguration.parser().parse_args(
            [
                "--renderer-binary",
                str(self.build / "duckiematrix.x86_64"),
                "--os-family",
                "linux",
            ]
        )
        with patch.object(run, "should_run_linux_renderer_through_fex", return_value=True), patch.object(
            run, "find_fex_executable", return_value="/usr/bin/FEX"
        ):
            config = run.configure_renderer_launch(self.shell, parsed, None)
        self.assertEqual(["/usr/bin/FEX"], config.app_prefix)
        self.assertIsNotNone(config.release)

    def test_linux_container_gets_the_host_machine_identity_and_local_session(self):
        command, name = run._build_renderer_container_command(
            str(self.build / "duckiematrix.x86_64"),
            ["--dts-session", "http://127.0.0.1:1234/renderer/" + "d" * 32 + "/proof"],
            "renderer-image",
        )
        self.assertIn("--network", command)
        self.assertIn("host", command)
        self.assertTrue(any("machine-id:ro" in argument for argument in command))
        self.assertNotIn(self.identity, command)

    def configuration(self, platform="linux", browser=False):
        root = (
            self.build
            if platform == "linux" and not browser
            else self.fixture.release("webgl" if browser else platform)
        )
        app = root / (
            "duckiematrix"
            if browser
            else {
                "linux": "duckiematrix.x86_64",
                "windows": "Duckiematrix.exe",
                "macos": "duckiematrix.app",
            }[platform]
        )
        return run.RendererLaunchConfiguration(
            app_bin=None if browser else str(app),
            app_config=[],
            app_path=str(app),
            app_prefix=[],
            os_family=platform,
            renderer_log_path=None,
            release=renderer.verify_renderer_release(root),
            development=False,
        )

    def fake_session(self):
        return SimpleNamespace(
            url="http://127.0.0.1:1234/renderer/" + "d" * 32 + "/proof",
            origin=None,
            close=MagicMock(),
            stop_event=MagicMock(),
            error=None,
        )

    def test_native_windows_macos_and_container_launches_receive_only_a_session_endpoint(
        self,
    ):
        for platform, extra in (
            ("linux", []),
            ("windows", []),
            ("macos", []),
            ("linux", ["--container-image", "renderer-image"]),
        ):
            with self.subTest(platform=platform, extra=extra):
                config = self.configuration(platform)
                parsed = RunConfiguration.parser().parse_args(extra)
                session = self.fake_session()
                with patch.object(run, "configure_renderer_launch", return_value=config), patch.object(
                    run, "RendererSession", return_value=session
                ), patch.object(
                    run,
                    "get_macos_app_executable",
                    return_value=str(self.root / "macos-native"),
                ), patch.object(
                    run,
                    "launch_renderer_process",
                    return_value=(MagicMock(), io.BytesIO()),
                ) as launcher, patch.object(
                    run, "join_renderer"
                ), patch.object(
                    run, "process_is_running", return_value=False
                ), patch.object(
                    run, "time"
                ) as clock:
                    run.DTCommand.command(self.shell, [], parsed=parsed)
                command = launcher.call_args.args[0]
                self.assertIn("--dts-session", command)
                self.assertIn(session.url, command)
                self.assertNotIn(self.identity, command)
                self.assertNotIn("--token", command)
                session.close.assert_called_once()

    def test_browser_url_and_served_directory_contain_no_identity_token(self):
        config = self.configuration(browser=True)
        parsed = RunConfiguration.parser().parse_args(["--browser"])
        session = self.fake_session()
        server = MagicMock()
        server_config = SimpleNamespace(server=server, display_host="localhost", port=12345)
        with patch.object(run, "configure_renderer_launch", return_value=config), patch.object(
            run, "RendererSession", return_value=session
        ), patch.object(
            run, "create_browser_http_server", return_value=server_config
        ) as create, patch.object(
            run, "open_browser_url", return_value=True
        ) as browser:
            run.DTCommand.command(self.shell, [], parsed=parsed)
        url = browser.call_args.args[0]
        self.assertIn("/duckiematrix/?", url)
        self.assertIn("dts-session=http%3A", url)
        self.assertNotIn(self.identity, url)
        self.assertNotIn("token=", url)
        self.assertEqual(str(Path(config.app_path).parent), create.call_args.kwargs["directory"])
        self.assertEqual("http://localhost:12345", session.origin)
        session.close.assert_called_once()
        server.server_close.assert_called_once()

    def test_host_delegation_mints_no_container_side_renderer_permission(self):
        parsed = RunConfiguration.parser().parse_args([])
        with patch.object(run, "should_delegate_matrix_run", return_value=True), patch.object(
            run, "delegate_matrix_run_to_host", return_value=0
        ) as delegate, patch.object(run, "RendererSession") as session:
            run.DTCommand.command(self.shell, [], parsed=parsed)
        delegate.assert_called_once()
        session.assert_not_called()

    def test_windows_browser_launch_preserves_the_encoded_session_endpoint(self):
        config = self.configuration(platform="windows", browser=True)
        parsed = RunConfiguration.parser().parse_args(["--browser"])
        session = self.fake_session()
        server = MagicMock()
        server_config = SimpleNamespace(server=server, display_host="localhost", port=12345)
        with patch.object(run, "configure_renderer_launch", return_value=config), patch.object(
            run, "RendererSession", return_value=session
        ), patch.object(run, "create_browser_http_server", return_value=server_config), patch.object(
            run.subprocess, "run", side_effect=FileNotFoundError("cmd.exe")
        ) as command, patch.object(
            run, "open_browser_url", return_value=True
        ) as browser:
            run.DTCommand.command(self.shell, [], parsed=parsed)
        url = browser.call_args.args[0]
        self.assertNotIn("^&", url)
        self.assertIn("dts-session=http%3A", url)
        command.assert_not_called()
        session.close.assert_called_once()
        server.server_close.assert_called_once()

    def test_editor_mode_keeps_dts_alive_without_launching_a_binary(self):
        parsed = RunConfiguration.parser().parse_args(["--renderer-editor"])
        session = self.fake_session()
        session.stop_event.wait.return_value = True
        config = run.RendererLaunchConfiguration(
            app_bin=None,
            app_config=[],
            app_path=str(self.root),
            app_prefix=[],
            os_family="linux",
            renderer_log_path=None,
            release=None,
            development=True,
        )
        with patch.object(run, "configure_renderer_launch", return_value=config), patch.object(
            run, "RendererSession", return_value=session
        ) as authorization, patch.object(run, "launch_renderer_process") as launcher:
            run.DTCommand.command(self.shell, [], parsed=parsed)
        self.assertTrue(authorization.call_args.kwargs["development"])
        launcher.assert_not_called()
        session.close.assert_called_once()

    def test_installer_offline_fallback_requires_a_verified_existing_release(self):
        releases = self.root / "releases"
        releases.mkdir()
        destination = releases / "v0.12.0-linux"
        self.build.rename(destination)
        parsed = InstallConfiguration.parser().parse_args(["--update", "--os-family", "linux"])
        with patch.object(duckiematrix_utils, "APP_RELEASES_DIR", str(releases)), patch.object(
            install, "APP_RELEASES_DIR", str(releases)
        ), patch.object(install, "create_data_client"), patch.object(
            install,
            "get_latest_version",
            side_effect=dt_data_api.TransferError("offline"),
        ), patch.object(
            install.dtslogger, "warning"
        ) as warning:
            install.DTCommand.command(self.shell, [], parsed=parsed)
            self.assertTrue(any("verified installed" in str(call) for call in warning.call_args_list))
            (destination / "duckiematrix.x86_64").write_bytes(b"tampered")
            with self.assertRaises(UserError):
                install.DTCommand.command(self.shell, [], parsed=parsed)

    def archive_bytes(self, root):
        output = io.BytesIO()
        with ZipFile(output, "w") as archive:
            for path in root.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(root).as_posix())
        return output.getvalue()

    def test_installer_uses_python_atomic_archive_extraction_without_rm_or_unzip(self):
        releases = self.root / "releases"
        data = self.archive_bytes(self.build)
        parsed = InstallConfiguration.parser().parse_args(["--version", "0.12.0", "--os-family", "linux"])

        def download(shell, args, *, parsed):
            Path(parsed.file[0]).write_bytes(data)

        self.shell.include.data.get.command.side_effect = download
        with patch.object(duckiematrix_utils, "APP_RELEASES_DIR", str(releases)), patch.object(
            install, "APP_RELEASES_DIR", str(releases)
        ), patch.object(install, "create_data_client"), patch.object(
            install, "get_remote_release_checksum", return_value=None
        ):
            install.DTCommand.command(self.shell, [], parsed=parsed)
        renderer.verify_renderer_release(releases / "v0.12.0-linux")
        self.assertEqual([], list(releases.glob(".renderer-*")))

    def test_publication_verifies_readback_before_changing_latest_pointer(self):
        parsed = PublishConfiguration.parser().parse_args(
            ["--directory", str(self.build), "--os-family", "linux"]
        )
        download = MagicMock()
        download.data = self.archive_bytes(self.build)
        data_client = MagicMock()
        data_client.storage.return_value.download.return_value = download
        with patch.object(publish, "create_data_client", return_value=data_client), patch.object(
            publish, "is_version_released", return_value=False
        ), patch.object(publish, "get_latest_version", return_value="0.11.0"), patch.object(
            publish, "mark_as_latest_version"
        ) as latest:
            publish.DTCommand.command(self.shell, [], parsed=parsed)
            latest.assert_called_once()
            (self.build / "duckiematrix.x86_64").write_bytes(b"new publisher-approved code")
            envelope = json.loads((self.build / renderer.RENDERER_MANIFEST).read_bytes())
            claims = json.loads(base64.b64decode(envelope["payload"]))
            claims["files"] = renderer._inventory(self.build)
            (self.build / renderer.RENDERER_MANIFEST).write_bytes(
                renderer._canonical(renderer._signed(renderer._canonical(claims), self.fixture.release_key))
            )
            latest.reset_mock()
            with self.assertRaisesRegex(UserError, "differs"):
                publish.DTCommand.command(self.shell, [], parsed=parsed)
            latest.assert_not_called()

    @contextmanager
    def in_project(self):
        previous = Path.cwd()
        os.chdir(self.root)
        try:
            yield
        finally:
            os.chdir(previous)

    def unsigned_manual_build(self):
        self.build = self.build.rename(self.root / "Release")
        (self.build / renderer.RENDERER_MANIFEST).unlink()
        (self.build / "GameAssembly.so").write_bytes(
            (
                self.fixture.release_public
                + json.dumps(self.fixture.issuers, sort_keys=True, separators=(",", ":"))
                + "duckiematrix-renderer-official-v1"
            ).encode("ascii")
        )
        tools = self.root / "tools"
        tools.mkdir()
        (tools / "renderer_release.py").write_text("signing tool fixture")

    def signing_pem(self):
        return self.fixture.release_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")

    def run_release_tool(self, arguments, **kwargs):
        with patch.dict(os.environ, kwargs["env"], clear=True):
            if arguments[2] == "prepare":
                RELEASE_TOOLS.prepare(Path(arguments[3]), Path(arguments[4]))
            else:
                RELEASE_TOOLS.seal(
                    Path(arguments[3]),
                    arguments[5],
                    arguments[7],
                    RELEASE_TOOLS.private_key(),
                )
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    def test_manual_flat_release_is_prepared_signed_and_verified_without_changing_build(
        self,
    ):
        self.unsigned_manual_build()
        backup = self.build / next(iter(RELEASE_TOOLS.DEBUG_DIRECTORIES))
        backup.mkdir()
        (backup / "do-not-ship.cpp").write_text("debug source")
        download = MagicMock()
        data_client = MagicMock()
        data_client.storage.return_value.download.return_value = download
        stages = []

        def upload(shell, args, parsed):
            stage = Path(parsed.file[0])
            stages.append(stage)
            self.assertNotEqual(self.build, stage)
            self.assertFalse((stage / backup.name).exists())
            download.data = self.archive_bytes(stage)

        self.shell.include.data.push.command.side_effect = upload
        with self.in_project(), patch.dict(
            os.environ,
            {
                "DTM_RELEASE_SIGNING_KEY": self.signing_pem(),
                "DTM_RELEASE_SIGNING_KEY_FILE": "",
            },
        ), patch.object(publish, "get_os_family", return_value="linux"), patch.object(
            publish.subprocess, "run", side_effect=self.run_release_tool
        ) as tooling, patch.object(
            publish, "create_data_client", return_value=data_client
        ), patch.object(
            publish, "is_version_released", return_value=False
        ), patch.object(
            publish, "get_latest_version", return_value="0.11.0"
        ), patch.object(
            publish, "mark_as_latest_version"
        ) as latest:
            publish.DTCommand.command(self.shell, [])
            latest.assert_called_once()
            self.assertEqual(2, tooling.call_count)
            self.assertNotIn("DTM_RELEASE_SIGNING_KEY", tooling.call_args_list[0].kwargs["env"])
            self.assertIn("DTM_RELEASE_SIGNING_KEY", tooling.call_args_list[1].kwargs["env"])
            self.assertEqual(
                self.fixture.release_public,
                tooling.call_args_list[1].kwargs["env"]["DTM_RELEASE_PUBLIC_KEY"],
            )
            self.assertTrue(all(self.signing_pem() not in call.args[0] for call in tooling.call_args_list))
        self.assertFalse((self.build / renderer.RENDERER_MANIFEST).exists())
        self.assertTrue(backup.exists())
        self.assertFalse(stages[0].exists())

    def test_default_release_discovery_supports_platform_layout_and_rejects_ambiguity(
        self,
    ):
        nested = self.root / "Release" / "linux"
        nested.parent.mkdir()
        self.build.rename(nested)
        with self.in_project():
            self.assertEqual(nested, publish._build_directory(None, "linux"))
            (nested.parent / "Duckiematrix.json").write_text("{}")
            with self.assertRaisesRegex(UserError, "Both Release"):
                publish._build_directory(None, "linux")
            self.assertEqual(nested, publish._build_directory(str(nested), "linux"))

    def test_missing_signing_key_is_actionable_and_does_not_upload(self):
        self.unsigned_manual_build()
        with self.in_project(), patch.dict(
            os.environ,
            {"DTM_RELEASE_SIGNING_KEY": "", "DTM_RELEASE_SIGNING_KEY_FILE": ""},
        ), self.assertRaisesRegex(UserError, "publisher-only"):
            with publish._release_for_publication(self.build, "0.12.0", "linux"):
                self.fail("An unsigned build without a signing key was accepted.")
        self.shell.include.data.push.command.assert_not_called()
        self.assertFalse((self.build / renderer.RENDERER_MANIFEST).exists())

    def test_invalid_existing_manifest_is_not_automatically_resigned(self):
        (self.build / renderer.RENDERER_MANIFEST).write_text("corrupt manifest")
        with patch.object(publish.subprocess, "run") as tooling, self.assertRaises(UserError):
            with publish._release_for_publication(self.build, "0.12.0", "linux"):
                self.fail("An invalid signed build was accepted.")
        tooling.assert_not_called()

    def test_signing_failure_does_not_upload_or_modify_the_source_build(self):
        self.unsigned_manual_build()
        before = renderer._inventory(self.build)
        data_client = MagicMock()
        failure = subprocess.CalledProcessError(1, ["seal"], stderr="artifact signing key does not match")
        with self.in_project(), patch.dict(
            os.environ,
            {
                "DTM_RELEASE_SIGNING_KEY": self.signing_pem(),
                "DTM_RELEASE_SIGNING_KEY_FILE": "",
            },
        ), patch.object(publish, "get_os_family", return_value="linux"), patch.object(
            publish.subprocess, "run", side_effect=failure
        ), patch.object(
            publish, "create_data_client", return_value=data_client
        ), patch.object(
            publish, "is_version_released", return_value=False
        ), patch.object(
            publish, "get_latest_version", return_value="0.11.0"
        ), patch.object(
            publish, "mark_as_latest_version"
        ) as latest, self.assertRaisesRegex(
            UserError, "nothing was uploaded"
        ):
            publish.DTCommand.command(self.shell, [])
        self.shell.include.data.push.command.assert_not_called()
        latest.assert_not_called()
        self.assertEqual(before, renderer._inventory(self.build))

    def test_artifact_private_key_cannot_be_inside_the_project_or_build(self):
        self.unsigned_manual_build()
        key = self.root / "artifact-private.pem"
        key.write_text(self.signing_pem())
        with self.in_project(), patch.dict(
            os.environ,
            {"DTM_RELEASE_SIGNING_KEY": "", "DTM_RELEASE_SIGNING_KEY_FILE": str(key)},
        ), self.assertRaisesRegex(UserError, "outside the project"):
            with publish._release_for_publication(self.build, "0.12.0", "linux"):
                self.fail("An in-project signing key was accepted.")

    def test_internal_editor_call_gets_defaults_for_new_authorization_flags(self):
        session = self.fake_session()
        session.stop_event.wait.return_value = True
        with patch.object(run, "RendererSession", return_value=session) as authorization:
            run.DTCommand.command(self.shell, [], parsed=SimpleNamespace(renderer_editor=True))
        self.assertTrue(authorization.call_args.kwargs["development"])
        self.assertFalse(authorization.call_args.kwargs["renew"])
        session.close.assert_called_once()

    def test_download_failure_is_explicit_and_preserves_the_installed_release(self):
        releases = self.root / "releases"
        releases.mkdir()
        destination = releases / "v0.12.0-linux"
        self.build.rename(destination)
        before = renderer.verify_renderer_release(destination)["sha256"]
        parsed = InstallConfiguration.parser().parse_args(
            ["--version", "0.12.0", "--os-family", "linux", "--force"]
        )
        self.shell.include.data.get.command.side_effect = dt_data_api.TransferError("download interrupted")
        with patch.object(duckiematrix_utils, "APP_RELEASES_DIR", str(releases)), patch.object(
            install, "APP_RELEASES_DIR", str(releases)
        ), patch.object(install, "create_data_client"), patch.object(
            install, "get_remote_release_checksum", return_value=None
        ), self.assertRaisesRegex(
            UserError, "not changed"
        ):
            install.DTCommand.command(self.shell, [], parsed=parsed)
        self.assertEqual(before, renderer.verify_renderer_release(destination)["sha256"])
        self.assertEqual([], list(releases.glob(".renderer-*")))

    def test_publication_readback_failure_never_advances_latest(self):
        parsed = PublishConfiguration.parser().parse_args(
            ["--directory", str(self.build), "--os-family", "linux"]
        )
        data_client = MagicMock()
        data_client.storage.return_value.download.return_value.join.side_effect = dt_data_api.TransferError(
            "readback interrupted"
        )
        with patch.object(publish, "create_data_client", return_value=data_client), patch.object(
            publish, "is_version_released", return_value=False
        ), patch.object(publish, "get_latest_version", return_value="0.11.0"), patch.object(
            publish, "mark_as_latest_version"
        ) as latest, self.assertRaisesRegex(
            UserError, "latest pointer"
        ):
            publish.DTCommand.command(self.shell, [], parsed=parsed)
        latest.assert_not_called()

    def test_actual_browser_server_serves_the_signed_root_and_webgl_entrypoint(self):
        root = self.fixture.release("webgl")
        config = run.create_browser_http_server("127.0.0.1", 0, directory=str(root))
        thread = threading.Thread(target=config.server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", config.port, timeout=5)
        try:
            for path in ("/duckiematrix/index.html", "/" + renderer.RENDERER_MANIFEST):
                connection.request("GET", path)
                response = connection.getresponse()
                self.assertEqual(200, response.status)
                self.assertTrue(response.read())
            self.assertTrue(thread.is_alive())
        finally:
            connection.close()
            config.server.shutdown()
            config.server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
