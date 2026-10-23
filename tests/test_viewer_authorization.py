import importlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

import dt_shell
from dt_shell import UserError
from dt_shell_tests.test_viewer import DEVICE, ViewerFixture
from utils import duckietown_viewer_utils as viewer
from utils import viewer_authorization as authorization
from utils import viewer_release as publisher
from utils import host_runner as bridge


class LauncherTests(unittest.TestCase):
    def test_every_command_selects_its_app_and_browser_mode_needs_no_desktop(self):
        selectors = (
            "image_viewer", "keyboard_control", "calibrate_intrinsics",
            "calibrate_extrinsics", "led_control", "graph_plotter",
        )
        for selector in selectors:
            module = importlib.import_module(f"duckiebot.{selector}.command")
            for browser in (False, True):
                with self.subTest(selector=selector, browser=browser):
                    parsed = SimpleNamespace(
                        browser=browser, local=False, os_family="linux", robot="testbot", verbose=False,
                        fullscreen=False, on_top=False, enable_hardware_acceleration=False, no_pull=True,
                    )
                    with patch.object(module.DTCommand, "_resolve_parsed", return_value=parsed), patch.object(
                        module, "resolve_os_family", return_value="linux"
                    ), patch.object(module, "ensure_duckietown_viewer_installed") as install, patch.object(
                        module, "launch_viewer"
                    ) as launch, patch.object(module, "get_asset_icon_path", return_value="/icon"):
                        if selector == "graph_plotter":
                            module.DTCommand.command(MagicMock(), [])
                        else:
                            with patch.object(module, "should_delegate_viewer_frontend", return_value=False):
                                module.DTCommand.command(MagicMock(), [])
                    if browser:
                        install.assert_not_called()
                    else:
                        install.assert_called_once_with("linux", app=module.LAUNCHER_NAME)
                    self.assertEqual(module.LAUNCHER_NAME, launch.call_args.args[0])
                    self.assertEqual(browser, launch.call_args.kwargs["browser"])
                    self.assertTrue(launch.call_args.kwargs["no_pull"])
        from duckiebot.image_viewer.configuration import DTCommandConfiguration
        self.assertIn("image_view", DTCommandConfiguration.aliases())


class SourceMountsReached(Exception):
    pass


