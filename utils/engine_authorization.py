"""Approved Engine images and private, live DTS handoffs for Docker and source work."""

import io
import os
from pathlib import Path
import tarfile
import socket

from docker.errors import DockerException

from dt_shell import UserError, dtslogger
from dt_shell.engine import EngineSession, _trust, new_context
from dt_shell.engine_runtime import (
    EngineAuthorizationError, EngineLease, HANDOFF_ENV, read_handoff, verify_image_catalog,
)
from dt_shell.renderer import _canonical, _private_write
from utils.data_endpoint_utils import create_data_client
from utils.docker_utils import get_client_OLD
from utils.viewer_authorization import _download, _route_address


CHANNEL = "assets/duckiematrix/ente"
CONTAINER_HANDOFF = "/run/duckiematrix-engine/handoff.json"


def image_record(shell, architecture: str, *, update=False) -> dict:
    release_key, _ = _trust()
    cache = Path(shell.profile.database("engine").yaml).parent / "engine-images.json"
    if cache.is_symlink():
        raise UserError("The Engine catalog cache must not be a symbolic link.")
    if cache.exists() and not update:
        with cache.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
    else:
        try:
            raw = _download(create_data_client(shell), f"{CHANNEL}/engines.json", 1024 * 1024)
        except FileNotFoundError as error:
            raise UserError(
                "The signed Duckiematrix Engine image catalog has not been published. "
                "Publish the coordinated Engine release before promoting these commands."
            ) from error
        try:
            verify_image_catalog(raw, release_key=release_key)
        except EngineAuthorizationError as error:
            raise UserError(str(error)) from error
        _private_write(cache, raw)
    try:
        catalog = verify_image_catalog(raw, release_key=release_key)
    except EngineAuthorizationError as error:
        raise UserError(str(error)) from error
    if architecture not in catalog["images"]:
        raise UserError(f"No approved Engine image is available for Docker architecture '{architecture}'.")
    return catalog["images"][architecture]


def verify_image(docker, reference: str, record: dict) -> None:
    if docker.images.get(reference).id != "sha256:" + record["config_sha256"]:
        raise UserError("The Engine image does not match its approved immutable identity. Pull the signed release.")


class EngineLaunch:
    def __init__(self, shell, *, record, development=False, renew=False):
        self.session = EngineSession(shell, context=new_context(
            runtime="0" * 64 if record is None else record["runtime_sha256"],
            image="0" * 64 if record is None else record["config_sha256"],
            development=development,
        ), renew=renew)

    def copy_handoff(self, container) -> None:
        content = _canonical(self.session.handoff(broker_host=_route_address()))
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as archive:
            directory = tarfile.TarInfo("duckiematrix-engine")
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o755
            archive.addfile(directory)
            handoff = tarfile.TarInfo("duckiematrix-engine/handoff.json")
            handoff.mode = 0o600
            handoff.uid = os.getuid()
            handoff.gid = os.getgid()
            handoff.size = len(content)
            archive.addfile(handoff, io.BytesIO(content))
        if not container.put_archive("/run", data.getvalue()):
            raise UserError("Docker did not accept the private Engine handoff. The Engine was not started.")

    def close(self):
        self.session.close()


def validate_development_handoff(path: Path) -> None:
    _, issuers = _trust()
    try:
        handoff = read_handoff(path)
        if not handoff["context"]["development"]:
            raise EngineAuthorizationError("Engine source runs require an Engine developer handoff.")
        EngineLease(handoff, issuer_keys=issuers)
    except EngineAuthorizationError as error:
        raise UserError(str(error)) from error


def development_handoff_source(path: Path) -> str:
    if not Path("/.dockerenv").exists():
        return str(path)
    try:
        container = get_client_OLD().containers.get(socket.gethostname())
    except DockerException as error:
        raise UserError(
            "Cannot map the Engine handoff to the Docker host. "
            "Run source development from the host or use a Workspace with an inspectable container."
        ) from error
    candidates = []
    for mount in container.attrs["Mounts"]:
        destination = Path(mount["Destination"])
        if path.is_relative_to(destination):
            candidates.append((len(destination.parts), str(Path(mount["Source"]) / path.relative_to(destination))))
    if not candidates:
        raise UserError(
            "Create the Engine handoff under a bind-mounted Workspace directory, "
            "such as the project checkout, so the Docker host can mount the same private file."
        )
    return max(candidates)[1]


def prepare_session(shell, destination: Path, *, renew=False) -> None:
    destination = destination.expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise UserError("Choose a new private Engine handoff path; existing files are not overwritten.")
    session = EngineSession(
        shell, context=new_context(runtime="0" * 64, image="0" * 64, development=True), renew=renew,
    )
    written = None
    try:
        written = session.write_handoff(destination, broker_host=_route_address())
        dtslogger.info(
            f"Engine developer session ready. Set {HANDOFF_ENV}={destination} for source runs, "
            "or pass this file with 'dts devel run --engine-handoff'. "
            "Keep this DTS command running; press Ctrl+C to end the session."
        )
        while not session.stop_event.wait(1):
            if session.error is not None:
                raise UserError(session.error)
    finally:
        try:
            session.close()
        finally:
            if written is not None:
                try:
                    current = destination.lstat()
                except FileNotFoundError:
                    pass
                else:
                    if (current.st_dev, current.st_ino) == (written.st_dev, written.st_ino):
                        destination.unlink()
                    else:
                        dtslogger.warning("The Engine handoff path was replaced; the replacement file was not removed.")


def publish(shell, parsed):
    from utils.viewer_release import _upload_verified

    session = EngineSession(shell, context=new_context(runtime="0" * 64, image="0" * 64, development=True))
    session.close()
    release_key, _ = _trust()
    path = Path(parsed.file)
    try:
        raw = path.read_bytes()
        claims = verify_image_catalog(raw, release_key=release_key)
    except (OSError, EngineAuthorizationError) as error:
        raise UserError(f"Cannot publish the signed Engine image catalog: {error}") from error
    token = parsed.token if parsed.token is not None else shell.profile.secrets.dt_token
    client = create_data_client(shell, token)
    archive = f"{CHANNEL}/engines-{claims['version']}.json"
    try:
        client.storage("public").head(archive)
    except FileNotFoundError:
        pass
    else:
        if not parsed.force:
            raise UserError("This Engine catalog version already exists. Choose an unused version or use --force explicitly.")
    try:
        current = _download(client, f"{CHANNEL}/engines.json", 1024 * 1024)
    except FileNotFoundError:
        current = None
    if current is not None:
        try:
            previous = verify_image_catalog(current, release_key=release_key)
        except EngineAuthorizationError as error:
            raise UserError(f"The published Engine catalog is invalid: {error}") from error
        if not parsed.force and tuple(map(int, claims["version"].split("."))) < tuple(map(int, previous["version"].split("."))):
            raise UserError("Refusing to move the Engine catalog backwards. Use --force only for an approved rollback.")
    _upload_verified(client, raw, archive, label="Engine")
    _upload_verified(client, raw, f"{CHANNEL}/engines.json", label="Engine")
    dtslogger.info(f"Published byte-verified signed Duckiematrix Engine catalog {claims['version']}.")
