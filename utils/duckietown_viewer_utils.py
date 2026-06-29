import glob
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from threading import Thread
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple, Union

import dockertown
import requests
from dockertown import Container
from dockertown import DockerClient
from dockertown.exceptions import NoSuchContainer, NoSuchImage
from dt_data_api import DataClient

import dt_shell
from dt_shell import dtslogger, DTShell, UserError
from utils.docker_utils import get_client, get_endpoint_architecture, get_registry_to_use, pull_image
from utils.duckietown_utils import USER_DATA_DIR, get_distro
from utils.misc_utils import open_browser_url, versiontuple, random_string
from utils.networking_utils import get_duckiebot_ip

APP_NAME = "duckietown-viewer"
DCSS_SPACE_NAME = "public"
DCSS_APP_DIR = f"assets/{APP_NAME}/"
DCSS_APP_RELEASES_DIR = f"assets/{APP_NAME}/releases/"
APP_LOCAL_DIR = os.path.join(USER_DATA_DIR, APP_NAME)
APP_RELEASES_DIR = os.path.join(APP_LOCAL_DIR, "releases")

AVAHI_SOCKET = "/var/run/avahi-daemon/socket"
SUPPORTED_OS_FAMILIES = ("linux", "macos", "windows")

WindowArgs = Dict[str, Union[int, float, str]]


