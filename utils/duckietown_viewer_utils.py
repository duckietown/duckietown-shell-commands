import glob
import json
import os
import re
import subprocess
import sys
import time
from threading import Thread
from types import SimpleNamespace
from typing import List, Optional, Union, Dict

import dockertown
import requests
from dockertown import Container
from dockertown import DockerClient
from dockertown.exceptions import NoSuchContainer
from dt_data_api import DataClient

import dt_shell
from dt_shell import dtslogger, DTShell, UserError
from utils.docker_utils import get_client, get_registry_to_use
from utils.duckietown_utils import USER_DATA_DIR, get_distro
from utils.misc_utils import versiontuple, random_string
from utils.networking_utils import get_duckiebot_ip

APP_NAME = "duckietown-viewer"
DCSS_SPACE_NAME = "public"
DCSS_APP_DIR = f"assets/{APP_NAME}/"
DCSS_APP_RELEASES_DIR = f"assets/{APP_NAME}/releases/"
APP_LOCAL_DIR = os.path.join(USER_DATA_DIR, APP_NAME)
APP_RELEASES_DIR = os.path.join(APP_LOCAL_DIR, "releases")

AVAHI_SOCKET = "/var/run/avahi-daemon/socket"

WindowArgs = Dict[str, Union[int, float, str]]


def get_os_family() -> str:
    if sys.platform.startswith('linux'):
        return "linux"
    elif sys.platform.startswith('win32') or sys.platform.startswith('cygwin'):
        return "windows"
    elif sys.platform.startswith('darwin'):
        return "macosx"


def get_latest_version(os_family: str = None) -> Optional[str]:
    # create storage client
    client = DataClient()
    storage = client.storage(DCSS_SPACE_NAME)
    # get latest version
    os_family = os_family or get_os_family()
    latest_version_obj = os.path.join(DCSS_APP_DIR, f"latest-{os_family}")
    try:
        download = storage.download(latest_version_obj)
        download.join()
    except FileNotFoundError:
        return None
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
    system: str = get_os_family()
    ext: str
    if system == "linux":
        ext = "AppImage"
    elif system == "macosx":
        ext = "app"
    elif system == "windows":
        ext = "exe"
    else:
        raise ValueError(f"Unknown platform '{system}'")
    # ---
    return os.path.join(app_dir, f"{APP_NAME}-v{version}.{ext}")


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


def ensure_duckietown_viewer_installed(log_prefix: str = None):
    shell: DTShell = dt_shell.shell
    log_prefix = log_prefix or " > "

    # make sure the app is not already installed
    installed_version: Optional[str] = get_most_recent_version_installed()
    if installed_version is not None:
        return

    # get latest version available on the DCSS
    latest: Optional[str] = get_latest_version()
    if latest is None:
        dtslogger.error(f"{log_prefix}No version available for installation.")
        return

    # download new version
    app_dir = os.path.join(APP_RELEASES_DIR, f"v{latest}")

    dtslogger.info(f"{log_prefix}Downloading version v{latest}...")
    os.makedirs(app_dir, exist_ok=True)
    zip_remote = remote_zip_obj(latest)
    zip_local = os.path.join(app_dir, f"v{latest}.zip")
    shell.include.data.get.command(
        shell,
        [],
        parsed=SimpleNamespace(
            object=[zip_remote],
            file=[zip_local],
            space=DCSS_SPACE_NAME,
        )
    )
    dtslogger.info(f"{log_prefix}Download completed.")

    # install
    dtslogger.info(f"{log_prefix}Installing...")
    subprocess.check_call(["unzip", f"v{latest}.zip"], cwd=app_dir)

    # clean up
    dtslogger.info(f"{log_prefix}Removing temporary files...")
    os.remove(zip_local)
    # ---
    dtslogger.info(f"{log_prefix}Installation completed successfully!")


def launch_viewer(robot: str, app: str, *, verbose: bool = False, window_args: Optional[WindowArgs] = None) \
        -> 'DuckietownViewerInstance':
    viewer = DuckietownViewerInstance(verbose=verbose)
    viewer.start(robot, app, window_args=window_args)
    return viewer


