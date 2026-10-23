"""Signed Duckietown Viewer delivery and launch orchestration for Ente; Daffy stays on its legacy path."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import socket
import tempfile
from types import SimpleNamespace

import dt_shell
import dt_shell_device
from dockertown.exceptions import NoSuchImage
from dt_shell import UserError, dtslogger
from dt_shell.viewer import (
    FORWARDED_HANDOFF_ENV, ViewerSession, _trust, authorize_install,
    forwarded_lease, host_info, new_context, verify_viewer_release,
)
from dt_shell.viewer_runtime import (
    ViewerAuthorizationError, install_archive, verify_backend_catalog,
)
from utils.data_endpoint_utils import create_data_client
from utils.duckietown_utils import get_distro
from utils.host_runner import (
    _resolve_host_runner_requests_dir, delegate_command_to_host, host_runner_delegated_cwd,
)


CHANNEL = "assets/duckietown-viewer/ente"


def enabled(shell=None) -> bool:
    return bool(os.environ.get(FORWARDED_HANDOFF_ENV)) or get_distro(
        shell or dt_shell.shell
    ).name in ("ente", "ente-staging")


def _download(client, remote: str, limit: int) -> bytes:
    transfer = client.storage("public").download(remote)
    transfer.join()
    if len(transfer.data) > limit:
        raise UserError("The signed Viewer metadata exceeds its size limit.")
    return transfer.data


def latest_version(os_family: str, client) -> str:
    try:
        version = _download(client, f"{CHANNEL}/latest-{os_family}", 128).decode("ascii").strip()
    except FileNotFoundError as error:
        raise UserError(
            "No signed Duckietown Viewer has been published for this platform. "
            "The coordinated Viewer release must be published before using this DTS version."
        ) from error
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        raise UserError("The signed Viewer channel returned an invalid version pointer.")
    return version


def ensure_installed(os_family: str, *, version=None, update=True, force=False, app="empty_viewer"):
    from utils import duckietown_viewer_utils as viewer

    shell = dt_shell.shell
    authorize_install(shell, app)
    forwarded = forwarded_lease(app)
    if forwarded is not None:
        version = forwarded.handoff["context"]["desktop_version"]
    installed = viewer.get_most_recent_version_installed(os_family)
    if installed and not force and not update and version in (None, installed):
        return verify_viewer_release(Path(viewer.get_path_to_install(installed, os_family)))["version"]
    client = create_data_client(shell)
    if update:
        _backend_catalog(shell, update=True)
    version = version or latest_version(os_family, client)
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        raise UserError("Invalid Viewer release version.")
    destination = Path(viewer.APP_RELEASES_DIR) / "ente" / f"v{version}-{os_family}"
    if destination.exists() and not force:
        return verify_viewer_release(destination)["version"]
    release_key, issuers = _trust()
    with tempfile.TemporaryDirectory(prefix="dts-viewer-download-") as temporary:
        archive = Path(temporary) / "viewer.zip"
        shell.include.data.get.command(
            shell, [], parsed=SimpleNamespace(
                object=[f"{CHANNEL}/releases/duckietown-viewer-{version}-{os_family}.zip"],
                file=[str(archive)], space="public",
            ),
        )
        try:
            install_archive(
                archive, destination, release_key=release_key, issuer_keys=issuers,
                version=version, platform=os_family,
            )
        except ViewerAuthorizationError as error:
            raise UserError(str(error)) from error
    dtslogger.info(f"Installed signed Duckietown Viewer v{version}.")
    return version


def _backend_catalog(shell, *, update=False):
    release_key, _ = _trust()
    cache = Path(shell.profile.database("viewer").yaml).parent / "viewer-backends.json"
    if cache.exists() and not update:
        raw = cache.read_bytes()
    else:
        try:
            raw = _download(create_data_client(shell), f"{CHANNEL}/backends.json", 1024 * 1024)
        except FileNotFoundError as error:
            raise UserError("The signed Duckietown Viewer backend catalog has not been published.") from error
        from dt_shell.renderer import _private_write
        try:
            verify_backend_catalog(raw, release_key=release_key)
        except ViewerAuthorizationError as error:
            raise UserError(str(error)) from error
        _private_write(cache, raw)
    try:
        catalog = verify_backend_catalog(raw, release_key=release_key)
    except ViewerAuthorizationError as error:
        raise UserError(str(error)) from error
    return catalog


def backend_record(shell, architecture: str, *, update=False):
    catalog = _backend_catalog(shell, update=update)
    if architecture not in catalog["images"]:
        raise UserError(f"The signed Viewer backend is not available for Docker architecture '{architecture}'.")
    return catalog["images"][architecture]


def verify_image(docker, reference: str, record: dict) -> None:
    image = docker.image.inspect(reference)
    if image.id != "sha256:" + record["config_sha256"]:
        raise UserError("The Viewer image does not match its approved immutable identity. Pull the signed release.")


def _route_address() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        try:
            connection.connect(("192.0.2.1", 9))
        except OSError as error:
            dtslogger.warning(f"No routed broker address is available ({error}); using Docker's host-gateway alias.")
            return "host.docker.internal"
        return connection.getsockname()[0]


def delegated_host_info():
    output = io.StringIO()
    with redirect_stdout(output):
        code = delegate_command_to_host(
            ("viewer", "host_info"), [], cwd=host_runner_delegated_cwd(),
        )
    if code != 0:
        raise UserError("Could not obtain native Viewer host identity. Update the host DTS and host runner.")
    lines = [line.partition("=")[2] for line in output.getvalue().splitlines() if line.startswith("DTS_VIEWER_HOST_INFO=")]
    if len(lines) != 1:
        raise UserError("The delegated native DTS did not return unambiguous Viewer host information.")
    try:
        info = json.loads(lines[0])
    except ValueError as error:
        raise UserError("The delegated Viewer host returned invalid identity information.") from error
    release, issuers = _trust()
    if (
        not isinstance(info, dict) or set(info) != {"format", "device_id", "platform", "architecture", "trust"}
        or type(info["format"]) is not int or info["format"] != 1
        or info["platform"] not in ("linux", "macos", "windows")
        or info["architecture"] not in ("x86_64", "amd64", "aarch64", "arm64")
        or not isinstance(info["device_id"], str) or re.fullmatch("[0-9a-f]{64}", info["device_id"]) is None
        or info["trust"] != {"release": release, "issuers": issuers}
    ):
        raise UserError("The delegated native DTS has incompatible Viewer trust or host identity.")
    return info


def _temporary_handoffs(delegated: bool):
    if delegated:
        shared = _resolve_host_runner_requests_dir()
        if shared is None:
            raise UserError("Protected Viewer delegation requires the private shared host-runner request directory.")
        return tempfile.TemporaryDirectory(prefix="viewer-", dir=shared[0])
    return tempfile.TemporaryDirectory(prefix="dts-viewer-session-")


def run(instance, app, robot, *, fullscreen, menu, on_top, enable_hardware_acceleration, browser, local, no_pull, window_args):
    from utils import duckietown_viewer_utils as viewer
    from utils.docker_utils import get_client, get_endpoint_architecture, pull_image

    shell = dt_shell.shell
    forwarded = forwarded_lease(app)
    args = dict(window_args or {})
    instance._viewer_lease = forwarded
    try:
        if forwarded is not None:
            context = forwarded.handoff["context"]
            requested = args.get("url") or viewer.forwarded_frontend_url()
            if requested is not None and requested != context["endpoint"]:
                raise UserError("The forwarded URL does not match its signed Viewer session.")
            if browser:
                raise UserError("Delegated desktop handoffs cannot be reused as browser sessions.")
            version = ensure_installed(instance._os_family, version=context["desktop_version"], update=False, app=app)
            release = verify_viewer_release(Path(viewer.get_path_to_install(version, instance._os_family)))
            if release["sha256"] != context["desktop"]:
                raise UserError("The delegated desktop payload does not match its signed Viewer session.")
            instance._viewer_handoff = Path(os.environ[FORWARDED_HANDOFF_ENV])
            args["url"] = context["endpoint"]
        else:
            if "url" in args or viewer.forwarded_frontend_url():
                raise UserError("Custom and forwarded Ente URLs require a valid paired Viewer handoff, not a URL override.")
            authorize_install(shell, app)
            delegated = viewer.should_delegate_viewer_frontend(browser, local)
            info = delegated_host_info() if delegated else host_info()
            target_family = info["platform"] + ("-arm64" if info["architecture"] in ("arm64", "aarch64") else "")
            if not browser and not delegated and instance._os_family != target_family:
                # WSL can target the native Windows desktop without consuming another slot.
                target_family = instance._os_family
                info["device_id"] = dt_shell_device.get_renderer_device_id(target_family.split("-")[0])
            release = None
            if not browser:
                version = ensure_installed(target_family, update=False, app=app)
                release = verify_viewer_release(Path(viewer.get_path_to_install(version, target_family)))
            docker = get_client()
            record = backend_record(shell, get_endpoint_architecture())
            image = record["reference"]
            if no_pull:
                try:
                    verify_image(docker, image, record)
                except NoSuchImage:
                    candidate = instance._local_arch_image(
                        instance._BACKEND_DOCKER_IMAGE.format(registry=viewer.get_registry_to_use(), distro=get_distro(shell).name),
                        docker,
                    )
                    if candidate is None:
                        raise UserError("No cached Viewer image was found. Omit --no-pull to pull the signed image.") from None
                    verify_image(docker, candidate, record)
                # Start by content ID, not the mutable local tag we just checked.
                image = "sha256:" + record["config_sha256"]
            else:
                pull_image(image, docker)
                verify_image(docker, image, record)
            instance._viewer_image = image
            instance._host_port = instance._find_free_host_port()
            endpoint = instance._host_visible_backend_url() if delegated else f"http://localhost:{instance._host_port}/app/"
            context, tickets = new_context(
                app=app, endpoint=endpoint, backend=record["runtime_sha256"],
                backend_image=record["config_sha256"],
                desktop=None if release is None else release["sha256"],
                desktop_version=None if release is None else release["version"],
                desktop_device=info["device_id"],
            )
            instance._viewer_session = ViewerSession(
                shell, app=app, context=context, os_family=host_info()["platform"],
            )
            instance._viewer_temporary = _temporary_handoffs(delegated)
            directory = Path(instance._viewer_temporary.name)
            broker_host = _route_address()
            backend_handoff = directory / "backend.json"
            desktop_handoff = directory / "desktop.json"
            instance._viewer_session.write_handoff(
                backend_handoff, consumer="backend", ticket=tickets["ready"], broker_host=broker_host,
            )
            instance._viewer_session.write_handoff(
                desktop_handoff, consumer="desktop", ticket=tickets["desktop"],
                broker_host=broker_host if delegated else "127.0.0.1",
            )
            instance._viewer_backend_handoff = backend_handoff
            instance._viewer_handoff = desktop_handoff
            instance._viewer_ready = tickets["ready"]
            instance._start_backend(app, robot, no_pull)
            if not instance._wait_backend_ready():
                raise UserError("The authorized Viewer backend did not become ready.")
            if delegated:
                code = instance._delegate_frontend_to_host(
                    app, robot, fullscreen, on_top, enable_hardware_acceleration,
                    no_pull, endpoint,
                )
                if code != 0:
                    raise UserError(f"The authorized host Viewer exited with code {code}.")
                return
            args["url"] = endpoint
            if browser:
                url = endpoint.replace("/app/", "/__viewer__/open#") + tickets["browser"]
                if not viewer.open_browser_url(url):
                    dtslogger.warning("Could not open the browser automatically.")
                dtslogger.info(f"Open this one-use Viewer link: {url}")
                try:
                    while instance._viewer_session.error is None:
                        import time
                        time.sleep(1)
                    raise UserError(instance._viewer_session.error)
                except KeyboardInterrupt:
                    dtslogger.info("Closing the Viewer browser session.")
                return
        instance._start_frontend(fullscreen, menu, on_top, enable_hardware_acceleration, args)
        instance._join_frontend()
    finally:
        instance._stop()