def linux_path_to_windows(path: str) -> Optional[str]:
    """Convert a Linux (WSL) filesystem path to its Windows equivalent using ``wslpath``.

    Args:
        path: The Linux/WSL path to convert.

    Returns:
        The Windows-style path string, or ``None`` if the conversion fails.
    """
    try:
        result = subprocess.run(
            ["wslpath", "-w", path],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_installed_windows_app_path() -> Optional[str]:
    """Locate the installed Duckietown Viewer executable on a Windows system (via WSL).

    Looks for the app under ``%LOCALAPPDATA%\\Programs\\<APP_NAME>\\`` and returns
    the path to the first ``.exe`` that is not an uninstaller.

    Returns:
        The path to the ``.exe`` binary, or ``None`` if it cannot be found.
    """
    try:
        result = subprocess.run(
            ["cmd.exe", "/c", "echo %LOCALAPPDATA%"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            return None
        windows_path = result.stdout.strip()
        result2 = subprocess.run(
            ["wslpath", windows_path],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result2.returncode != 0:
            return None
        wsl_path = result2.stdout.strip()
        search_dir = os.path.join(wsl_path, "Programs", APP_NAME)
        pattern = os.path.join(search_dir, "*.exe")
        matches = [
            file for file in glob.glob(pattern)
            if "uninstall" not in file.lower()
        ]
        return matches[0] if matches else None
    except Exception:
        return None


def get_os_family() -> str:
    """Detect the current operating-system family.

    Checks for WSL by inspecting ``/proc/version``, then falls back to
    ``sys.platform`` to distinguish between ``"linux"``, ``"windows"``,
    and ``"macos"``.

    Returns:
        One of ``"linux"``, ``"windows"``, or ``"macos"``.
    """
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


def resolve_os_family(os_family: str = "", browser: bool = False) -> str:
    """Resolve and validate the target OS family string.

    The resolved OS family is based on :func:`get_os_family` when *os_family*
    is empty, and an ``"-arm64"`` suffix is appended when running on ARM
    hardware.

    Args:
        os_family: Explicit OS family override (e.g. ``"linux"``, ``"macos"``,
            ``"windows"``).  Pass an empty string for auto-detection.
        browser: Whether the caller intends to open a browser instead of the
            native app.  Mutually exclusive with a non-empty *os_family*.

    Returns:
        The resolved OS family string, potentially suffixed with ``"-arm64"``.

    Raises:
        UserError: If *os_family* and *browser* are both specified, or if
            *os_family* is not in :data:`SUPPORTED_OS_FAMILIES`.
    """
    machine = platform.machine()
    lowercase_machine = machine.lower()
    if os_family:
        if browser:
            raise UserError("You cannot use -os/--os-family and --browser together.")
        if os_family not in SUPPORTED_OS_FAMILIES:
            raise UserError(
                f"Unsupported os-family '{os_family}'. "
                f"Supported values are: {', '.join(SUPPORTED_OS_FAMILIES)}."
            )
        if lowercase_machine in ("aarch64", "arm64"):
            os_family += "-arm64"
        return os_family
    os_family = get_os_family()
    if lowercase_machine in ("aarch64", "arm64"):
        os_family += "-arm64"
    return os_family


def get_latest_version(os_family: str = "") -> Optional[str]:
    """Fetch the latest available version string from the Duckietown Cloud Storage.

    Args:
        os_family: The OS family for which to look up the latest version
            (e.g. ``"linux"``, ``"macos"``).  An empty string means no suffix.

    Returns:
        The version string (e.g. ``"1.2.3"``), or ``None`` if no release has
        been published for the given OS family.
    """
    # create storage client
    client = DataClient()
    storage = client.storage(DCSS_SPACE_NAME)
    # get latest version
    latest_version_obj = os.path.join(DCSS_APP_DIR, f"latest-{os_family}")
    try:
        download = storage.download(latest_version_obj)
        download.join()
    except FileNotFoundError:
        return None
    return download.data.decode("ascii").strip()


def get_all_installed_releases(os_family: str = "") -> List[str]:
    """Return the version strings of all locally installed releases.

    Args:
        os_family: The OS family to filter releases by.

    Returns:
        A list of version strings (e.g. ``["1.0.0-linux", "1.2.3-linux"]``).
    """
    app_dir = os.path.join(APP_RELEASES_DIR, f"*-{os_family}")
    dirs = glob.glob(app_dir)
    version_regex = r"v([0-9]+)\.([0-9]+)\.([0-9]+)"
    version_pattern = re.compile(version_regex)
    is_release_dir = lambda fp: os.path.isdir(fp) and version_pattern.match(os.path.basename(fp))
    return list(map(lambda p: os.path.basename(p)[1:], filter(is_release_dir, dirs)))


def get_most_recent_version_installed(os_family: str = "") -> Optional[str]:
    """Find the highest-versioned locally installed release.

    Args:
        os_family: The OS family to filter releases by.

    Returns:
        The version string of the most recent locally installed release
        (e.g. ``"1.2.3"``), or ``None`` if nothing is installed.
    """
    releases = get_all_installed_releases(os_family)
    release = None
    for r in releases:
        if release is None or versiontuple(r) > versiontuple(release):
            release = r
    if release is None:
        return None
    split_release = release.split("-")
    return split_release[0]


def get_path_to_install(version: str, os_family: str = ""):
    """Return the local installation directory for a specific version.

    Args:
        version: The version string to look up (e.g. ``"1.2.3"``).
        os_family: The OS family for which the version was installed.

    Returns:
        The absolute path to the installation directory, or ``None`` if the
        directory does not exist.
    """
    app_dir = os.path.join(APP_RELEASES_DIR, f"v{version}-{os_family}")
    if not os.path.isdir(app_dir):
        app_dir = None
    return app_dir


def get_path_to_binary(version: str, os_family: str = ""):
    """Return the path to the executable binary for a specific installed version.

    For macOS the path points to the ``.app`` bundle; for Linux it is an
    ``AppImage``; for Windows it is an ``.exe``.

    Args:
        version: The version string (e.g. ``"1.2.3"``).
        os_family: The OS family (``"linux"``, ``"macos"``, or ``"windows"``).

    Returns:
        The path to the binary, or ``None`` if the installation directory does
        not exist.

    Raises:
        ValueError: If *os_family* is not a recognised platform.
    """
    app_dir = get_path_to_install(version, os_family)
    if app_dir is None:
        return None
    if os_family == "macos" or os_family == "macos-arm64":
        return os.path.join(app_dir, "Duckietown Viewer.app")
    if os_family == "linux" or os_family == "linux-arm64":
        ext = "AppImage"
    elif os_family == "windows" or os_family == "windows-arm64":
        ext = "exe"
    else:
        raise ValueError(f"Unknown platform '{os_family}'")
    pattern = os.path.join(app_dir, f"{APP_NAME}-v{version}-*.{ext}")
    matching_files = glob.glob(pattern)
    if matching_files:
        return matching_files[0]
    return os.path.join(app_dir, f"{APP_NAME}-v{version}.{ext}")


def is_version_released(version: str, os_family: str = "") -> bool:
    """Check whether a specific version has been published on the Duckietown Cloud Storage.

    Args:
        version: The version string to check (e.g. ``"1.2.3"``).
        os_family: The OS family for which to check availability.

    Returns:
        ``True`` if the release archive exists in the cloud storage,
        ``False`` otherwise.
    """
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


def remote_zip_obj(version: str, os_family: str = ""):
    """Build the cloud-storage object path for a release archive.

    Args:
        version: The version string (e.g. ``"1.2.3"``).
        os_family: The OS family suffix (e.g. ``"linux"``, ``"macos"``).

    Returns:
        The object path (key) of the release ``.zip`` on the Duckietown Cloud
        Storage Service.
    """
    return os.path.join(DCSS_APP_RELEASES_DIR, f"{APP_NAME}-{version}-{os_family}.zip")


def mark_as_latest_version(token: str, version: str, os_family: str):
    """Upload a pointer file to the cloud storage that designates a version as the latest.

    Args:
        token: Authentication token for the Duckietown Cloud Storage Service.
        version: The version string to mark as latest (e.g. ``"1.2.3"``).
        os_family: The OS family for which this version should be marked latest.
    """
    # create storage client
    client = DataClient(token)
    storage = client.storage(DCSS_SPACE_NAME)
    # get latest version
    latest_version_obj = os.path.join(DCSS_APP_DIR, f"latest-{os_family}")
    upload = storage.upload(version.encode("ascii"), latest_version_obj)
    upload.join()


def ensure_duckietown_viewer_installed(os_family: str = "", log_prefix: str = ""):
    """Download and install the Duckietown Viewer if a newer version is available.

    Compares the most recently installed local version against the latest version
    published on the cloud storage.  If the local version is absent or outdated
    the new release is downloaded, extracted, and installed.  For Windows an NSIS
    silent installer is executed; for macOS the ``.app`` bundle is extracted from
    a DMG image.

    Args:
        os_family: The OS family to install the viewer for.  Auto-detected when
            empty.
        log_prefix: Prefix string prepended to every log message (defaults to
            ``" > "``).
    """
    shell: DTShell = dt_shell.shell
    log_prefix = log_prefix or " > "

    # make sure the app is not already installed
    installed_version: Optional[str] = get_most_recent_version_installed(os_family)
    # get latest version available on the DCSS
    latest: Optional[str] = get_latest_version(os_family)
    if latest is None:
        dtslogger.error(f"{log_prefix}No version available for installation.")
        return
    # compare installed and latest versions
    if installed_version:
        if installed_version == latest:
            return
        os.remove(get_path_to_binary(installed_version, os_family))
        os.rmdir(get_path_to_install(installed_version, os_family))
    # download new version
    app_dir = os.path.join(APP_RELEASES_DIR, f"v{latest}-{os_family}")

    dtslogger.info(f"{log_prefix}Downloading version v{latest}...")
    os.makedirs(app_dir, exist_ok=True)
    zip_remote = remote_zip_obj(latest, os_family)
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
    # On macOS, extract the .app from the DMG
    if os_family == "macos" or os_family == "macos-arm64":
        dmg_pattern = os.path.join(app_dir, "*.dmg")
        dmg_files = glob.glob(dmg_pattern)
        if dmg_files:
            dmg_file = dmg_files[0]
            dtslogger.info(f"{log_prefix}Mounting DMG...")
            # Mount the DMG
            result = subprocess.run(
                ["hdiutil", "attach", dmg_file, "-nobrowse"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                # Parse mount point from output
                mount_point = None
                for line in result.stdout.split("\n"):
                    if "/Volumes/" in line:
                        split_line = line.split("\t")
                        mount_point = split_line[-1].strip()
                        break
                if mount_point:
                    # Find .app in mounted volume
                    app_pattern = os.path.join(mount_point, "*.app")
                    app_files = glob.glob(app_pattern)
                    if app_files:
                        dtslogger.info(
                            f"{log_prefix}Extracting application..."
                        )
                        # Copy .app to installation directory
                        app_name = os.path.basename(app_files[0])
                        dest_app = os.path.join(app_dir, app_name)
                        subprocess.check_call(
                            ["cp", "-R", app_files[0], dest_app]
                        )
                    # Unmount the DMG
                    dtslogger.info(f"{log_prefix}Unmounting DMG...")
                    subprocess.run(
                        ["hdiutil", "detach", mount_point],
                        capture_output=True
                    )
                # Remove the DMG file
                os.remove(dmg_file)
    if os_family == "windows" or os_family == "windows-arm64":
        # ensure the installer is executable (needed in WSL)
        installer = get_path_to_binary(latest, os_family)
        if installer and os.path.exists(installer):
            installer_status = os.stat(installer)
            os.chmod(installer, installer_status.st_mode | 0o111)
        # run the NSIS installer silently so the app ends up in %LOCALAPPDATA%
        dtslogger.info(
            f"{log_prefix}Running Windows installer silently..."
        )
        subprocess.check_call([installer, "/S"])
        dtslogger.info(f"{log_prefix}Windows installer completed.")
    # clean up
    dtslogger.info(f"{log_prefix}Removing temporary files...")
    os.remove(zip_local)
    # ---
    dtslogger.info(f"{log_prefix}Installation completed successfully!")


def launch_viewer(
    app: str,
    *,
    os_family: str = "",
    robot: Optional[str] = None,
    verbose: bool = False,
    fullscreen: bool = False,
    menu: bool = False,
    on_top: bool = False,
    enable_hardware_acceleration: bool = False,
    browser: bool = False,
    no_pull: bool = False,
    window_args: Optional[WindowArgs] = None
) -> 'DuckietownViewerInstance':
    """Create and start a :class:`DuckietownViewerInstance`.

    This is a convenience wrapper that instantiates the viewer, calls
    :meth:`DuckietownViewerInstance.start`, and returns the instance.

    Args:
        app: The name of the viewer app to launch (must be one of
            :attr:`DuckietownViewerInstance._KNOWN_APPS`).
        os_family: Target OS family string.  Auto-detected when empty.
        robot: Hostname or IP of the robot to connect to.  Required unless
            *window_args* contains a ``"url"`` key.
        verbose: When ``True`` the backend container logs are printed to stdout.
        fullscreen: Launch the viewer in fullscreen mode.
        menu: Show the viewer menu bar.
        on_top: Keep the viewer window on top of all other windows.
        enable_hardware_acceleration: Enable GPU hardware acceleration in the
            viewer.
        browser: Open the viewer URL in the system browser instead of the
            native app window.
        no_pull: Use a local backend image without pulling updates.
        window_args: Extra keyword arguments forwarded to the frontend binary
            as ``--key=value`` CLI flags.  A ``"url"`` key bypasses the
            backend entirely.

    Returns:
        The :class:`DuckietownViewerInstance` after it has finished running.
    """
    viewer = DuckietownViewerInstance(os_family, verbose)
    viewer.start(
        app=app,
        robot=robot,
        fullscreen=fullscreen,
        menu=menu,
        on_top=on_top,
        enable_hardware_acceleration=enable_hardware_acceleration,
        browser=browser,
        no_pull=no_pull,
        window_args=window_args,
    )
    return viewer


class DuckietownViewerInstance:
    """Manages the lifecycle of a Duckietown Viewer session.

    A session consists of two components:

    * **Backend** – a Docker container that serves the viewer web application
      and communicates with a physical or virtual Duckiebot over the network.
    * **Frontend** – the native desktop application (or browser tab) that
      renders the viewer UI by connecting to the backend HTTP server.

    Typical usage::

        viewer = DuckietownViewerInstance(os_family="linux")
        viewer.start("image_viewer", robot="my-duckiebot")
    """

    _BACKEND_DOCKER_IMAGE = "{registry}/duckietown/dt-duckietown-viewer:{distro}"
    _BACKEND_REMOTE_PORT = 8000
    _BACKEND_PORT_ENV = "DT_VIEWER_BACKEND_PORT"
    _KNOWN_APPS = [
        "image_viewer",
        "keyboard_controller",
        "intrinsics_calibrator",
        "extrinsics_calibrator",
        "led_controller",
        "graph_plotter",
        "dashboard"
    ]

    def __init__(self, os_family: str = "", verbose: bool = False):
        """Initialise a new viewer instance.

        Args:
            os_family: The OS family used to locate the correct frontend binary.
                Auto-detected when empty.
            verbose: When ``True`` the Docker backend logs are streamed to
                stdout in a background thread.
        """
        self._os_family: str = os_family
        self._verbose: bool = verbose
        # internal state
        self._backend: Optional[Container] = None
        self._frontend: Optional[subprocess.Popen] = None
        self._backend_url: Optional[str] = None
        self._host_port: Optional[str] = None

    @staticmethod
    def _find_free_host_port() -> str:
        """Find an available TCP port on localhost."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", 0))
            address = sock.getsockname()
            port = address[1]
        finally:
            sock.close()
        return str(port)

    @staticmethod
    def _use_host_network_for_backend() -> bool:
        """Return whether the viewer backend should share the host network."""
        system_name = platform.system()
        return system_name == "Darwin"

    @staticmethod
    def _resolve_backend_vehicle_ip(ip: str, use_host_network: bool) -> Tuple[str, List[Tuple[str, str]]]:
        """Return a backend-reachable vehicle address and any extra host mappings.

        A local virtual robot resolves to loopback on the host. When the
        backend runs in a bridge-networked container, that loopback would point
        back to the backend container itself instead of the Docker host.
        """
        if use_host_network or not ip.startswith("127."):
            return ip, []
        return "host.docker.internal", [("host.docker.internal", "host-gateway")]

    @classmethod
    def _local_arch_image(cls, image: str, docker: DockerClient) -> Optional[str]:
        """Return the local architecture-specific image tag when it exists."""
        try:
            arch = get_endpoint_architecture()
        except Exception:
            dtslogger.debug("Could not determine Docker endpoint architecture.")
            return None

        local_image = f"{image}-{arch}"
        try:
            docker.image.inspect(local_image)
        except NoSuchImage:
            return None
        return local_image

    @classmethod
    def _backend_image(cls, docker: DockerClient, no_pull: bool = False) -> str:
        """Resolve the backend image, optionally using a local development build."""
        image = cls._BACKEND_DOCKER_IMAGE.format(
            registry=get_registry_to_use(),
            distro=get_distro(dt_shell.shell).name
        )
        if no_pull:
            local_image = cls._local_arch_image(image, docker)
            if local_image is None:
                raise UserError(
                    f"No local viewer backend image found for '{image}'. "
                    "Run 'dts devel build' in dt-duckietown-viewer or omit '--no-pull'."
                )
            return local_image

        dtslogger.info("Checking for updates...")
        pull_image(image, docker)
        return image

    def start(
        self,
        app: str,
        robot: Optional[str],
        fullscreen: Optional[bool],
        menu: Optional[bool],
        on_top: Optional[bool],
        enable_hardware_acceleration: Optional[bool],
        browser: bool = False,
        no_pull: bool = False,
        window_args: Optional[WindowArgs] = None
    ):
        """Start the viewer backend (if needed) and then the frontend, blocking until exit.

        If *window_args* contains a ``"url"`` key the backend is skipped and
        the frontend opens that URL directly.  In browser mode the method
        blocks until a ``KeyboardInterrupt`` is received.

        Args:
            app: Name of the viewer app to run.
            robot: Hostname or IP of the target robot.
            fullscreen: Pass ``--fullscreen`` to the frontend.
            menu: Pass ``--menu`` to the frontend.
            on_top: Pass ``--on-top`` to the frontend.
            enable_hardware_acceleration: Pass ``--enable-hardware-acceleration``
                to the frontend.
            browser: Open in the system browser instead of the native app.
            no_pull: Use a local backend image without pulling updates.
            window_args: Additional ``--key=value`` arguments for the frontend.
        """
        if "url" not in window_args.keys():
            self._start_backend(app, robot, no_pull)
            if not self._wait_backend_ready():
                self._backend.stop()
                return
        if browser:
            url = f"http://localhost:{self._host_port}/app/"
            if not open_browser_url(url):
                dtslogger.warning("Could not open browser.")
            dtslogger.info(f"Navigate to {url}")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                dtslogger.info("Exiting...")
        else:
            self._start_frontend(fullscreen, menu, on_top, enable_hardware_acceleration, window_args or {})
            self._join_frontend()
        self._stop()

    def _start_backend(self, app: str, robot: str, no_pull: bool = False):
        """Pull the backend Docker image and start a container for the given app.

        The container exposes the backend HTTP server on a random host port.
        An Avahi socket is mounted into the container when available to enable
        mDNS resolution.  A shutdown hook is registered so the container is
        stopped when the shell exits.

        Args:
            app: The viewer app identifier (must be in :attr:`_KNOWN_APPS`).
            robot: Hostname or IP of the robot to connect to.
            no_pull: Use a local backend image without pulling updates.

        Raises:
            ValueError: If *app* is not in :attr:`_KNOWN_APPS`.
            UserError: If the robot's IP address cannot be resolved.
        """
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
        image = self._backend_image(docker, no_pull)
        dtslogger.debug(f"Using image '{image}'")
        # create container
        container_name: str = f"duckietown-viewer-backend-{random_string()}"
        backend_port = str(self._BACKEND_REMOTE_PORT)
        self._host_port = None
        use_host_network = self._use_host_network_for_backend()
        vehicle_ip, add_hosts = self._resolve_backend_vehicle_ip(ip, use_host_network)
        network_cfg: dict = {
            "publish": [(0, self._BACKEND_REMOTE_PORT)],
        }
        if use_host_network:
            backend_port = self._find_free_host_port()
            self._host_port = backend_port
            network_cfg = {
                "x_passthrough_args": ["--net=host"],
            }
        container_cfg: dict = {
            "name": container_name,
            "detach": True,
            "volumes": [],
            "remove": True,
            "envs": {
                "DT_LAUNCHER": app,
                "VEHICLE_IP": vehicle_ip,
                "VEHICLE_NAME": robot,
                self._BACKEND_PORT_ENV: backend_port,
            },
            **network_cfg,
        }
        if add_hosts:
            container_cfg["add_hosts"] = add_hosts
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
        """Poll the backend HTTP server until it returns ``200 OK`` or a timeout is reached.

        Retrieves the dynamically assigned host port from the running container,
        then sends GET requests to ``http://localhost:<port>/`` at 0.5-second
        intervals.

        Returns:
            ``True`` when the backend is ready, ``False`` if the 10-second
            timeout expires before a successful response is received.
        """
        container: Container = self._backend
        container_name: str = container.name
        dtslogger.debug(f"Waiting for container '{container_name}' to be ready...")

        # retrieve container's published port on the host
        if self._host_port is None:
            container.reload()
            self._host_port: str = container.network_settings.ports[f"{self._BACKEND_REMOTE_PORT}/tcp"][0]["HostPort"]
        
        # use localhost with the published host port (more reliable across Docker versions)
        backend_url = f"localhost:{self._host_port}"
        dtslogger.debug(f"Container '{container_name}' is reachable at '{backend_url}'")
        # wait for the backend to be ready
        stime: float = time.time()
        timeout: float = 10
        while True:
            url: str = f"http://{backend_url}/"
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
                self._backend_url = backend_url
                return True
            # timeout
            if time.time() - stime > timeout:
                dtslogger.error(f"Timeout reached ({timeout}s) while waiting for container '{container_name}'")
                return False
            # retry
            time.sleep(0.5)

    def _start_frontend(self, fullscreen: Optional[bool], menu: Optional[bool], on_top: Optional[bool], enable_hardware_acceleration: Optional[bool], args: WindowArgs):
        """Locate the frontend binary and launch it as a subprocess.

        Builds the CLI argument list from the supplied options, resolves the
        platform-specific binary path, and spawns the process with
        :class:`subprocess.Popen`.  On macOS ``.app`` bundles are launched via
        ``open -n -W``.

        Args:
            fullscreen: Pass ``--fullscreen`` to the binary.
            menu: Pass ``--menu`` to the binary.
            on_top: Pass ``--on-top`` to the binary.
            enable_hardware_acceleration: Pass ``--enable-hardware-acceleration``
                to the binary.
            args: Additional ``key``/``value`` pairs appended as
                ``--key=value`` flags.  A ``"url"`` key overrides the backend
                URL.
        """
        app_config = ["--no-sandbox"]
        if "url" not in args.keys():
            if self._backend_url is None:
                raise ValueError("Backend not ready. This should not have happened.")
            app_config.extend(["--url", f"http://{self._backend_url}/app/"])
        if fullscreen:
            app_config.append("--fullscreen")
        if menu:
            app_config.append("--menu")
        if on_top:
            app_config.append("--on-top")
        if enable_hardware_acceleration:
            app_config.append("--enable-hardware-acceleration")
        os_family = self._os_family
        if os_family == "windows" or os_family == "windows-arm64":
            app_bin = get_installed_windows_app_path()
        else:
            app_bin = get_path_to_binary(get_most_recent_version_installed(os_family), os_family)
        # add extra arguments
        for k, v in args.items():
            app_config.append(f"--{k}={v}")
        # run the app
        dtslogger.info("Launching viewer...")
        # On macOS, use 'open' command for .app bundles
        if (os_family == "macos" or os_family == "macos-arm64") and app_bin.endswith(".app"):
            # -n starts a separate app instance; -W waits until that instance exits.
            app_cmd = ["open", "-n", "-W", app_bin, "--args"] + app_config
        else:
            app_cmd = [app_bin] + app_config
        dtslogger.debug(f"$ > {app_cmd}")
        self._frontend = subprocess.Popen(app_cmd)

    def _join_frontend(self):
        """Block until the frontend process exits."""
        self._frontend.wait()
        dtslogger.info("Viewer closed. Exiting...")

    def _stop(self):
        """Terminate the frontend process and stop the backend container."""
        if self._frontend is not None:
            self._frontend.terminate()
        if self._backend is not None:
            self._backend.stop()
