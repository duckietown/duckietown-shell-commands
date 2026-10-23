"""Publish byte-verified signed Duckietown Viewer payloads for Ente without touching Daffy pointers."""

import hashlib
from pathlib import Path
import re
import tempfile

from dt_shell import UserError, dtslogger
from dt_shell.viewer import _trust, authorize_install, verify_viewer_release
from dt_shell.viewer_runtime import ViewerAuthorizationError, install_archive, verify_backend_catalog
from utils.data_endpoint_utils import create_data_client
from utils.viewer_authorization import CHANNEL, _download


def _upload_verified(client, content: bytes, path: str, *, label="Viewer"):
    transfer = client.storage("public").upload(content, path)
    transfer.join()
    downloaded = _download(client, path, len(content))
    if hashlib.sha256(downloaded).digest() != hashlib.sha256(content).digest():
        raise UserError(f"The uploaded {label} bytes do not match the signed local artifact. Latest pointers were not updated.")


def publish(shell, parsed):
    from utils.duckietown_viewer_utils import resolve_os_family, versiontuple

    authorize_install(shell, development=True)
    client = create_data_client(shell, parsed.token)
    root = Path("release/signed")
    families = parsed.os_family or (
        sorted({
            match.group(1)
            for path in root.glob("duckietown-viewer-*.zip")
            if (match := re.fullmatch(r"duckietown-viewer-\d+\.\d+\.\d+-(.+)\.zip", path.name))
        }) if parsed.all_archs else [resolve_os_family()]
    )
    if not families:
        raise UserError("No signed Viewer payloads were found under release/signed.")
    release_key, issuers = _trust()
    pending = []
    for family in families:
        directory = root / family
        release = verify_viewer_release(directory) if directory.exists() else None
        if release is not None and release["platform"] != family:
            raise UserError("A signed desktop release does not match its platform directory.")
        candidates = (
            [root / f"duckietown-viewer-{release['version']}-{family}.zip"] if release is not None
            else list(root.glob(f"duckietown-viewer-*-{family}.zip"))
        )
        if len(candidates) != 1 or not candidates[0].is_file():
            raise UserError(f"Provide exactly one signed Viewer ZIP for '{family}' under release/signed.")
        archive = candidates[0]
        match = re.fullmatch(r"duckietown-viewer-(\d+\.\d+\.\d+)-" + re.escape(family) + r"\.zip", archive.name)
        if match is None:
            raise UserError("The signed Viewer archive has an invalid release filename.")
        version = match.group(1)
        with tempfile.TemporaryDirectory(prefix="viewer-publish-") as temporary:
            try:
                checked = install_archive(
                    archive, Path(temporary) / f"v{version}-{family}",
                    release_key=release_key, issuer_keys=issuers, version=version, platform=family,
                )
            except ViewerAuthorizationError as error:
                raise UserError(str(error)) from error
        if release is not None and checked["sha256"] != release["sha256"]:
            raise UserError("The archived Viewer payload differs from the signed installed payload.")
        remote = f"{CHANNEL}/releases/{archive.name}"
        try:
            client.storage("public").head(remote)
        except FileNotFoundError:
            exists = False
        else:
            exists = True
        try:
            latest = _download(client, f"{CHANNEL}/latest-{family}", 128).decode("ascii").strip()
        except FileNotFoundError:
            latest = None
        if latest is not None and re.fullmatch(r"\d+\.\d+\.\d+", latest) is None:
            raise UserError("The existing Viewer latest pointer is invalid.")
        if not parsed.force and (exists or (latest is not None and versiontuple(latest) > versiontuple(version))):
            raise UserError("This Viewer version already exists or is older than the latest release. Use --force explicitly.")
        _upload_verified(client, archive.read_bytes(), remote)
        pending.append((family, version))
    catalog = root / "backends.json"
    if not catalog.is_file():
        raise UserError("The signed backend catalog release/signed/backends.json is required before publishing desktop pointers.")
    raw = catalog.read_bytes()
    try:
        claims = verify_backend_catalog(raw, release_key=release_key)
    except ViewerAuthorizationError as error:
        raise UserError(str(error)) from error
    _upload_verified(client, raw, f"{CHANNEL}/backends-{claims['version']}.json")
    _upload_verified(client, raw, f"{CHANNEL}/backends.json")
    for family, version in pending:
        _upload_verified(client, version.encode("ascii"), f"{CHANNEL}/latest-{family}")
    dtslogger.info(
        f"Published {len(pending)} byte-verified signed Duckietown Viewer release(s). "
        "Daffy pointers were unchanged."
    )
