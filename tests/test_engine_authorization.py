import io
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from dt_shell import UserError
from matrix.engine.run import command as run
from matrix.engine.run.configuration import DTCommandConfiguration as Configuration
from utils import engine_authorization as authorization
from dt_shell_tests.test_engine import EngineFixture


class EngineCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="engine-command-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixture = EngineFixture(self.root)
        self.record = {
            "reference": "duckietown/dt-duckiematrix@sha256:" + "b" * 64,
            "config_sha256": "c" * 64, "runtime_sha256": "d" * 64,
        }
        self.shell = SimpleNamespace(profile=SimpleNamespace(
            distro=SimpleNamespace(name="ente"),
            secrets=SimpleNamespace(dt_token="test-publisher-identity"),
            database=lambda name: SimpleNamespace(yaml=str(self.root / f"{name}.yaml")),
        ))
        self.docker = MagicMock()
        self.docker.containers.list.return_value = []
        self.docker.images.get.return_value.id = "sha256:" + self.record["config_sha256"]
        self.container = self.docker.containers.create.return_value
        self.container.status = "running"
        self.container.wait.return_value = {"StatusCode": 0}
        for mock in (
            patch.object(run.DTCommand, "parser", Configuration.parser()),
            patch.object(run, "get_client_OLD", return_value=self.docker),
            patch.object(run, "get_endpoint_architecture", return_value="amd64"),
            patch.object(run, "image_record", return_value=self.record),
            patch.object(run.platform, "system", return_value="Linux"),
            patch.dict(run.os.environ, {"DOCKER_REGISTRY": run.DEFAULT_REGISTRY}),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def configured(self, args=None):
        parsed = Configuration.parser().parse_args(args or ["--sandbox", "--no-pull"])
        engine = run.MatrixEngine()
        self.assertTrue(engine.configure(self.shell, parsed))
        return engine

    def test_normal_images_are_immutable_even_with_no_pull(self):
        engine = self.configured()
        self.assertEqual(self.record["reference"], engine.config["image"])
        self.assertEqual(authorization.CONTAINER_HANDOFF, engine.config["environment"]["DT_MATRIX_ENGINE_HANDOFF"])
        self.assertNotIn("identity", str(engine.config))

    def test_authorization_and_copy_happen_before_container_start_without_host_bind_mounts(self):
        engine = self.configured()
        order = []
        self.docker.containers.create.side_effect = lambda **kwargs: order.append("create") or self.container
        self.container.start.side_effect = lambda: order.append("start")
        launch = MagicMock()
        launch.copy_handoff.side_effect = lambda container: order.append("handoff")
        with patch.object(run, "EngineLaunch", return_value=launch) as authorize:
            self.assertTrue(engine.start())
        self.assertEqual(["create", "handoff", "start"], order)
        authorize.assert_called_once_with(self.shell, record=self.record, development=False, renew=False)
        engine.stop()
        launch.close.assert_called_once()

    def test_changed_image_is_rejected_before_container_creation(self):
        engine = self.configured()
        self.docker.images.get.return_value.id = "sha256:" + "f" * 64
        with patch.object(run, "EngineLaunch") as authorize:
            with self.assertRaisesRegex(UserError, "immutable identity"):
                engine.start()
        self.docker.containers.create.assert_not_called()
        authorize.return_value.close.assert_called_once()

    def test_copy_failure_never_starts_a_container_and_closes_session(self):
        engine = self.configured()
        with patch.object(run, "EngineLaunch") as authorize:
            authorize.return_value.copy_handoff.side_effect = UserError("handoff rejected")
            with self.assertRaisesRegex(UserError, "handoff rejected"):
                engine.start()
        self.container.start.assert_not_called()
        self.container.remove.assert_called_once()
        authorize.return_value.close.assert_called_once()

    def test_custom_images_select_separate_engine_developer_authorization(self):
        engine = self.configured(["--sandbox", "--no-pull", "--engine-image", "example.test/custom:dev"])
        with patch.object(run, "EngineLaunch") as authorize:
            engine.start()
        authorize.assert_called_once_with(self.shell, record=None, development=True, renew=False)
        self.docker.images.get.assert_not_called()
        engine.stop()

    def test_nonzero_exit_is_reported_and_resources_are_closed(self):
        engine = self.configured()
        with patch.object(run, "EngineLaunch") as authorize:
            engine.start()
        self.container.wait.return_value = {"StatusCode": 1}
        with self.assertRaisesRegex(UserError, "status 1"):
            engine.join()
        authorize.return_value.close.assert_called_once()

    def test_prepare_session_needs_no_map_or_docker_container(self):
        with patch.object(run, "prepare_session") as prepare:
            run.DTCommand.command(self.shell, ["--prepare-session", str(self.root / "engine.json")])
        prepare.assert_called_once_with(self.shell, self.root / "engine.json", renew=False)
        self.docker.containers.create.assert_not_called()

    def test_prepare_session_can_force_fresh_developer_authorization(self):
        with patch.object(run, "prepare_session") as prepare:
            run.DTCommand.command(self.shell, [
                "--prepare-session", str(self.root / "engine.json"), "--renew-authorization",
            ])
        prepare.assert_called_once_with(self.shell, self.root / "engine.json", renew=True)

    def test_hub_denial_prevents_engine_image_download(self):
        engine = self.configured()
        with patch.object(run, "EngineLaunch", side_effect=UserError("Engine denied")), patch.object(
            run, "pull_image_OLD",
        ) as pull:
            with self.assertRaisesRegex(UserError, "Engine denied"):
                engine.pull()
        pull.assert_not_called()

    def test_failed_preparation_does_not_delete_a_file_it_never_created(self):
        destination = self.root / "private.json"
        session = MagicMock()

        def fail_write(*args, **kwargs):
            destination.write_text("created by someone else")
            raise UserError("exclusive creation rejected")

        session.write_handoff.side_effect = fail_write
        with patch.object(authorization, "EngineSession", return_value=session), patch.object(
            authorization, "new_context", return_value={},
        ), patch.object(authorization, "_route_address", return_value="127.0.0.1"):
            with self.assertRaisesRegex(UserError, "exclusive creation rejected"):
                authorization.prepare_session(self.shell, destination)
        self.assertEqual("created by someone else", destination.read_text())
        session.close.assert_called_once()

    def test_preparation_removes_only_its_own_completed_handoff(self):
        for replace in (False, True):
            with self.subTest(replace=replace):
                destination = self.root / f"private-{replace}.json"
                session = MagicMock()

                def write(*args, **kwargs):
                    destination.write_text("private fixture")
                    return destination.stat()

                def finish(*args):
                    if replace:
                        other = self.root / "replacement.json"
                        other.write_text("replacement")
                        os.replace(other, destination)
                    return True

                session.write_handoff.side_effect = write
                session.stop_event.wait.side_effect = finish
                with patch.object(authorization, "EngineSession", return_value=session), patch.object(
                    authorization, "new_context", return_value={},
                ), patch.object(authorization, "_route_address", return_value="127.0.0.1"):
                    authorization.prepare_session(self.shell, destination)
                if replace:
                    self.assertEqual("replacement", destination.read_text())
                else:
                    self.assertFalse(destination.exists())
                session.close.assert_called_once()

    def test_handoff_is_a_private_file_copied_over_docker_api_not_a_guest_absolute_mount(self):
        session = MagicMock()
        session.handoff.return_value = {"private": "session-fixture"}
        with patch.object(authorization, "EngineSession", return_value=session), patch.object(
            authorization, "new_context", return_value={},
        ), patch.object(authorization, "_route_address", return_value="192.0.2.2"):
            launch = authorization.EngineLaunch(self.shell, record=self.record)
            launch.copy_handoff(self.container)
        destination, content = self.container.put_archive.call_args.args
        self.assertEqual("/run", destination)
        with tarfile.open(fileobj=io.BytesIO(content)) as archive:
            entry = archive.getmember("duckiematrix-engine/handoff.json")
            self.assertEqual(0o600, entry.mode)
            self.assertEqual(b'{"private":"session-fixture"}', archive.extractfile(entry).read())
        launch.close()

    def test_signed_catalog_is_verified_before_cache_and_offline_reuse(self):
        claims = {
            "format": 1, "audience": "duckiematrix-engine-images", "distribution": "ente",
            "version": "1.0.0", "images": {"amd64": self.record},
        }
        raw = self.fixture.signed(claims)
        with patch.object(authorization, "_trust", return_value=(self.fixture.release_public, self.fixture.issuers)), patch.object(
            authorization, "_download", return_value=raw,
        ) as download, patch.object(authorization, "create_data_client"):
            self.assertEqual(self.record, authorization.image_record(self.shell, "amd64", update=True))
            self.assertEqual(self.record, authorization.image_record(self.shell, "amd64"))
            self.assertEqual(1, download.call_count)
            with self.assertRaisesRegex(UserError, "architecture"):
                authorization.image_record(self.shell, "unsupported")
            (self.root / "engine-images.json").write_bytes(raw[:-1] + b"x")
            with self.assertRaises(UserError):
                authorization.image_record(self.shell, "amd64")

    def test_workspace_handoff_uses_the_longest_matching_docker_host_mount(self):
        docker = MagicMock()
        docker.containers.get.return_value.attrs = {"Mounts": [
            {"Destination": "/workspace", "Source": "/host/workspaces"},
            {"Destination": "/workspace/project", "Source": "/host/engine"},
        ]}
        with patch.object(authorization.Path, "exists", return_value=True), patch.object(
            authorization, "get_client_OLD", return_value=docker,
        ):
            self.assertEqual(
                "/host/engine/private/engine.json",
                authorization.development_handoff_source(Path("/workspace/project/private/engine.json")),
            )
            with self.assertRaisesRegex(UserError, "bind-mounted"):
                authorization.development_handoff_source(Path("/tmp/engine.json"))

    def test_source_handoff_requires_engine_developer_permission_and_fresh_proof(self):
        handoff = {"consumer": "engine", "context": {"development": False}}
        with patch.object(authorization, "_trust", return_value=("release", {})), patch.object(
            authorization, "read_handoff", return_value=handoff,
        ), patch.object(authorization, "EngineLease") as lease:
            with self.assertRaisesRegex(UserError, "developer"):
                authorization.validate_development_handoff(self.root / "engine.json")
            lease.assert_not_called()
            handoff["context"]["development"] = True
            authorization.validate_development_handoff(self.root / "engine.json")
            lease.assert_called_once_with(handoff, issuer_keys={})

    def test_publisher_verifies_before_uploads_and_reads_back_before_advancing_catalog(self):
        claims = {
            "format": 1, "audience": "duckiematrix-engine-images", "distribution": "ente",
            "version": "1.0.0", "images": {"amd64": self.record},
        }
        path = self.root / "engines.json"
        raw = self.fixture.signed(claims)
        path.write_bytes(raw)
        parsed = SimpleNamespace(file=str(path), token=None, force=False)
        client = MagicMock()
        client.storage.return_value.head.side_effect = FileNotFoundError
        with patch.object(authorization, "_trust", return_value=(self.fixture.release_public, self.fixture.issuers)), patch.object(
            authorization, "EngineSession",
        ), patch.object(authorization, "create_data_client", return_value=client), patch.object(
            authorization, "_download", side_effect=FileNotFoundError,
        ), patch("utils.viewer_release._upload_verified") as upload:
            authorization.publish(self.shell, parsed)
            self.assertEqual(
                [f"{authorization.CHANNEL}/engines-1.0.0.json", f"{authorization.CHANNEL}/engines.json"],
                [call.args[2] for call in upload.call_args_list],
            )
            path.write_bytes(b"not a signed catalog")
            upload.reset_mock()
            with self.assertRaises(UserError):
                authorization.publish(self.shell, parsed)
            upload.assert_not_called()

    def test_catalog_readback_failure_preserves_the_latest_pointer(self):
        claims = {
            "format": 1, "audience": "duckiematrix-engine-images", "distribution": "ente",
            "version": "1.0.0", "images": {"amd64": self.record},
        }
        path = self.root / "engines.json"
        path.write_bytes(self.fixture.signed(claims))
        parsed = SimpleNamespace(file=str(path), token=None, force=False)
        client = MagicMock()
        client.storage.return_value.head.side_effect = FileNotFoundError
        with patch.object(authorization, "_trust", return_value=(self.fixture.release_public, self.fixture.issuers)), patch.object(
            authorization, "EngineSession",
        ), patch.object(authorization, "create_data_client", return_value=client), patch.object(
            authorization, "_download", side_effect=FileNotFoundError,
        ), patch("utils.viewer_release._upload_verified", side_effect=UserError("readback mismatch")) as upload:
            with self.assertRaisesRegex(UserError, "readback mismatch"):
                authorization.publish(self.shell, parsed)
        self.assertEqual(1, upload.call_count)
