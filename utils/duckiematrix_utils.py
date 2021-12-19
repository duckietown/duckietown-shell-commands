import glob
import os
import re
import sys
from typing import List, Optional

from dt_data_api import DataClient

from utils.duckietown_utils import USER_DATA_DIR
from utils.misc_utils import versiontuple

APP_NAME = "duckiematrix"
DCSS_SPACE_NAME = "public"
DCSS_APP_DIR = f"assets/{APP_NAME}/"
DCSS_APP_RELEASES_DIR = f"assets/{APP_NAME}/releases/"
APP_LOCAL_DIR = os.path.join(USER_DATA_DIR, APP_NAME)
APP_RELEASES_DIR = os.path.join(APP_LOCAL_DIR, "releases")


def get_os_family() -> str:
    if sys.platform.startswith('linux'):
        return "linux"
    elif sys.platform.startswith('win32') or sys.platform.startswith('cygwin'):
        return "windows"
    elif sys.platform.startswith('darwin'):
        return "macosx"


def get_latest_version(os_family: str = None):
    # create storage client
    client = DataClient()
    storage = client.storage(DCSS_SPACE_NAME)
    # get latest version
    os_family = os_family or get_os_family()
    latest_version_obj = os.path.join(DCSS_APP_DIR, f"latest-{os_family}")
    download = storage.download(latest_version_obj)
    download.join()
    return download.data.decode("ascii").strip()


def get_all_installed_releases() -> List[str]:
    app_dir = os.path.join(APP_RELEASES_DIR, "*")
    dirs = glob.glob(app_dir)
    version_regex = r"v([0-9]+)\.([0-9]+)\.([0-9]+)"
    version_pattern = re.compile(version_regex)
    is_release_dir = lambda fp: os.path.isdir(fp) and version_pattern.match(os.path.basename(fp))
    return list(map(lambda p: os.path.basename(p)[1:], filter(is_release_dir, dirs)))


def get_most_recent_version_installed() -> Optional[str]:
    releases = get_all_installed_releases()
    release = None
    for r in releases:
        if release is None or versiontuple(r) > versiontuple(release):
            release = r
    return release


def get_path_to_install(version: str):
    app_dir = os.path.join(APP_RELEASES_DIR, f"v{version}")
    if not os.path.isdir(app_dir):
        app_dir = None
    return app_dir


def get_path_to_binary(version: str):
    app_dir = get_path_to_install(version)
    if app_dir is None:
        return None
    return os.path.join(app_dir, f"{APP_NAME}.x86_64")


def is_version_released(version: str, os_family: str = None) -> bool:
    # create storage client
    client = DataClient()
    storage = client.storage(DCSS_SPACE_NAME)
    # check whether the object exists
    release_obj = remote_zip_obj(version, os_family)
    try:
        storage.head(release_obj)
        return True
    except FileNotFoundError:
        return False


def remote_zip_obj(version: str, os_family: str = None):
    os_family = os_family or get_os_family()
    return os.path.join(DCSS_APP_RELEASES_DIR, f"{APP_NAME}-{version}-{os_family}.zip")


def mark_as_latest_version(token: str, version: str, os_family: str):
    # create storage client
    client = DataClient(token)
    storage = client.storage(DCSS_SPACE_NAME)
    # get latest version
    latest_version_obj = os.path.join(DCSS_APP_DIR, f"latest-{os_family}")
    upload = storage.upload(version.encode("ascii"), latest_version_obj)
    upload.join()

