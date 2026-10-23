from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import dt_data_api

from dt_shell import DTCommandAbs, dtslogger, DTShell, renderer
from dt_shell.exceptions import UserError
from dt_shell.renderer import (
    RENDERER_MANIFEST,
    install_renderer_archive,
    verify_renderer_release,
)
from utils.data_endpoint_utils import create_data_client
from utils.duckiematrix_utils import (
    APP_NAME,
    DCSS_SPACE_NAME,
    remote_zip_obj,
    get_latest_version,
    is_version_released,
    mark_as_latest_version,
    get_os_family,
)

from utils.misc_utils import versiontuple


def _build_directory(directory, os_family):
    if directory:
        build = Path(directory).resolve()
    else:
        candidates = [Path("Release"), Path("Release") / os_family]
        found = [
            path
            for path in candidates
            if (path / f"{APP_NAME.capitalize()}.json").is_file()
        ]
        if len(found) > 1:
            raise UserError(
                "Both Release and Release/<os-family> contain renderer builds. "
                "Use --directory to select the build to publish."
            )
        if not found:
            raise UserError(
                "No renderer build metadata was found in Release or Release/<os-family>. "
                "Run this command from the duckiematrix project root after building, or use --directory."
            )
        build = found[0].resolve()
    if not build.is_dir():
        raise UserError(f"Renderer build directory '{build}' does not exist.")
    return build