class SourceRunTests(unittest.TestCase):
    def setUp(self):
        self.run = importlib.import_module("devel.run.command")
        configuration = importlib.import_module("devel.run.configuration")
        self.read_original = importlib.import_module("dt_shell.viewer_runtime").read_handoff
        self.parsed = configuration.DTCommandConfiguration.parser().parse_args(["--arch", "amd64"])
        self.handoff = {
            "consumer": "backend", "context": {"development": True, "app": "empty_viewer"},
        }
        mounts = MagicMock()
        mounts.__iter__.side_effect = SourceMountsReached
        mocks = (
            patch.object(self.run.DTCommand, "_resolve_parsed", return_value=self.parsed),
            patch.object(self.run.shutil, "which", return_value="/usr/bin/docker"),
            patch.object(self.run, "DTProject", return_value=SimpleNamespace(name="dt-duckietown-viewer", distro="ente")),
            patch.object(self.run, "get_registry_to_use", return_value="docker.io"),
            patch.object(self.run, "DEFAULT_MOUNTS", mounts),
            patch("dt_shell.viewer._trust", return_value=("release", {"issuer": "key"})),
            patch("dt_shell.viewer_runtime.read_handoff", return_value=self.handoff),
            patch("dt_shell.viewer_runtime.ViewerLease"),
        )
        started = [mock.start() for mock in mocks]
        for mock in mocks:
            self.addCleanup(mock.stop)
        self.trust, self.read, self.lease = started[-3:]

    def run_source(self):
        self.run.DTCommand.command(MagicMock(), [], parsed=self.parsed)

    def test_source_requires_a_separate_developer_handoff_before_mounting(self):
        with self.assertRaisesRegex(UserError, "separate staff/superuser developer session"):
            self.run_source()
        self.trust.assert_not_called()
        self.read.assert_not_called()
        self.lease.assert_not_called()

    def test_ordinary_or_wrong_app_handoffs_cannot_authorize_source(self):
        self.parsed.viewer_handoff = "/private/backend.json"
        for development, app in ((False, "empty_viewer"), (True, "image_viewer")):
            self.handoff["context"].update(development=development, app=app)
            with self.assertRaisesRegex(UserError, "not a Viewer developer handoff"):
                self.run_source()
        self.lease.assert_not_called()

    def test_source_default_smoke_and_named_launchers_verify_the_matching_developer_lease(self):
        self.parsed.viewer_handoff = "/private/backend.json"
        for launcher, app in (
            (None, "empty_viewer"), ("default", "empty_viewer"),
            ("ci-smoke-test", "empty_viewer"), ("image_viewer", "image_viewer"),
        ):
            with self.subTest(launcher=launcher):
                self.parsed.launcher = launcher
                self.handoff["context"]["app"] = app
                self.lease.reset_mock()
                with self.assertRaises(SourceMountsReached):
                    self.run_source()
                self.lease.assert_called_once_with(self.handoff, issuer_keys={"issuer": "key"})

    @unittest.skipIf(os.name == "nt", "Creating Windows symlinks requires additional privileges.")
    def test_source_does_not_resolve_away_the_private_file_symlink_check(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            target.write_text("{}", encoding="utf-8")
            target.chmod(0o600)
            link = Path(directory) / "backend.json"
            link.symlink_to(target)
            self.parsed.viewer_handoff = str(link)
            self.read.side_effect = self.read_original
            with self.assertRaisesRegex(UserError, "regular private files"):
                self.run_source()
        self.lease.assert_not_called()


class HostRunnerHandoffTests(unittest.TestCase):
    def test_handoff_uses_a_relative_shared_path_instead_of_a_guest_absolute_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "viewer-session"
            private.mkdir()
            handoff = private / "desktop.json"
            handoff.write_text("{}", encoding="utf-8")
            handoff.chmod(0o600)
            with patch.object(bridge, "_normalize_host_delegated_cwd", return_value="/workspaces/project"), patch.object(
                bridge, "_resolve_host_runner_requests_dir", return_value=(root, 1),
            ), patch.object(bridge, "_delegate_command_via_requests_dir", return_value=0) as delegate:
                self.assertEqual(0, bridge.delegate_command_to_host(
                    ["duckiebot", "image_viewer"], ["testbot"],
                    forwarded_env={"HOST_DTS_VIEWER_HANDOFF": str(handoff)},
                ))
            self.assertEqual(
                "viewer-session/desktop.json",
                delegate.call_args.args[1]["env"]["HOST_DTS_VIEWER_HANDOFF"],
            )

    def test_private_handoff_requires_a_shared_directory_and_cannot_escape_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "shared"
            shared.mkdir()
            outside = root / "outside"
            outside.mkdir()
            handoff = outside / "desktop.json"
            handoff.write_text("{}", encoding="utf-8")
            handoff.chmod(0o600)
            for resolved in (None, (shared, 1)):
                with self.subTest(resolved=resolved), patch.object(
                    bridge, "_normalize_host_delegated_cwd", return_value="/workspaces/project",
                ), patch.object(bridge, "_resolve_host_runner_requests_dir", return_value=resolved), patch.object(
                    bridge, "_delegate_command_via_requests_dir",
                ) as delegate:
                    with self.assertRaisesRegex(bridge.HostRunnerError, "request directory"):
                        bridge.delegate_command_to_host(
                            ["duckiebot", "image_viewer"], ["testbot"],
                            forwarded_env={"HOST_DTS_VIEWER_HANDOFF": str(handoff)},
                        )
                    delegate.assert_not_called()


class ViewerOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.shell = MagicMock()
        self.shell.profile.distro.name = "ente"
        self.record = {
            "reference": "duckietown/dt-duckietown-viewer@sha256:" + "1" * 64,
            "config_sha256": "2" * 64, "runtime_sha256": "3" * 64,
        }
        self.release = {"sha256": "4" * 64, "version": "1.2.3", "entrypoint": "viewer"}
        self.session = MagicMock()
        self.session.error = "test revocation"
        self.docker = MagicMock()
        self.docker.image.inspect.return_value = SimpleNamespace(id="sha256:" + self.record["config_sha256"])
        self.instance = viewer.DuckietownViewerInstance(os_family="linux")
        for name in ("_start_backend", "_start_frontend", "_join_frontend"):
            setattr(self.instance, name, MagicMock())
        self.instance._wait_backend_ready = MagicMock(return_value=True)
        mocks = (
            patch.object(dt_shell, "shell", self.shell, create=True),
            patch.object(authorization, "forwarded_lease", return_value=None),
            patch.object(authorization, "authorize_install"),
            patch.object(authorization, "host_info", return_value={"platform": "linux", "architecture": "x86_64", "device_id": DEVICE}),
            patch.object(authorization, "ensure_installed", return_value="1.2.3"),
            patch.object(authorization, "verify_viewer_release", return_value=self.release),
            patch.object(authorization, "backend_record", return_value=self.record),
            patch.object(authorization, "_route_address", return_value="172.17.0.1"),
            patch.object(authorization, "ViewerSession", return_value=self.session),
            patch.object(viewer, "get_path_to_install", return_value="/signed/viewer"),
            patch.object(viewer, "should_delegate_viewer_frontend", return_value=False),
            patch.object(viewer, "forwarded_frontend_url", return_value=None),
            patch("dt_shell_device.get_device_id", return_value=DEVICE),
            patch("utils.docker_utils.get_client", return_value=self.docker),
            patch("utils.docker_utils.get_endpoint_architecture", return_value="amd64"),
            patch("utils.docker_utils.pull_image"),
        )
        for mock in mocks:
            mock.start()
            self.addCleanup(mock.stop)

    def run_viewer(self, **changes):
        return authorization.run(self.instance, "image_viewer", "testbot", **{
            "fullscreen": False, "menu": False, "on_top": False, "enable_hardware_acceleration": False,
            "browser": False, "local": False, "no_pull": False, "window_args": {}, **changes,
        })

    def test_authorization_denial_precedes_installation_docker_and_robot_connections(self):
        with patch.object(authorization, "authorize_install", side_effect=UserError("plan denied")):
            with self.assertRaisesRegex(UserError, "plan denied"):
                self.run_viewer()
        authorization.ensure_installed.assert_not_called()
        self.docker.image.inspect.assert_not_called()
        self.instance._start_backend.assert_not_called()

    def test_custom_url_without_a_verified_handoff_cannot_skip_the_gate(self):
        with self.assertRaisesRegex(UserError, "paired Viewer handoff"):
            self.run_viewer(window_args={"url": "http://localhost:1234/app/"})
        authorization.authorize_install.assert_not_called()
        self.instance._start_frontend.assert_not_called()

    def test_cached_immutable_no_pull_image_is_checked_and_started_by_config_id(self):
        self.run_viewer(no_pull=True)
        self.assertEqual("sha256:" + self.record["config_sha256"], self.instance._viewer_image)
        self.docker.image.inspect.assert_called_with(self.record["reference"])
        self.instance._start_backend.assert_called_once()
        self.instance._start_frontend.assert_called_once()
        self.session.close.assert_called_once()

    def test_no_pull_cannot_trust_a_mutable_tag_or_wrong_image_configuration(self):
        self.docker.image.inspect.return_value = SimpleNamespace(id="sha256:" + "9" * 64)
        with self.assertRaisesRegex(UserError, "immutable identity"):
            self.run_viewer(no_pull=True)
        self.instance._start_backend.assert_not_called()
        self.instance._start_frontend.assert_not_called()

    def test_browser_needs_no_desktop_and_revocation_closes_its_session(self):
        with patch.object(viewer, "open_browser_url", return_value=True) as open_browser:
            with self.assertRaisesRegex(UserError, "test revocation"):
                self.run_viewer(browser=True)
        authorization.ensure_installed.assert_not_called()
        authorization.verify_viewer_release.assert_not_called()
        self.instance._start_frontend.assert_not_called()
        self.assertIn("/__viewer__/open#", open_browser.call_args.args[0])
        self.session.close.assert_called_once()

    def test_plain_daffy_instance_retains_legacy_launch_path(self):
        with patch.object(viewer, "_protected_viewer", return_value=False), patch.object(
            viewer, "should_delegate_viewer_frontend", return_value=False
        ):
            self.instance.start(
                "image_viewer", "testbot", False, False, False, False,
                window_args={"url": "http://localhost:1234/app/"},
            )
        authorization.authorize_install.assert_not_called()
        self.instance._start_frontend.assert_called_once()

    def test_forwarded_ente_session_cannot_fall_back_to_a_native_daffy_profile(self):
        self.shell.profile.distro.name = "daffy"
        with patch.dict(os.environ, {authorization.FORWARDED_HANDOFF_ENV: "/private/desktop.json"}):
            self.assertTrue(authorization.enabled(self.shell))

    def test_host_delegation_forwards_the_private_handoff_and_restores_the_url(self):
        self.instance._viewer_handoff = Path("/shared/private/desktop.json")
        with patch.dict(os.environ, {
            viewer.HOST_RUNNER_FRONTEND_URL_FORWARD_ENV: "http://previous.example/app/",
        }), patch.object(viewer, "build_host_viewer_command", return_value=(["duckiebot", "image_viewer"], [])), patch.object(
            viewer, "host_delegated_viewer_cwd", return_value="/shared/workspace",
        ), patch.object(viewer, "delegate_command_to_host", return_value=0) as delegate:
            self.assertEqual(0, self.instance._delegate_frontend_to_host(
                "image_viewer", "testbot", False, False, False, True,
                "http://localhost:1234/app/",
            ))
            self.assertEqual(
                {"HOST_DTS_VIEWER_HANDOFF": "/shared/private/desktop.json"},
                delegate.call_args.kwargs["forwarded_env"],
            )
            self.assertEqual("/shared/workspace", delegate.call_args.kwargs["cwd"])
            self.assertEqual(
                "http://previous.example/app/", os.environ[viewer.HOST_RUNNER_FRONTEND_URL_FORWARD_ENV],
            )

    def test_frontend_environment_removes_credentials_and_uses_the_paired_version(self):
        self.instance._viewer_lease = SimpleNamespace(handoff={"context": {"desktop_version": "1.2.3"}})
        with patch.dict(os.environ, {"DTSHELL_TOKEN": "private", "DTV_RELEASE_SIGNING_KEY": "private"}), patch.object(
            viewer, "_protected_viewer", return_value=True
        ), patch.object(viewer, "get_path_to_binary", return_value="/signed/viewer") as binary, patch.object(
            viewer, "get_most_recent_version_installed"
        ) as latest, patch.object(viewer.subprocess, "Popen") as spawn:
            viewer.DuckietownViewerInstance._start_frontend(
                self.instance, False, False, False, False, {"url": "http://localhost:1234/app/"},
            )
        binary.assert_called_once_with("1.2.3", "linux")
        latest.assert_not_called()
        self.assertNotIn("DTSHELL_TOKEN", spawn.call_args.kwargs["env"])
        self.assertNotIn("DTV_RELEASE_SIGNING_KEY", spawn.call_args.kwargs["env"])
        self.assertEqual(os.environ["PATH"], spawn.call_args.kwargs["env"]["PATH"])

    def test_delegated_readiness_uses_the_signed_host_not_the_local_polling_address(self):
        self.instance._backend = SimpleNamespace(name="viewer-test")
        self.instance._host_port = "54321"
        self.instance._viewer_ready = "private-readiness-ticket"
        self.instance._viewer_session = SimpleNamespace(
            session_id="a" * 32, context={"endpoint": "http://192.0.2.10:54321/app/"},
        )
        response = SimpleNamespace(
            status_code=200, reason="OK", json=lambda: {"ready": True, "session_id": "a" * 32},
        )
        with patch.object(viewer.requests, "get", return_value=response) as request:
            self.assertTrue(viewer.DuckietownViewerInstance._wait_backend_ready(self.instance))
        self.assertEqual("192.0.2.10:54321", request.call_args.kwargs["headers"]["Host"])
        self.assertEqual("private-readiness-ticket", request.call_args.kwargs["headers"]["X-Viewer-Ready"])

    def test_cleanup_closes_the_broker_and_private_handoffs_when_container_stop_fails(self):
        self.instance._viewer_session = self.session
        self.instance._viewer_temporary = MagicMock()
        self.instance._backend = MagicMock()
        self.instance._backend.stop.side_effect = UserError("container stop failed")
        with self.assertRaisesRegex(UserError, "container stop failed"):
            self.instance._stop()
        self.session.close.assert_called_once()
        self.instance._viewer_temporary.cleanup.assert_called_once()


class SignedPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="viewer-publication-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        old_cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, old_cwd)
        self.fixture = ViewerFixture(self.root)
        source = self.fixture.release()
        self.folder = self.root / "release/signed"
        self.folder.mkdir(parents=True)
        self.archive = self.folder / "duckietown-viewer-1.2.3-linux.zip"
        with ZipFile(self.archive, "w") as archive:
            for path in source.iterdir():
                archive.write(path, path.name)
        claims = {
            "format": 1, "audience": "duckietown-viewer-backends", "distribution": "ente", "version": "1.2.3",
            "images": {"amd64": {
                "reference": "duckietown/dt-duckietown-viewer@sha256:" + "a" * 64,
                "config_sha256": "b" * 64, "runtime_sha256": "c" * 64,
            }},
        }
        (self.folder / "backends.json").write_bytes(self.fixture.sign(claims))
        self.objects = {}
        self.corrupt = False
        self.uploaded = []
        storage = MagicMock()

        def upload(content, path):
            self.uploaded.append(path)
            self.objects[path] = b"corrupt" if self.corrupt else content
            return SimpleNamespace(join=lambda: None)

        def download(path):
            if path not in self.objects:
                raise FileNotFoundError(path)
            return SimpleNamespace(data=self.objects[path], join=lambda: None)

        def head(path):
            if path not in self.objects:
                raise FileNotFoundError(path)

        storage.upload.side_effect = upload
        storage.download.side_effect = download
        storage.head.side_effect = head
        self.client = MagicMock()
        self.client.storage.return_value = storage
        self.parsed = SimpleNamespace(token=None, os_family=["linux"], all_archs=False, force=False)
        for mock in (
            patch.object(publisher, "_trust", return_value=(self.fixture.release_public, self.fixture.issuers)),
            patch.object(publisher, "authorize_install"),
            patch.object(publisher, "create_data_client", return_value=self.client),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def test_first_release_accepts_ci_zips_and_updates_only_ente_pointers_last(self):
        publisher.publish(MagicMock(), self.parsed)
        publisher.authorize_install.assert_called_once_with(unittest.mock.ANY, development=True)
        self.assertEqual(authorization.CHANNEL + "/latest-linux", self.uploaded[-1])
        self.assertTrue(all("/ente/" in path for path in self.uploaded))
        self.assertEqual(b"1.2.3", self.objects[self.uploaded[-1]])

    def test_corrupt_upload_never_updates_backend_or_desktop_pointers(self):
        self.corrupt = True
        with self.assertRaisesRegex(UserError, "Latest pointers were not updated"):
            publisher.publish(MagicMock(), self.parsed)
        self.assertFalse(any("/latest-" in path or path.endswith("/backends.json") for path in self.uploaded))

    def test_existing_or_newer_release_requires_explicit_force(self):
        latest = authorization.CHANNEL + "/latest-linux"
        self.objects[latest] = b"2.0.0"
        with self.assertRaisesRegex(UserError, "older than"):
            publisher.publish(MagicMock(), self.parsed)
        self.assertEqual([], self.uploaded)
        self.parsed.force = True
        publisher.publish(MagicMock(), self.parsed)
        self.assertEqual(b"1.2.3", self.objects[latest])


if __name__ == "__main__":
    unittest.main()
