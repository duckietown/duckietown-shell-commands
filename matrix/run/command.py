import json
import os
import plistlib
import re
import time
import shlex
import errno
from collections import Counter
from pathlib import Path

import subprocess
import platform
import socket
import sys
import uuid
from socket import AF_INET, SOCK_STREAM
from http.server import HTTPServer, SimpleHTTPRequestHandler
from threading import Thread
from typing import Optional, Callable
from shutil import which

from dt_shell import DTCommandAbs, dtslogger, DTShell
from dt_shell.constants import DB_BILLBOARDS
from dt_shell.database import DTShellDatabase
from ..engine.run.command import MatrixEngine
from utils.misc_utils import open_browser_url
from utils.duckiematrix_utils import \
    APP_NAME, \
    get_most_recent_version_installed, \
    get_path_to_app, \
    get_os_family

EXTERNAL_SHUTDOWN_REQUEST: str = "===REQUESTED-EXTERNAL-SHUTDOWN==="
FEX_EXECUTABLES = ("FEX", "FEXInterpreter")
ARM64_MACHINES = ("aarch64", "arm64")
FEX_SETUP_GUIDANCE = (
    "See https://fex-emu.com/ for setup instructions, or use --browser to avoid the "
    "native renderer."
)
WINDOWS_ARM64_SETUP_GUIDANCE = (
    "Windows on ARM64 can run x86-64 applications through Windows emulation. "
    "If launch fails, verify x64 emulation support is available, or use --browser to avoid "
    "the native renderer."
)


def _mask_token_value(token: str) -> str:
    parts = token.split("-", maxsplit=2)
    if len(parts) == 3:
        return f"{parts[0]}-{parts[1]}-{'*' * len(parts[2])}"
    if len(parts) == 2:
        return f"{parts[0]}-{'*' * len(parts[1])}"
    return "*" * len(token)


def _supports_terminal_hyperlinks() -> bool:
    if not sys.stdout.isatty():
        return False
    if os.environ.get("TERM_PROGRAM") in {"vscode", "iTerm.app", "WezTerm"}:
        return True
    if os.environ.get("WT_SESSION") or os.environ.get("KONSOLE_VERSION"):
        return True
    vte_version = os.environ.get("VTE_VERSION")
    return vte_version is not None and vte_version.isdigit() and int(vte_version) >= 5000