@contextmanager
def _release_for_publication(build, version, os_family):
    manifest = build / RENDERER_MANIFEST
    if manifest.exists() or manifest.is_symlink():
        yield build, verify_renderer_release(
            build, version=version, os_family=os_family
        )
        return
    tool = Path.cwd() / "tools" / "renderer_release.py"
    if not tool.is_file():
        raise UserError(
            "An unsigned Unity build must be published from the duckiematrix project root "
            "with tools/renderer_release.py present. Already-signed artifacts can be published with --directory."
        )
    key_file = os.environ.get("DTM_RELEASE_SIGNING_KEY_FILE")
    key_pem = os.environ.get("DTM_RELEASE_SIGNING_KEY")
    if bool(key_file) == bool(key_pem):
        raise UserError(
            "To sign this Unity build, configure exactly one publisher-only "
            "DTM_RELEASE_SIGNING_KEY_FILE or DTM_RELEASE_SIGNING_KEY. "
            "Keep the artifact private key outside the project and build directories; Unity does not need it."
        )
    if key_file and (
        Path(key_file).resolve().is_relative_to(build.resolve())
        or Path(key_file).resolve().is_relative_to(Path.cwd().resolve())
    ):
        raise UserError(
            "The renderer signing key must be outside the project and build being published."
        )
    release_key, issuers = renderer._trust()
    environment = os.environ.copy()
    environment["DTM_RELEASE_PUBLIC_KEY"] = release_key
    environment["DTM_RENDERER_PUBLIC_KEYS"] = json.dumps(
        issuers, sort_keys=True, separators=(",", ":")
    )
    preparation_environment = {
        key: value
        for key, value in environment.items()
        if key not in ("DTM_RELEASE_SIGNING_KEY_FILE", "DTM_RELEASE_SIGNING_KEY")
    }
    with tempfile.TemporaryDirectory(prefix="renderer-publication-stage-") as temporary:
        prepared = Path(temporary) / "release"
        dtslogger.info(
            "Preparing and signing the Unity build for publication; the original build will not be modified."
        )
        for arguments, process_environment in (
            (["prepare", str(build), str(prepared)], preparation_environment),
            (
                ["seal", str(prepared), "--version", version, "--platform", os_family],
                environment,
            ),
        ):
            try:
                result = subprocess.run(
                    [sys.executable, str(tool), *arguments],
                    env=process_environment,
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except subprocess.CalledProcessError as error:
                detail = (error.stderr or error.stdout or str(error)).strip()
                raise UserError(
                    f"Renderer preparation/signing failed; nothing was uploaded: {detail}"
                ) from error
            except OSError as error:
                raise UserError(
                    f"Could not run the renderer signing tool; nothing was uploaded: {error}"
                ) from error
            if result.stdout.strip():
                dtslogger.info(result.stdout.strip())
        yield prepared, verify_renderer_release(
            prepared, version=version, os_family=os_family
        )


class DTCommand(DTCommandAbs):

    help = f"Creates a new release of the {APP_NAME} application and pushes it to the DCSS."

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        # ---
        if versiontuple(dt_data_api.__version__) < (1, 0, 1):
            dtslogger.error(
                f"You need to have the library dt-data-api>=1.0.1, "
                f"the version {dt_data_api.__version__} was found instead."
            )
            return

        # make sure we are in the right place
        os_family = parsed.os_family or get_os_family()
        build_dir = _build_directory(parsed.directory, os_family)

        # read app.json
        capitalized_app_name = APP_NAME.capitalize()
        json_fp = build_dir / f"{capitalized_app_name}.json"
        if not os.path.isfile(json_fp):
            raise UserError(
                f"Renderer build metadata '{json_fp}' was not found. Build the player before publishing it."
            )

        # load metadata
        with open(json_fp, "rt") as fin:
            meta = json.loads(fin.read())
        version = parsed.version
        release_version = version if version else meta["version"]
        if os_family.lower() != "webgl":
            os_family = meta["target"]["operating_system_family"].lower()
        release = release_version + "-" + os_family
        # make sure we have a token
        token: str = parsed.token
        if token is None:
            token = shell.profile.secrets.dt_token
        data_client = create_data_client(shell, token)

        if not version:
            # check whether the same version was already released
            if is_version_released(release_version, os_family, client=data_client):
                dtslogger.warn(
                    f"The version v{release} was found "
                    f"already on the DCSS, are you re-releasing this version? "
                    f"(use -f/--force to continue)"
                )
                if not parsed.force:
                    return
                else:
                    dtslogger.warn("Forced!")

            # check whether we are releasing an older version
            latest_version = get_latest_version(os_family, client=data_client)
            latest = latest_version + "-" + os_family
            if versiontuple(latest_version) > versiontuple(release_version):
                dtslogger.warn(
                    f"The version v{latest} was found on the DCSS, are you releasing "
                    f"an older version? (use -f/--force to continue)"
                )
                if not parsed.force:
                    return
                else:
                    dtslogger.warn("Forced!")

        with _release_for_publication(build_dir, release_version, os_family) as (
            published_dir,
            signed_release,
        ):
            dtslogger.info(f"Uploading version v{release}...")
            zip_remote = remote_zip_obj(release_version, os_family)
            shell.include.data.push.command(
                shell,
                [],
                parsed=SimpleNamespace(
                    file=[str(published_dir)],
                    object=[zip_remote],
                    token=token,
                    space=DCSS_SPACE_NAME,
                    exclude="duckiematrix_BackUpThisFolder_ButDontShipItWithYourGame/*,"
                    "Duckiematrix_BackUpThisFolder_ButDontShipItWithYourGame/*,"
                    "duckiematrix_BurstDebugInformation_DoNotShip/*,"
                    "Duckiematrix_BurstDebugInformation_DoNotShip/*",
                    compress=True,
                ),
            )
            with tempfile.TemporaryDirectory(
                prefix="renderer-publication-check-"
            ) as temporary:
                archive = Path(temporary) / "uploaded.zip"
                try:
                    download = data_client.storage(DCSS_SPACE_NAME).download(zip_remote)
                    download.join()
                    archive.write_bytes(download.data)
                except (
                    OSError,
                    dt_data_api.APIError,
                    dt_data_api.TransferError,
                ) as error:
                    raise UserError(
                        f"Could not verify the uploaded renderer; the latest pointer was not changed: {error}"
                    ) from error
                installation = Path(temporary) / f"v{release_version}-{os_family}"
                install_renderer_archive(
                    archive, installation, version=release_version, os_family=os_family
                )
                uploaded = verify_renderer_release(
                    installation, version=release_version, os_family=os_family
                )
                if uploaded["sha256"] != signed_release["sha256"]:
                    raise UserError(
                        "The uploaded renderer differs from the signed local build. The latest pointer was not changed."
                    )
        if not version:
            # mark this as latest (if needed)
            if versiontuple(latest_version) < versiontuple(release_version):
                mark_as_latest_version(
                    token, release_version, os_family, client=data_client
                )

        dtslogger.info(f"Congrats! You just released version v{release}.")

    @staticmethod
    def complete(shell, word, line):
        return []
