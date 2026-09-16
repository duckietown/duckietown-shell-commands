import glob
import json
import os
import platform
import re
import sys
from typing import List, Mapping, Optional

from dt_data_api import DataClient

from utils.duckietown_utils import USER_DATA_DIR
from utils.misc_utils import versiontuple

APP_NAME = "duckiematrix"
DCSS_SPACE_NAME = "public"
DCSS_APP_DIR = f"assets/{APP_NAME}/"
DCSS_APP_RELEASES_DIR = f"assets/{APP_NAME}/releases/"
APP_LOCAL_DIR = os.path.join(USER_DATA_DIR, APP_NAME)
APP_RELEASES_DIR = os.path.join(APP_LOCAL_DIR, "releases")
RELEASE_METADATA_FILENAME = ".release.json"


def get_os_family() -> str:
    if os.path.exists("/proc/version"):
        with open("/proc/version", "r") as f:
            if "microsoft" in f.read().lower():
                return "windows"
    if sys.platform.startswith('linux'):
        return "linux"
    elif sys.platform.startswith('win32') or sys.platform.startswith('cygwin'):
        return "windows"
    elif sys.platform.startswith('darwin'):
        return "macos"


def get_latest_version(
    os_family: str = "", webgl: bool = False, client: Optional[DataClient] = None
) -> str:
    # create storage client
    client = client or DataClient()
    storage = client.storage(DCSS_SPACE_NAME)
    # get latest version
    latest_version_obj = os.path.join(DCSS_APP_DIR, f"latest-{'webgl' if webgl else os_family}")
    download = storage.download(latest_version_obj)
    download.join()
    return download.data.decode("ascii").strip()


def get_all_installed_releases(os_family: str = "", webgl: bool = False) -> List[str]:
    app_dir = os.path.join(APP_RELEASES_DIR, f"*-{'webgl' if webgl else os_family}")
    dirs = glob.glob(app_dir)
    version_regex = r"v([0-9]+)\.([0-9]+)\.([0-9]+)"
    version_pattern = re.compile(version_regex)
    is_release_dir = lambda fp: os.path.isdir(fp) and version_pattern.match(os.path.basename(fp))
    return list(map(lambda p: os.path.basename(p)[1:], filter(is_release_dir, dirs)))


def get_most_recent_version_installed(os_family: str = "", webgl: bool = False) -> Optional[str]:
    releases = get_all_installed_releases(os_family, webgl)
    release = None
    for r in releases:
        if release is None or versiontuple(r) > versiontuple(release):
            release = r
    if release is None:
        return None
    split_release = release.split("-")
    return split_release[0]


def get_path_to_install(os_family: str, version: str, webgl: bool = False) -> Optional[str]:
    app_dir = os.path.join(APP_RELEASES_DIR, f"v{version}-{('webgl' if webgl else os_family)}")
    if not os.path.isdir(app_dir):
        app_dir = None
    return app_dir


def get_path_to_app(os_family: str, version: str, webgl: bool = False):
    app_dir = get_path_to_install(os_family, version, webgl)
    if app_dir is None:
        return None
    if webgl:
        return os.path.join(app_dir, APP_NAME)
    elif os_family == "linux":
        app_name = APP_NAME
        ext = "x86_64"
    elif os_family == "macos":
        app_name = APP_NAME
        ext = "app"
    elif os_family == "windows":
        app_name = APP_NAME.capitalize()
        ext = "exe"
    else:
        return None
    return os.path.join(app_dir, f"{app_name}.{ext}")


def _normalize_checksum(checksum: Optional[str]) -> Optional[str]:
    if checksum is None:
        return None
    checksum = checksum.strip()
    checksum = checksum.strip('"')
    return checksum.strip("'") or None


def get_release_checksum(metadata: Mapping[str, str]) -> Optional[str]:
    for key in (
        "ETag",
        "Etag",
        "etag",
        "Content-MD5",
        "Content-Md5",
        "content-md5",
        "x-amz-checksum-sha256",
        "x-amz-meta-sha256",
    ):
        checksum = metadata.get(key)
        if checksum:
            return _normalize_checksum(checksum)
    return None


def get_remote_release_checksum(
    version: str, os_family: str = "", webgl: bool = False, client: Optional[DataClient] = None
) -> Optional[str]:
    client = client or DataClient()
    storage = client.storage(DCSS_SPACE_NAME)
    release_obj = remote_zip_obj(version, os_family, webgl)
    metadata = storage.head(release_obj)
    return get_release_checksum(metadata)


def get_installed_release_checksum(os_family: str, version: str, webgl: bool = False) -> Optional[str]:
    app_dir = get_path_to_install(os_family, version, webgl)
    if app_dir is None:
        return None
    metadata_fp = os.path.join(app_dir, RELEASE_METADATA_FILENAME)
    if not os.path.isfile(metadata_fp):
        return None
    try:
        with open(metadata_fp, "rt", encoding="utf-8") as fin:
            metadata = json.load(fin)
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(metadata, dict):
        return None
    checksum = metadata.get("checksum")
    return _normalize_checksum(checksum)


def write_installed_release_checksum(app_dir: str, checksum: Optional[str]) -> None:
    metadata = {
        "checksum": _normalize_checksum(checksum)
    }
    metadata_fp = os.path.join(app_dir, RELEASE_METADATA_FILENAME)
    with open(metadata_fp, "wt", encoding="utf-8") as fout:
        json.dump(metadata, fout, indent=4, sort_keys=True)
        fout.write("\n")


def is_version_released(
    version: str, os_family: str = "", client: Optional[DataClient] = None
) -> bool:
    # create storage client
    client = client or DataClient()
    storage = client.storage(DCSS_SPACE_NAME)
    # check whether the object exists
    release_obj = remote_zip_obj(version, os_family)
    try:
        storage.head(release_obj)
        return True
    except FileNotFoundError:
        return False


def remote_zip_obj(version: str, os_family: str = "", webgl: bool = False) -> str:
    return os.path.join(DCSS_APP_RELEASES_DIR, f"{APP_NAME}-{version}-{('webgl' if webgl else os_family)}.zip")


def mark_as_latest_version(
    token: str, version: str, os_family: str, client: Optional[DataClient] = None
):
    # create storage client
    client = client or DataClient(token)
    storage = client.storage(DCSS_SPACE_NAME)
    # get latest version
    latest_version_obj = os.path.join(DCSS_APP_DIR, f"latest-{os_family}")
    upload = storage.upload(version.encode("ascii"), latest_version_obj)
    upload.join()