def _mask_token_in_text(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group("token")
        suffix = "/" if token.endswith("/") else ""
        token = token[:-1] if suffix else token
        return f"token={_mask_token_value(token)}{suffix}"

    return re.sub(r"token=(?P<token>[^&\s\"]+)", replace, text)


def _format_navigation_url(url: str, token: str) -> str:
    display_url = _mask_token_in_text(url)
    if not _supports_terminal_hyperlinks():
        return display_url
    escape = "\033"
    return f"{escape}]8;;{url}{escape}\\{display_url}{escape}]8;;{escape}\\"


class RedactingSimpleHTTPRequestHandler(SimpleHTTPRequestHandler):

    def log_message(self, format: str, *args) -> None:
        sanitized_args = tuple(
            _mask_token_in_text(arg) if isinstance(arg, str) else arg
            for arg in args
        )
        super_ = super()
        super_.log_message(format, *sanitized_args)


def _build_renderer_container_command(
    app_bin: str,
    app_config: list,
    container_image: str,
):
    path = os.path.expanduser(app_bin)
    app_bin = os.path.abspath(path)
    app_dir = os.path.dirname(app_bin)
    app_name = os.path.basename(app_bin)
    home = os.path.expanduser("~")
    uuid4_ = uuid.uuid4()
    container_name = f"dts-duckiematrix-renderer-{uuid4_.hex[:8]}"
    command = [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", "host",
        "--runtime", "runc",
        "-e", "DISPLAY",
        "-e", f"HOME={home}",
        "-v", "/tmp/.X11-unix:/tmp/.X11-unix:rw",
        "-v", f"{home}:{home}:rw",
        "-v", f"{app_dir}:{app_dir}:ro",
        "-w", app_dir,
        container_image,
        f"./{app_name}",
        *app_config,
    ]
    return command, container_name


class DTCommand(DTCommandAbs):

    help = f'Runs the {APP_NAME} renderer'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        container_image = parsed.container_image
        # ---
        # check for conflicting arguments
        run_engine: bool = parsed.standalone
        run_renderer: bool = True
        # - map VS sandbox
        if parsed.sandbox and parsed.map is not None:
            dtslogger.error("Sandbox mode (--sandbox) and custom map (-m/--map) "
                            "cannot be used together.")
            return
        # - vulkan VS opengl
        if parsed.force_vulkan and parsed.force_opengl:
            dtslogger.error("You cannot use --force-vulkan and --force-opengl together.")
            return
        # - links VS renderer-only
        if len(parsed.links) > 0 and not run_engine:
            dtslogger.error("You cannot use --links without -S/--standalone.")
            return
        # - xvfb only works for native renderer mode
        if parsed.xvfb and parsed.browser:
            dtslogger.error("You cannot use --xvfb together with --browser.")
            return
        if parsed.xvfb and container_image:
            dtslogger.error(
                "You cannot use --xvfb together with --container-image.",
            )
            return
        if parsed.renderer_binary and parsed.browser:
            dtslogger.error("You cannot use --renderer-binary together with --browser.")
            return
        if container_image and parsed.browser:
            dtslogger.error(
                "You cannot use --container-image together with --browser.",
            )
            return
        # make sure the map is given (in standalone mode)
        if run_engine and not parsed.map and not parsed.sandbox:
            dtslogger.error("You need to specify a map with -m/--map when running in "
                            "Standalone mode, or use a default map with -s/--sandbox.")
            return
        # make sure the time step is only given in gym mode
        # if parsed.delta_t is not None and not parsed.simulation:
        #     dtslogger.error("You can specify a --delta-t only when running with "
        #                     "--gym/--simulation.")
        #     return
        # profiler
        if parsed.profiler and not run_engine:
            dtslogger.error("You cannot use --profiler without -S/--standalone.")
            return
        if container_image and platform.system() != "Linux":
            dtslogger.error("You cannot use --container-image outside Linux.")
            return
        # configure the engine if in standalone
        engine: Optional[MatrixEngine] = None
        if run_engine:
            engine = shell.include.matrix.engine.run.make_engine(shell, parsed, use_defaults=True)
            if engine is None:
                return
            # ENGINE is now configured
            # -------------------------------------------------------------------------------------

        # configure renderer
        app_path: Optional[str] = None
        app_config: list = []
        app_prefix: list = []
        terminate_renderer: Optional[Callable] = None
        if run_renderer:
            os_family = parsed.os_family
            browser = parsed.browser
            app_bin: Optional[str] = None
            if parsed.renderer_binary:
                os_family = os_family or get_os_family()
                version = "custom"
                path = os.path.expanduser(parsed.renderer_binary)
                app_bin = os.path.abspath(path)
                app_path = app_bin
            else:
                if os_family:
                    if browser:
                        dtslogger.error("You cannot use -os/--os-family and --browser together.")
                        return
                    if os_family not in ("linux", "macos", "windows"):
                        dtslogger.error(f"Unsupported os-family '{os_family}'. "
                                        f"Supported values are: linux, macos, windows.")
                        return
                else:
                    os_family = get_os_family()
                version = parsed.version
                if version:
                    shell.include.matrix.install.command(shell, ("--version", version))
                else:
                    install_args = ["--update"]
                    if browser:
                        install_args.append("--webgl")
                    else:
                        install_args.extend(["--os-family", os_family])
                    shell.include.matrix.install.command(shell, install_args)
                    version = get_most_recent_version_installed(os_family, browser)
                app_path = get_path_to_app(os_family, version, browser) if version is not None else None
                if not browser:
                    app_bin = app_path
            dtslogger.info(f"Configuring Renderer ({version})...")
            dtslogger.debug(f"Will try to run {version}...")
            # make sure the app is installed
            if app_path is None:
                extra = f"version v{parsed.version} " if parsed.version is not None else ""
                dtslogger.error(f"The app {extra}was not found on your disk.\n"
                                f"Use the command `dts matrix install` to download it.")
                return
            if container_image and os_family != "linux":
                dtslogger.error(
                    "You cannot use --container-image with a non-Linux renderer.",
                )
                return
            if not browser:
                if app_bin is None:
                    dtslogger.error("Renderer binary path is not configured.")
                    return
                if os_family == "macos":
                    renderer_binary_exists = os.path.exists(app_bin)
                else:
                    renderer_binary_exists = os.path.isfile(app_bin)
                if not renderer_binary_exists:
                    dtslogger.error(f"Renderer binary not found at {app_bin!r}.")
                    return
                if should_run_linux_renderer_through_fex(os_family):
                    if container_image:
                        dtslogger.error(
                            "You cannot use --container-image on an ARM64 Linux host with the native "
                            "x86-64 renderer. Use the native launcher with FEX-EMU, or use "
                            "--browser."
                        )
                        return
                    fex_executable = find_fex_executable()
                    if fex_executable is None:
                        message = format_fex_renderer_message()
                        dtslogger.error(message)
                        return
                    app_prefix = [fex_executable]
                elif is_arm64_windows_host(os_family):
                    dtslogger.info(
                        "Detected an ARM64 Windows host. The Windows Duckiematrix renderer "
                        "is an x86-64 binary and will rely on Windows x64 emulation."
                    )
            # Unity on macOS/Windows uses "-" to mean "log to stdout"; "/dev/stdout" works on Linux.
            app_config = [
                "-logfile", "/dev/stdout" if os_family == "linux" else "-"
            ]
            # graphics API
            if parsed.force_opengl:
                app_config += ["-force-opengl"]
            elif parsed.force_vulkan:
                app_config += ["-force-vulkan"]
            else:
                # by default, we use Vulkan for native platforms
                # for Windows binaries (WSL), let Unity auto-detect the graphics API
                if os_family != "windows":
                    app_config += ["-force-vulkan"]
            # custom engine
            if parsed.engine_hostname is not None:
                app_config += ["--engine-hostname", parsed.engine_hostname]
            _ep = parsed.engine_control_port if parsed.engine_control_port is not None else (7502 + parsed.port_offset if parsed.port_offset else None)
            _ewp = parsed.engine_ws_control_port if parsed.engine_ws_control_port is not None else (7503 + parsed.port_offset if parsed.port_offset else None)
            if _ep is not None:
                app_config += ["--engine-control-port", str(_ep)]
            if _ewp is not None:
                app_config += ["--engine-ws-control-port", str(_ewp)]
            # custom renderer ID
            if parsed.renderer_id is not None:
                app_config += ["--renderer-id", f"renderer_{parsed.renderer_id}"]
            # custom renderer key
            if parsed.renderer_key is not None:
                app_config += ["--renderer-key", parsed.renderer_key]
            # By default, display the tutorial
            if parsed.no_tutorial:
                pass
            else:
                app_config += ["--tutorial"]
            if parsed.profiler:
                app_config += ["--profiler"]
            # token
            app_config += ["--token", shell.profile.secrets.dt_token]
            # billboards
            billboards_database = DTShellDatabase.open(DB_BILLBOARDS)
            billboard_names = shell.get_billboard_names(billboards_database)
            if billboard_names:
                billboard = shell.get_billboard(billboards_database, billboard_names)
                if billboard:
                    app_config += ["--billboard", billboard]
                app_config += ["--billboards-path", billboards_database.yaml]
                # convert list with repeated names to JSON with frequencies
                counter = Counter(billboard_names)
                billboard_names_dict = dict(counter)
                app_config += ["--billboard-names", json.dumps(billboard_names_dict)]
            # ---
            dtslogger.info("Renderer configured!")
            # RENDERER is now configured
            # -------------------------------------------------------------------------------------

        # run
        try:
            # - engine
            if run_engine:
                if not parsed.no_pull:
                    engine.pull()
                engine.start()

            # - renderer
            if run_renderer:
                # wait for the engine (if any) to become healthy
                if run_engine:
                    timeout = 20
                    dtslogger.info(f"Waiting up to {timeout} seconds for the Engine to start...")
                    try:
                        engine.wait_until_healthy(timeout)
                    except Exception as e:
                        dtslogger.error(f"The Engine failed to become healthy within {timeout} "
                                        f"seconds. Try running with the --verbose flag to gain "
                                        f"insights into the problem.\n"
                                        f"The error reads:\n{e}")
                        engine.stop()
                        return

                if browser:
                    dtslogger.info("Launching Renderer in browser...")
                    os.chdir(app_path)
                    host = parsed.host
                    port = parsed.port
                    if port is None:
                        with socket.socket(AF_INET, SOCK_STREAM) as socket_:
                            socket_.bind((host, 0))
                            socket_.listen(1)
                            sock_name = socket_.getsockname()
                            port = sock_name[1]
                    server = HTTPServer((host, port), RedactingSimpleHTTPRequestHandler)
                    server_thread = Thread(target=server.serve_forever)
                    server_thread.daemon = True
                    url = f"http://{host}:{port}/?"
                    if parsed.renderer_id is not None:
                        url += f"renderer-id={parsed.renderer_id}&"
                    if parsed.renderer_key is not None:
                        url += f"renderer-key={parsed.renderer_key}&"
                    if parsed.engine_hostname is not None:
                        url += f"engine-hostname={parsed.engine_hostname}&"
                    _ep = parsed.engine_control_port if parsed.engine_control_port is not None else (7502 + parsed.port_offset if parsed.port_offset else None)
                    _ewp = parsed.engine_ws_control_port if parsed.engine_ws_control_port is not None else (7503 + parsed.port_offset if parsed.port_offset else None)
                    if _ep is not None:
                        url += f"engine-control-port={_ep}&"
                    if _ewp is not None:
                        url += f"engine-ws-control-port={_ewp}&"
                    url += f"profiler={'true' if parsed.profiler else 'false'}&"
                    url += f"tutorial={'true' if not parsed.no_tutorial else 'false'}&"
                    token = shell.profile.secrets.dt_token
                    url += f"token={token}/"
                    server_thread.start()
                    browser_opened = False
                    if os_family == "windows":
                        try:
                            url = url.replace("&", "^&")
                            subprocess.run(
                                ["cmd.exe", "/c", "start", f"{url}"], 
                                stderr=subprocess.DEVNULL, 
                                stdout=subprocess.DEVNULL,
                            )
                            browser_opened = True
                        except Exception:
                            pass
                    if not browser_opened:
                        browser_opened = open_browser_url(url)
                    if not browser_opened:
                        dtslogger.warning("Could not open browser.")
                    formatted_url = _format_navigation_url(url, token)
                    dtslogger.info(f"Navigate to {formatted_url}.")
                    # wait for the engine to terminate
                    if run_engine:
                        engine.join()
                    else:
                        server_thread.join()
                else:
                    # run the app
                    dtslogger.info("Launching Renderer...")
                    time.sleep(2)
                    if container_image:
                        container_cmd, container_name = _build_renderer_container_command(
                            app_bin,
                            app_config,
                            parsed.container_image,
                        )
                        dtslogger.info(f"Launching Renderer container ({container_name})...")
                        dtslogger.debug(f"$ > {container_cmd}")
                        renderer = subprocess.Popen(
                            container_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                        )

                        def terminate_renderer(*_):
                            # noinspection PyBroadException
                            try:
                                subprocess.run(
                                    ["docker", "kill", container_name],
                                    check=False,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                )
                            except Exception:
                                pass
                            try:
                                renderer.kill()
                            except Exception:
                                pass

                    else:
                        if os_family == "macos":
                            try:
                                app_path_list = [get_macos_app_executable(app_path)]
                            except FileNotFoundError as error:
                                error_string = str(error)
                                dtslogger.error(error_string)
                                return
                        else:
                            app_path_list = [*app_prefix, app_bin]
                        app_cmd = app_path_list + app_config
                        if parsed.xvfb:
                            if os_family != "linux":
                                dtslogger.error("--xvfb is supported only with Linux native renderer binaries.")
                                return
                            if which("xvfb-run") is None:
                                dtslogger.error("Could not find 'xvfb-run' in PATH. Install xvfb first.")
                                return
                            xvfb_args = shlex.split(parsed.xvfb_args or "")
                            app_cmd = ["xvfb-run", "-a", *xvfb_args, "--", *app_cmd]
                        dtslogger.debug(f"$ > {app_cmd}")
                        try:
                            renderer = subprocess.Popen(app_cmd, stdout=subprocess.PIPE)
                        except OSError as error:
                            if error.errno == errno.ENOEXEC:
                                show_exec_format_error(os_family, app_path)
                                return
                            raise
                        # this is how we terminate the renderer

                        def terminate_renderer(*_):
                            # noinspection PyBroadException
                            try:
                                if os_family == "windows":
                                    # For Windows binaries in WSL, kill by process name since WSL PIDs don't map to Windows
                                    app_basename = os.path.basename(app_path)
                                    subprocess.run(
                                        ["taskkill.exe", "/F", "/IM", app_basename],
                                        stderr=subprocess.DEVNULL,
                                    )
                                else:
                                    renderer.kill()
                            except Exception:
                                pass

                    # wait for the renderer to terminate
                    join_renderer(renderer, parsed.verbose)
            else:
                # wait for the engine to terminate
                engine.join()

        finally:
            if run_engine:
                engine.stop()
            if run_renderer and terminate_renderer:
                terminate_renderer()

    @staticmethod
    def complete(shell, word, line):
        return []


def join_renderer(process: subprocess.Popen, verbose: bool = False):
    while True:
        line = process.stdout.readline()
        if not line:
            break
        line = line.decode("utf-8")
        if EXTERNAL_SHUTDOWN_REQUEST in line:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return
        if verbose:
            print(line, end="")


def is_arm64_machine() -> bool:
    machine = platform.machine()
    return machine.lower() in ARM64_MACHINES


def should_run_linux_renderer_through_fex(os_family: str) -> bool:
    return (
        os_family == "linux"
        and platform.system() == "Linux"
        and is_arm64_machine()
    )


def is_arm64_windows_host(os_family: str) -> bool:
    return os_family == "windows" and is_arm64_machine()


def find_fex_executable() -> Optional[str]:
    for executable in FEX_EXECUTABLES:
        executable_path = which(executable)
        if executable_path is not None:
            return executable_path
    return None


def format_fex_renderer_message(*, launch_failed: bool = False, app_path: Optional[str] = None) -> str:
    if launch_failed:
        message = (
            "Failed to execute the native Linux Duckiematrix renderer.\n"
            "This host is ARM64 and the renderer binary is x86-64, so it must be run through "
            "FEX-EMU with an x86-64 RootFS configured.\n"
            f"{FEX_SETUP_GUIDANCE}"
        )
    else:
        message = (
            "The native Linux Duckiematrix renderer is an x86-64 binary, "
            "but this host is ARM64.\n"
            "Install and configure FEX-EMU, then rerun this command.\n"
            f"{FEX_SETUP_GUIDANCE}"
        )
    if app_path is not None:
        message += f"\nRenderer path: {app_path}"
    return message


def format_windows_arm64_renderer_message(app_path: Optional[str] = None) -> str:
    message = (
        "Failed to execute the native Windows Duckiematrix renderer.\n"
        "This host is ARM64 and the renderer binary is x86-64, so it relies on Windows "
        "x64 emulation support.\n"
        f"{WINDOWS_ARM64_SETUP_GUIDANCE}"
    )
    if app_path is not None:
        message += f"\nRenderer path: {app_path}"
    return message


def show_exec_format_error(os_family: str, app_path: str):
    if should_run_linux_renderer_through_fex(os_family):
        message = format_fex_renderer_message(launch_failed=True, app_path=app_path)
        dtslogger.error(message)
        return
    if is_arm64_windows_host(os_family):
        message = format_windows_arm64_renderer_message(app_path=app_path)
        dtslogger.error(message)
        return
    dtslogger.error(f"Failed to execute renderer binary '{app_path}'.")


def get_macos_app_executable(app_path: str) -> str:
    app_bundle = Path(app_path)
    info_plist = app_bundle / "Contents" / "Info.plist"
    executable_name = app_bundle.stem
    if info_plist.is_file():
        try:
            with info_plist.open("rb") as file:
                plist_data = plistlib.load(file)
                bundle_executable = plist_data.get("CFBundleExecutable")
                executable_name = bundle_executable or executable_name
        except (OSError, plistlib.InvalidFileException, ValueError):
            pass
    executable_path = app_bundle / "Contents" / "MacOS" / executable_name
    if not executable_path.is_file():
        raise FileNotFoundError(f"Could not find executable in macOS app bundle '{app_path}'.")
    return str(executable_path)
