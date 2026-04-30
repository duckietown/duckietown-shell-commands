import json
import os
import time
import shlex
from collections import Counter

import subprocess
import platform
import socket
import webbrowser
from socket import AF_INET, SOCK_STREAM
from http.server import HTTPServer, SimpleHTTPRequestHandler
from threading import Thread
from typing import Optional, Callable
from shutil import which

from dt_shell import DTCommandAbs, dtslogger, DTShell
from dt_shell.constants import DB_BILLBOARDS
from dt_shell.database import DTShellDatabase
from ..engine.run.command import MatrixEngine
from utils.duckiematrix_utils import \
    APP_NAME, \
    get_most_recent_version_installed, \
    get_path_to_app, \
    get_os_family

EXTERNAL_SHUTDOWN_REQUEST: str = "===REQUESTED-EXTERNAL-SHUTDOWN==="
RENDERER_CONTAINER_IMAGE = "ubuntu:20.04"


def _build_renderer_container_command(app_bin: str, app_config: list):
    app_bin = os.path.abspath(os.path.expanduser(app_bin))
    app_dir = os.path.dirname(app_bin)
    app_name = os.path.basename(app_bin)
    home = os.path.expanduser("~")
    container_name = f"dts-duckiematrix-renderer-{uuid.uuid4().hex[:8]}"
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
        RENDERER_CONTAINER_IMAGE,
        f"./{app_name}",
        *app_config,
    ]
    return command, container_name


class DTCommand(DTCommandAbs):

    help = f'Runs the {APP_NAME} renderer'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
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
        if parsed.xvfb and parsed.container:
            dtslogger.error("You cannot use --xvfb together with --container.")
            return
        if parsed.renderer_binary and parsed.browser:
            dtslogger.error("You cannot use --renderer-binary together with --browser.")
            return
        if parsed.container and parsed.browser:
            dtslogger.error("You cannot use --container together with --browser.")
            return
        # make sure the map is given (in standalone mode)
        if run_engine and not parsed.map and not parsed.sandbox:
            dtslogger.error("You need to specify a map with -m/--map when running in "
                            "Standalone mode, or use a default map with -s/--sandbox.")
            return
        # make sure the time step is only given in gym mode
        if parsed.delta_t is not None and not parsed.simulation:
            dtslogger.error("You can specify a --delta-t only when running with "
                            "--gym/--simulation.")
            return
        if parsed.shm_path:
            if not parsed.simulation:
                dtslogger.error("You cannot use --shm-path without --gym/--simulation.")
                return
            if not run_engine:
                dtslogger.error("You cannot use --shm-path without -S/--standalone.")
                return
        # profiler
        if parsed.profiler and not run_engine:
            dtslogger.error("You cannot use --profiler without -S/--standalone.")
            return
        if parsed.disable_contracts and not run_engine:
            dtslogger.error("You cannot use --disable-contracts without -S/--standalone.")
            return
        if parsed.container and platform.system() != "Linux":
            dtslogger.error("You cannot use --container outside Linux.")
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
        terminate_renderer: Optional[Callable] = None
        if run_renderer:
            os_family = parsed.os_family
            browser = parsed.browser
            app_bin: Optional[str] = None
            if parsed.renderer_binary:
                os_family = os_family or get_os_family()
                version = "custom"
                app_bin = os.path.abspath(os.path.expanduser(parsed.renderer_binary))
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
            if not browser and (app_bin is None or not os.path.isfile(app_bin)):
                dtslogger.error(f"Renderer binary not found at {app_bin!r}.")
                return
            # Unity on Windows/WSL uses "-" to mean "log to stdout"; "/dev/stdout" only exists on Unix-like OSes.
            app_config = [
                "-logfile", "-" if os_family == "windows" else "/dev/stdout"
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
            if parsed.target_frame_rate is not None:
                app_config += ["--target-frame-rate", str(parsed.target_frame_rate)]
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
                    server = HTTPServer((host, port), SimpleHTTPRequestHandler)
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
                    url += f"token={shell.profile.secrets.dt_token}/"
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
                        browser_opened = webbrowser.open(url)
                    if not browser_opened:
                        dtslogger.warning("Could not open browser.")
                    dtslogger.info(f"Navigate to {url}.")
                    # wait for the engine to terminate
                    if run_engine:
                        engine.join()
                    else:
                        server_thread.join()
                else:
                    # run the app
                    os.makedirs("/tmp/Duckietown/Duckiematrix", exist_ok=True)
                    dtslogger.info("Launching Renderer...")
                    time.sleep(2)
                    if parsed.container:
                        container_cmd, container_name = _build_renderer_container_command(
                            app_bin,
                            app_config,
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
                        app_path_list = ["open", app_path, "--args"] if os_family == "macos" else [app_bin]
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
                        renderer = subprocess.Popen(app_cmd, stdout=subprocess.PIPE)
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
            return
        if verbose:
            print(line, end="")