class DuckietownViewerInstance:
    _BACKEND_DOCKER_IMAGE = "{registry}/duckietown/dt-duckietown-viewer:{distro}"
    _BACKEND_REMOTE_PORT = 8000
    _KNOWN_APPS = [
        "joystick",
        "image_viewer",
        "intrinsics_calibrator",
        "extrinsics_calibrator",
    ]

    def __init__(self, verbose: bool = False):
        self._verbose: bool = verbose
        # internal state
        self._backend: Optional[Container] = None
        self._frontend: Optional[subprocess.Popen] = None
        self._backend_ip: Optional[str] = None

    def start(self, robot: str, app: str, window_args: Optional[WindowArgs] = None):
        self._start_backend(robot, app)
        self._wait_backend_ready()
        self._start_frontend(window_args or {})
        self._join_frontend()
        self._stop()

    def _start_backend(self, robot: str, app: str):
        import dt_shell
        # make sure the app is known
        if app not in self._KNOWN_APPS:
            raise ValueError(f"Unknown app '{app}'. Known apps are: {', '.join(self._KNOWN_APPS)}")
        # resolve IP address of the robot
        try:
            ip: str = get_duckiebot_ip(robot)
        except Exception:
            raise UserError(f"Could not resolve IP address for robot '{robot}'. Make sure the robot is online.")
        dtslogger.debug(f"Resolved IP address of '{robot}' to '{ip}'")
        # create docker client
        docker: DockerClient = get_client()
        # compile image name
        image = self._BACKEND_DOCKER_IMAGE.format(
            registry=get_registry_to_use(),
            distro=get_distro(dt_shell.shell).name
        )
        dtslogger.debug(f"Using image '{image}'")
        # create container
        container_name: str = f"duckietown-viewer-backend-{random_string()}"
        container_cfg: dict = {
            "name": container_name,
            "detach": True,
            "publish": [(0, self._BACKEND_REMOTE_PORT)],
            "volumes": [],
            "remove": True,
            "envs": {
                "DT_LAUNCHER": app,
                "VEHICLE_IP": ip,
                "VEHICLE_NAME": robot,
            }
        }
        # mount avahi socket (if it is available)
        if os.path.exists(AVAHI_SOCKET):
            container_cfg["volumes"].append((AVAHI_SOCKET, AVAHI_SOCKET))
        # run the container
        dtslogger.debug(f"Starting container with configuration:\n{json.dumps(container_cfg, indent=4)}")
        container: Container = docker.run(image, **container_cfg)
        # stop container when the shell is closed

        def _stop_container(_):
            try:
                dtslogger.debug(f"Stopping container '{container_name}'...")
                container.stop()
                dtslogger.debug(f"Container '{container_name}' stopped")
            except NoSuchContainer:
                dtslogger.warning(f"Could not stop container '{container_name}'")

        dt_shell.shell.on_shutdown(_stop_container)

        # in verbose mode we attach a log reader to the container
        if self._verbose:
            def _consume_container_logs():
                # consume logs
                print(dockertown.__version__)
                for (stream, line) in container.logs(follow=True, stream=True):
                    line = line.decode("utf-8")
                    print(line, end="")

            # start log reader
            log_reader = Thread(target=_consume_container_logs, daemon=True)
            log_reader.start()

        # save container
        self._backend = container

    def _wait_backend_ready(self) -> bool:
        container: Container = self._backend
        container_name: str = container.name
        dtslogger.debug(f"Waiting for container '{container_name}' to be ready...")

        # retrieve container's IP address and port
        container.reload()
        container_ip: str = container.network_settings.ip_address

        dtslogger.debug(f"Container '{container_name}' is reachable at the IP address '{container_ip}'")
        # wait for the backend to be ready
        stime: float = time.time()
        timeout: float = 10
        while True:
            url: str = f"http://{container_ip}:{self._BACKEND_REMOTE_PORT}/"
            try:
                response = requests.get(url)
                dtslogger.debug(f"GET: {url}\n < {response.status_code} {response.reason}")
            except requests.exceptions.ConnectionError:
                # retry
                time.sleep(0.5)
                continue

            # ready
            if response.status_code == 200:
                dtslogger.debug(f"Container '{container_name}' is ready")
                self._backend_ip = container_ip
                return True
            # timeout
            if time.time() - stime > timeout:
                dtslogger.error(f"Timeout reached ({timeout}s) while waiting for container '{container_name}'")
                return False
            # retry
            time.sleep(0.5)

    def _start_frontend(self, args: WindowArgs):
        if self._backend_ip is None:
            raise ValueError("Backend not ready. This should not have happened.")
        app_bin = get_path_to_binary(get_most_recent_version_installed())
        app_config = [
            "--url", f"http://{self._backend_ip}:{self._BACKEND_REMOTE_PORT}/app/",
        ]
        # add extra arguments
        for k, v in args.items():
            app_config.extend([f"--{k}", str(v)])
        # run the app
        dtslogger.info("Launching viewer...")
        app_cmd = [app_bin] + app_config
        dtslogger.debug(f"$ > {app_cmd}")
        self._frontend = subprocess.Popen(app_cmd)

    def _join_frontend(self):
        self._frontend.wait()
        dtslogger.info("Viewer closed. Exiting...")

    def _stop(self):
        if self._frontend is not None:
            self._frontend.terminate()
        if self._backend is not None:
            self._backend.stop()
