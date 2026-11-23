import json
import os
import plistlib
import re
import tempfile
import time
import shlex
import errno
import threading
from dataclasses import dataclass
from collections import Counter
from pathlib import Path
from random import choices

import subprocess
import platform
import socket
import sys
import uuid
from socket import AF_INET6
from http.server import HTTPServer, SimpleHTTPRequestHandler
from threading import Thread
from typing import BinaryIO, Optional, Callable
from shutil import which
from urllib.parse import quote

from docker.errors import DockerException
from requests.exceptions import RequestException

try:
    import pty
except ImportError:
    pty = None

from dt_shell import DTCommandAbs, dtslogger, DTShell
from dt_shell.constants import DB_BILLBOARDS
from dt_shell.database import DTShellDatabase
from ..engine.run.command import DEFAULT_STATIC_NETWORK_PORTS, MatrixEngine
from .map_control import (
    MAP_CONTROL_HOSTS,
    MAP_CONTROL_PORT_ENV,
    MAP_CONTROL_TOKEN_ENV,
    MapControl,
    MapControlHTTPServer,
    serve_launcher_request,
)
from utils.host_runner import (
    HOST_RUNNER_ACTIVE_ENV,
    HOST_RUNNER_MATRIX_MAP_CONTROL_ENV,
    HOST_RUNNER_MATRIX_RENDERER_ONLY_ENV,
    HostRunnerError,
    delegate_matrix_run_to_host,
    host_runner_engine_host,
    should_delegate_matrix_run,
)
from utils.misc_utils import open_browser_url
from utils.matrix_trace import (
    RendererTrace,
    TraceSettings,
    TRACE_DURATION_DEFAULT,
    TRACE_OUTPUT_ENV,
    resolve_trace_output,
    trace_limits,
    trace_start_session,
)
from utils.duckiematrix_utils import \
    APP_NAME, \
    get_most_recent_version_installed, \
    get_path_to_app, \
    get_os_family

EXTERNAL_SHUTDOWN_REQUEST: str = "===REQUESTED-EXTERNAL-SHUTDOWN==="
RENDERER_EXIT_POLL_SECONDS = 0.1
RENDERER_TAILED_SHUTDOWN_WAIT_SECONDS = 2
RENDERER_FORCE_KILL_WAIT_SECONDS = 5
RENDERER_MACOS_SHUTDOWN_TIMEOUT_SECONDS = 2
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


def should_run_host_renderer_only() -> bool:
    active_value = os.environ.get(HOST_RUNNER_ACTIVE_ENV, "")
    renderer_only_value = os.environ.get(
        HOST_RUNNER_MATRIX_RENDERER_ONLY_ENV,
        "",
    )
    return active_value == "1" and renderer_only_value == "1"


def resolve_delegated_engine_host(parsed_engine_hostname: Optional[str]) -> Optional[str]:
    if parsed_engine_hostname:
        return parsed_engine_hostname
    return host_runner_engine_host()


def should_use_ipv6_loopback_browser_server(host: str) -> bool:
    return host == "localhost"


def format_http_host(host: str) -> str:
    if ":" not in host:
        return host
    if host.startswith("[") and host.endswith("]"):
        return host
    return f"[{host}]"


def renderer_control_ports(parsed) -> tuple[Optional[int], Optional[int]]:
    return (
        parsed.engine_control_port if parsed.engine_control_port is not None
        else (7502 + parsed.port_offset if parsed.port_offset else None),
        parsed.engine_ws_control_port if parsed.engine_ws_control_port is not None
        else (7503 + parsed.port_offset if parsed.port_offset else None),
    )


def renderer_uses_local_engine(parsed, config: dict) -> bool:
    if parsed.engine_hostname is not None and parsed.engine_hostname not in MAP_CONTROL_HOSTS:
        return False
    port, ws_port = renderer_control_ports(parsed)
    name = "matrix-websocket-bridge-control-out-port" if parsed.browser else "matrix-control-out-port"
    command = config["command"]
    flag = f"--{name}"
    default = DEFAULT_STATIC_NETWORK_PORTS[name]
    engine_port = int(command[command.index(flag) + 1]) if flag in command else default
    renderer_port = ws_port if parsed.browser else port
    return (default if renderer_port is None else renderer_port) == engine_port


def can_manage_local_engine(parsed, config: dict) -> bool:
    docker_endpoint = os.environ.get("DOCKER_HOST", "")
    return (not parsed.container_image and "--build-assets" not in config["command"]
            and renderer_uses_local_engine(parsed, config)
            and (not docker_endpoint or docker_endpoint.startswith(("unix://", "npipe://")))
            and (not parsed.browser or parsed.host in MAP_CONTROL_HOSTS))


def delegated_map_control() -> Optional[tuple[str, str, bool]]:
    if not should_run_host_renderer_only():
        return None
    address = os.environ.get(HOST_RUNNER_MATRIX_MAP_CONTROL_ENV, "")
    match = re.fullmatch(r"([0-9]{1,5}):([a-f0-9]{64}):(0|1)", address)
    if match is None or not 1 <= int(match[1]) <= 65535:
        return None
    return match[1], match[2], match[3] == "1"


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

    return re.sub(r"token=(?P<token>[^&#\s\"]+)", replace, text)


def _format_navigation_url(url: str, token: str) -> str:
    display_url = _mask_token_in_text(url)
    if not _supports_terminal_hyperlinks():
        return display_url
    escape = "\033"
    return f"{escape}]8;;{url}{escape}\\{display_url}{escape}]8;;{escape}\\"


class RedactingSimpleHTTPRequestHandler(SimpleHTTPRequestHandler):

    def do_GET(self) -> None:
        if not serve_launcher_request(self):
            super().do_GET()

    def do_POST(self) -> None:
        if not serve_launcher_request(self):
            self.send_error(404)

    def log_message(self, format: str, *args) -> None:
        sanitized_args = tuple(
            _mask_token_in_text(arg) if isinstance(arg, str) else arg
            for arg in args
        )
        super_ = super()
        super_.log_message(format, *sanitized_args)


class DualStackHTTPServer(HTTPServer):

    address_family = AF_INET6

    def server_bind(self) -> None:
        if socket.has_dualstack_ipv6():
            try:
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            except OSError:
                pass
        super_ = super()
        super_.server_bind()


@dataclass
class BrowserHTTPServerConfiguration:
    server: HTTPServer
    bind_host: str
    display_host: str
    port: int


def create_browser_http_server(
    host: str,
    port: Optional[int],
) -> BrowserHTTPServerConfiguration:
    requested_port = 0 if port is None else port
    if should_use_ipv6_loopback_browser_server(host):
        dtslogger.info(
            "Serving the browser frontend through an IPv6 loopback HTTP server..."
        )
        try:
            server = DualStackHTTPServer(
                ("::1", requested_port),
                RedactingSimpleHTTPRequestHandler,
            )
        except OSError as error:
            error_text = str(error)
            message = "Could not start the IPv6 loopback HTTP server for localhost."
            if error_text:
                message = f"{message} {error_text}"
            message = f"{message} Falling back to IPv4 localhost."
            dtslogger.warning(message)
        else:
            return BrowserHTTPServerConfiguration(
                server=server,
                bind_host="::1",
                display_host="localhost",
                port=server.server_port,
            )
        bind_host = "127.0.0.1"
        server = HTTPServer(
            (bind_host, requested_port),
            RedactingSimpleHTTPRequestHandler,
        )
        return BrowserHTTPServerConfiguration(
            server=server,
            bind_host=bind_host,
            display_host="localhost",
            port=server.server_port,
        )
    bind_host = host
    server = HTTPServer(
        (bind_host, requested_port),
        RedactingSimpleHTTPRequestHandler,
    )
    return BrowserHTTPServerConfiguration(
        server=server,
        bind_host=bind_host,
        display_host=host,
        port=server.server_port,
    )


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


def launch_renderer_process(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
) -> tuple[subprocess.Popen, BinaryIO]:
    if pty is None:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        stream = process.stdout
        if stream is None:
            raise RuntimeError("Renderer process stdout pipe was not created.")
        return process, stream
    master_fd, slave_fd = pty.openpty()
    try:
        process = subprocess.Popen(
            command,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            env=env,
        )
    except Exception:
        os.close(master_fd)
        os.close(slave_fd)
        raise
    else:
        os.close(slave_fd)
    stream = os.fdopen(master_fd, "rb", buffering=0)
    return process, stream


def write_renderer_output(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def flush_renderer_log_chunk_with_shutdown_signal(
    chunk: str,
    buffered: str,
    shutdown_event: threading.Event,
    *, on_line: Callable[[str], None] | None = None,
) -> str:
    buffered += chunk
    while "\n" in buffered:
        line, buffered = buffered.split("\n", 1)
        if EXTERNAL_SHUTDOWN_REQUEST in line:
            shutdown_event.set()
        if on_line is not None:
            on_line(line)
        write_renderer_output(line + "\n")
    return buffered


def tail_renderer_log_file(
    log_path: Path,
    stop_event: threading.Event,
    shutdown_event: threading.Event,
    *, on_line: Callable[[str], None] | None = None,
) -> None:
    buffered = ""
    offset = 0
    while True:
        if log_path.exists():
            with log_path.open("r", encoding="utf-8", errors="replace") as stream:
                stream.seek(offset)
                chunk = stream.read()
                offset = stream.tell()
            if chunk:
                buffered = flush_renderer_log_chunk_with_shutdown_signal(
                    chunk,
                    buffered,
                    shutdown_event,
                    on_line=on_line,
                )
        should_stop = stop_event.wait(0.1)
        if not should_stop:
            continue
        if log_path.exists():
            with log_path.open("r", encoding="utf-8", errors="replace") as stream:
                stream.seek(offset)
                chunk = stream.read()
                offset = stream.tell()
            if chunk:
                buffered = flush_renderer_log_chunk_with_shutdown_signal(
                    chunk,
                    buffered,
                    shutdown_event,
                    on_line=on_line,
                )
        if buffered:
            if EXTERNAL_SHUTDOWN_REQUEST in buffered:
                shutdown_event.set()
            if on_line is not None:
                on_line(buffered)
            write_renderer_output(buffered)
        return


def read_renderer_stream_line(stream: BinaryIO) -> bytes:
    try:
        line = stream.readline()
    except OSError as error:
        if error.errno == errno.EIO:
            return b""
        raise
    return line


def wait_for_process_exit(process: subprocess.Popen, timeout_seconds: float) -> bool:
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return False
    return True


def create_renderer_log_path(
    os_family: str,
    *,
    use_tailed_log_file: bool,
) -> Optional[Path]:
    if os_family != "macos" or not use_tailed_log_file:
        return None
    temp_dir = tempfile.gettempdir()
    log_name = f"duckietown-renderer-{uuid.uuid4().hex}.log"
    return Path(temp_dir) / log_name


def start_renderer_log_tailer(
    log_path: Optional[Path],
    verbose: bool,
    *, on_line: Callable[[str], None] | None = None,
) -> tuple[Optional[threading.Event], Optional[threading.Event], Optional[Thread]]:
    if log_path is None or not verbose:
        return None, None, None
    stop_event = threading.Event()
    shutdown_event = threading.Event()
    thread_suffix = uuid.uuid4().hex[:8]
    thread_name = f"matrix-renderer-log-{thread_suffix}"
    tailer_thread = Thread(
        target=tail_renderer_log_file,
        args=(log_path, stop_event, shutdown_event),
        kwargs={"on_line": on_line},
        daemon=True,
        name=thread_name,
    )
    tailer_thread.start()
    return stop_event, shutdown_event, tailer_thread


def stop_renderer_log_tailer(
    stop_event: Optional[threading.Event],
    tailer_thread: Optional[Thread],
) -> None:
    if stop_event is None or tailer_thread is None:
        return
    stop_event.set()
    tailer_thread.join(timeout=2)


def remove_renderer_log_file(log_path: Optional[Path]) -> None:
    if log_path is None:
        return
    try:
        log_path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def process_is_running(process: Optional[subprocess.Popen]) -> bool:
    if process is None:
        return False
    return process.poll() is None


def wait_for_tailed_renderer_shutdown(
    process: subprocess.Popen,
    shutdown_event: threading.Event,
    terminate_process: Optional[Callable] = None,
) -> None:
    while True:
        exited = wait_for_process_exit(process, RENDERER_EXIT_POLL_SECONDS)
        if exited:
            return
        if not shutdown_event.is_set():
            continue
        exited = wait_for_process_exit(process, RENDERER_TAILED_SHUTDOWN_WAIT_SECONDS)
        if exited:
            return
        if not process_is_running(process):
            return
        if terminate_process is None:
            process.kill()
        else:
            terminate_process()
        wait_for_process_exit(process, RENDERER_FORCE_KILL_WAIT_SECONDS)
        if process_is_running(process):
            process.kill()
            wait_for_process_exit(process, RENDERER_FORCE_KILL_WAIT_SECONDS)
        return


@dataclass
class RendererLaunchConfiguration:
    app_bin: Optional[str]
    app_config: list[str]
    app_path: str
    app_prefix: list[str]
    os_family: str
    renderer_log_path: Optional[Path]
    screen_billboard: Optional[str] = None
    world_billboards: Optional[str] = None


def _webgl_billboard_payload(
    database: DTShellDatabase[dict], weights: Counter[str],
) -> Optional[str]:
    remaining = weights.copy()
    records = []
    while remaining:
        # Keep the desktop weighted selection without reusing a record on another board.
        name = choices(list(remaining), weights=list(remaining.values()))[0]
        del remaining[name]
        entry = database.get(name, None)
        if entry is None or entry.get("enabled") is False:
            continue
        records.append({
            "content": entry.get("content"),
            "graphics": entry.get("graphics"),
            "end_time": entry.get("end_time"),
        })
    return json.dumps(records, ensure_ascii=False, separators=(",", ":")) if records else None


def configure_renderer_launch(
    shell: DTShell,
    parsed,
    delegated_engine_host: Optional[str],
) -> Optional[RendererLaunchConfiguration]:
    app_path: Optional[str] = None
    app_config: list[str] = []
    app_prefix: list[str] = []
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
                return None
            if os_family not in ("linux", "macos", "windows"):
                dtslogger.error(
                    f"Unsupported os-family '{os_family}'. Supported values are: linux, macos, windows."
                )
                return None
        else:
            os_family = get_os_family()
        version = parsed.version
        if version:
            install_args = ["--version", version]
        else:
            install_args = ["--update"]
        if browser:
            install_args.append("--webgl")
        else:
            install_args.extend(["--os-family", os_family])
        shell.include.matrix.install.command(shell, install_args)
        if not version:
            version = get_most_recent_version_installed(os_family, browser)
        if version is not None:
            app_path = get_path_to_app(os_family, version, browser)
        if not browser:
            app_bin = app_path

    dtslogger.info(f"Configuring Renderer ({version})...")
    dtslogger.debug(f"Will try to run {version}...")
    if app_path is None:
        extra = f"version v{parsed.version} " if parsed.version is not None else ""
        dtslogger.error(
            f"The app {extra}was not found on your disk.\n"
            f"Use the command `dts matrix install` to download it."
        )
        return None
    if parsed.container_image and os_family != "linux":
        dtslogger.error(
            "You cannot use --container-image with a non-Linux renderer.",
        )
        return None
    if not browser:
        if app_bin is None:
            dtslogger.error("Renderer binary path is not configured.")
            return None
        if os_family == "macos":
            renderer_binary_exists = os.path.exists(app_bin)
        else:
            renderer_binary_exists = os.path.isfile(app_bin)
        if not renderer_binary_exists:
            dtslogger.error(f"Renderer binary not found at {app_bin!r}.")
            return None
        if should_run_linux_renderer_through_fex(os_family):
            if parsed.container_image:
                dtslogger.error(
                    "You cannot use --container-image on an ARM64 Linux host with the native "
                    "x86-64 renderer. Use the native launcher with FEX-EMU, or use "
                    "--browser."
                )
                return None
            fex_executable = find_fex_executable()
            if fex_executable is None:
                message = format_fex_renderer_message()
                dtslogger.error(message)
                return None
            app_prefix = [fex_executable]
        elif is_arm64_windows_host(os_family):
            dtslogger.info(
                "Detected an ARM64 Windows host. The Windows Duckiematrix renderer "
                "is an x86-64 binary and will rely on Windows x64 emulation."
            )

    use_tailed_log_file = (
        os_family == "macos" and (
            should_run_host_renderer_only() or getattr(parsed, "trace", False)
            or getattr(parsed, "metal_capture", False)
        )
    )

    renderer_log_path = create_renderer_log_path(
        os_family,
        use_tailed_log_file=use_tailed_log_file,
    )
    if renderer_log_path is None:
        renderer_log_target = "/dev/stdout" if os_family == "linux" else "-"
    else:
        renderer_log_target = str(renderer_log_path)
    app_config = ["-logFile", renderer_log_target]
    if parsed.force_opengl:
        app_config += ["-force-opengl"]
    elif parsed.force_vulkan:
        app_config += ["-force-vulkan"]
    elif getattr(parsed, "metal_capture", False):
        app_config += ["-force-metal"]
    else:
        if os_family != "windows" and not getattr(parsed, "trace", False):
            app_config += ["-force-vulkan"]
    if delegated_engine_host is not None:
        app_config += ["--engine-hostname", delegated_engine_host]
    _ep, _ewp = renderer_control_ports(parsed)
    if _ep is not None:
        app_config += ["--engine-control-port", str(_ep)]
    if _ewp is not None:
        app_config += ["--engine-ws-control-port", str(_ewp)]
    if parsed.renderer_id is not None:
        app_config += ["--renderer-id", f"renderer_{parsed.renderer_id}"]
    if parsed.renderer_key is not None:
        app_config += ["--renderer-key", parsed.renderer_key]
    if parsed.no_tutorial:
        app_config += ["--no-tutorial"]
    elif not parsed.no_spectator_cameras:
        app_config += ["--tutorial"]
    if getattr(parsed, "no_cinematics", False):
        app_config += ["--no-cinematics"]
    if parsed.profiler:
        app_config += ["--profiler"]
    elif parsed.live_profiler:
        app_config += ["--live-profiler"]
    profiler_level = getattr(parsed, "profiler_level", None)
    if profiler_level is not None:
        app_config += ["--profiler-level", profiler_level]
    if getattr(parsed, "profiler_memory", False):
        app_config += ["--profiler-memory"]
    if getattr(parsed, "profiler_no_table", False):
        app_config += ["--profiler-no-table"]
    profiler_report_interval = getattr(parsed, "profiler_report_interval", None)
    if profiler_report_interval is not None:
        app_config += ["--profiler-report-interval", str(profiler_report_interval)]
    if parsed.on_top:
        app_config += ["--on-top"]
    if parsed.target_frame_rate is not None:
        app_config += ["--target-frame-rate", str(parsed.target_frame_rate)]
    if parsed.no_spectator_cameras:
        app_config += ["--no-spectator-cameras"]
    app_config += ["--token", shell.profile.secrets.dt_token]
    billboards_database = DTShellDatabase.open(DB_BILLBOARDS)
    billboard_names = shell.get_billboard_names(billboards_database)
    billboard = None
    world_billboards = None
    if billboard_names:
        billboard = shell.get_billboard(billboards_database, billboard_names)
        counter = Counter(billboard_names)
        if browser:
            world_billboards = _webgl_billboard_payload(billboards_database, counter)
        else:
            if billboard:
                app_config += ["--billboard", billboard]
            app_config += ["--billboards-path", billboards_database.yaml]
            app_config += ["--billboard-names", json.dumps(dict(counter))]
    dtslogger.info("Renderer configured!")
    return RendererLaunchConfiguration(
        app_bin=app_bin,
        app_config=app_config,
        app_path=app_path,
        app_prefix=app_prefix,
        os_family=os_family,
        renderer_log_path=renderer_log_path,
        screen_billboard=billboard,
        world_billboards=world_billboards,
    )

class DTCommand(DTCommandAbs):

    help = f'Runs the {APP_NAME} renderer'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        container_image = parsed.container_image
        host_renderer_only = should_run_host_renderer_only()
        delegate_renderer_to_host = (
            should_delegate_matrix_run()
            and not parsed.browser
            and not parsed.local
            and container_image is None
            and not parsed.xvfb
        )
        delegated_engine_host = resolve_delegated_engine_host(parsed.engine_hostname)
        if delegate_renderer_to_host:
            dtslogger.info("Configuring host-delegated native renderer...")
        # ---
        # check for conflicting arguments
        run_engine: bool = parsed.standalone and not host_renderer_only
        run_renderer: bool = True
        environments = getattr(parsed, "environments", 1)
        if (
            isinstance(environments, bool)
            or not isinstance(environments, int)
            or environments < 1
        ):
            dtslogger.error("--environments must be a positive integer.")
            return
        if environments > 1 and not parsed.standalone:
            dtslogger.error("--environments requires --standalone; "
                            "the Engine owns replication.")
            return
        if parsed.no_spectator_cameras and parsed.no_tutorial:
            dtslogger.error("You cannot use --no-spectator-cameras and --no-tutorial together.")
            return
        no_cinematics = getattr(parsed, "no_cinematics", False)
        # - map VS sandbox
        if parsed.sandbox and parsed.map is not None:
            dtslogger.error("Sandbox mode (--sandbox) and custom map (-m/--map) "
                            "cannot be used together.")
            return
        # - vulkan VS opengl
        if parsed.force_vulkan and parsed.force_opengl:
            dtslogger.error("You cannot use --force-vulkan and --force-opengl together.")
            return
        if parsed.profiler and parsed.live_profiler:
            dtslogger.error("You cannot use --profiler and --live-profiler together.")
            return
        profiler_level = getattr(parsed, "profiler_level", None)
        if profiler_level is not None and not (parsed.profiler or parsed.live_profiler):
            dtslogger.error("--profiler-level requires --profiler or --live-profiler.")
            return
        profiler_memory = getattr(parsed, "profiler_memory", False)
        profiler_no_table = getattr(parsed, "profiler_no_table", False)
        profiler_report_interval = getattr(parsed, "profiler_report_interval", None)
        if profiler_memory and not parsed.live_profiler:
            dtslogger.error("--profiler-memory requires --live-profiler.")
            return
        if (
            (profiler_no_table or profiler_report_interval is not None)
            and not parsed.live_profiler
        ):
            dtslogger.error("--profiler-no-table and --profiler-report-interval "
                            "require --live-profiler.")
            return
        if profiler_report_interval is not None and (
            isinstance(profiler_report_interval, bool)
            or not isinstance(profiler_report_interval, int)
            or profiler_report_interval <= 0
        ):
            dtslogger.error("--profiler-report-interval must be a positive "
                            "number of seconds.")
            return
        if parsed.browser and (profiler_memory or profiler_no_table):
            dtslogger.error("--profiler-memory and --profiler-no-table "
                            "require a native Renderer.")
            return
        # - links VS renderer-only
        if len(parsed.links) > 0 and not run_engine and not host_renderer_only:
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
        if parsed.embedded and not parsed.map:
            dtslogger.error("--embedded requires -m/--map.")
            return
        if run_engine and parsed.map == "":
            dtslogger.error("-m/--map cannot be empty.")
            return
        launch_picker = parsed.standalone and parsed.map is None and not parsed.sandbox
        select_map_at_start = run_engine and launch_picker
        forwarded_map_control = delegated_map_control() if host_renderer_only else None
        if host_renderer_only and launch_picker and not (forwarded_map_control and forwarded_map_control[2]):
            dtslogger.error("The host runner did not forward startup map selection. "
                            "Update the host runner or use --local, --browser, or an explicit --map.")
            return
        if select_map_at_start and not delegate_renderer_to_host:
            delegated_engine_host = parsed.engine_hostname
        # make sure the time step is only given in gym mode
        if parsed.delta_t is not None and not parsed.simulation:
            dtslogger.error("You can specify a --delta-t only when running with "
                            "--gym/--simulation.")
            return
        if parsed.shm_path:
            if not parsed.simulation:
                dtslogger.error("You cannot use --shm-path without --gym/--simulation.")
                return
            if not run_engine and not host_renderer_only:
                dtslogger.error("You cannot use --shm-path without -S/--standalone.")
                return
        # profiler
        if (parsed.profiler or parsed.live_profiler) and not run_engine and not host_renderer_only:
            dtslogger.error("Profiling requires -S/--standalone.")
            return
        if container_image and platform.system() != "Linux":
            dtslogger.error("You cannot use --container-image outside Linux.")
            return
        metal_capture = getattr(parsed, "metal_capture", False)
        if metal_capture:
            if parsed.browser or container_image is not None or parsed.xvfb:
                dtslogger.error("--metal-capture requires a native macOS Renderer, without --browser, --container-image, or --xvfb.")
                return
            if parsed.force_opengl or parsed.force_vulkan:
                dtslogger.error("--metal-capture uses Metal; do not force OpenGL or Vulkan.")
                return
            if not delegate_renderer_to_host and (parsed.os_family or get_os_family()) != "macos":
                dtslogger.error("--metal-capture requires a native macOS Renderer.")
                return
        trace_recording = None
        trace_interrupted = False
        trace_enabled = getattr(parsed, "trace", False)
        trace_export = getattr(parsed, "trace_export", False)
        trace_output = getattr(parsed, "trace_output", None)
        trace_duration = getattr(parsed, "trace_duration", TRACE_DURATION_DEFAULT)
        trace_window = getattr(parsed, "trace_window", None)
        trace_session = getattr(parsed, "trace_start_session", None)
        trace_settings = TraceSettings(
            template=getattr(parsed, "trace_template", None),
            performance_state=getattr(parsed, "trace_performance_state", None),
            waiting_threads=getattr(parsed, "trace_waiting_threads", False),
            kernel_callstacks=getattr(parsed, "trace_kernel_callstacks", False),
            context_switch_sampling=getattr(parsed, "trace_context_switch_sampling", False),
        )
        if not trace_enabled and (
            trace_output is not None or trace_window is not None
            or trace_duration != TRACE_DURATION_DEFAULT or trace_export or trace_session is not None
            or trace_settings.customized
        ):
            dtslogger.error("Trace control options require --trace.")
            return
        if trace_enabled:
            if parsed.browser or container_image is not None or parsed.xvfb:
                dtslogger.error("--trace requires a native macOS Renderer, without --browser, --container-image, or --xvfb.")
                return
            if parsed.force_opengl or parsed.force_vulkan:
                dtslogger.error("--trace uses Metal; do not force OpenGL or Vulkan.")
                return
            try:
                trace_settings.validate()
                trace_duration, trace_window = trace_limits(trace_duration, trace_window)
                trace_session = trace_start_session(trace_session)
                if trace_session is not None and not parsed.live_profiler:
                    raise ValueError("--trace-start-session requires --live-profiler to observe Renderer sessions.")
                if not delegate_renderer_to_host:
                    if (parsed.os_family or get_os_family()) != "macos":
                        raise ValueError("--trace requires a native macOS Renderer.")
                    if host_renderer_only:
                        trace_output = os.environ.get(TRACE_OUTPUT_ENV)
                        if trace_output is None:
                            raise ValueError("Delegated --trace requires an updated shared-queue host runner.")
                    output_path = resolve_trace_output(trace_output, export=trace_export)
                    trace_recording = RendererTrace(
                        output_path, trace_duration, trace_window, export=trace_export,
                        start_session=trace_session, settings=trace_settings,
                    )
                    dtslogger.info(f"Renderer trace output: {output_path}")
                    if trace_session is not None:
                        dtslogger.info(f"Waiting for Renderer session >= {trace_session} before Instruments recording.")
                    if trace_duration == -1 and trace_window == -1:
                        dtslogger.warning("Tracing the entire Renderer lifetime without a history cap can use substantial disk space.")
            except (ValueError, OSError) as error:
                dtslogger.error(str(error))
                return
        # configure the engine if in standalone
        engine: Optional[MatrixEngine] = None
        if run_engine:
            engine = shell.include.matrix.engine.run.make_engine(
                shell, parsed, use_defaults=True, defer_map=select_map_at_start,
            )
            if engine is None or engine.config is None:
                return
            if select_map_at_start and not can_manage_local_engine(parsed, engine.config):
                dtslogger.error("Startup map selection requires a local Docker Engine and a local "
                                "Renderer with matching control ports (and a loopback --host in browser mode). "
                                "Use these settings, or supply a map with --map or --sandbox.")
                return
            # ENGINE is now configured
            # -------------------------------------------------------------------------------------

        # configure renderer
        app_path: Optional[str] = None
        app_config: list = []
        app_prefix: list = []
        app_bin: Optional[str] = None
        browser = parsed.browser
        os_family = parsed.os_family or get_os_family()
        renderer: Optional[subprocess.Popen] = None
        terminate_renderer: Optional[Callable] = None
        renderer_stream: Optional[BinaryIO] = None
        renderer_log_path: Optional[Path] = None
        renderer_log_stop_event: Optional[threading.Event] = None
        renderer_shutdown_event: Optional[threading.Event] = None
        renderer_log_thread: Optional[Thread] = None
        renderer_configuration: Optional[RendererLaunchConfiguration] = None
        if run_renderer and not delegate_renderer_to_host:
            renderer_configuration = configure_renderer_launch(
                shell,
                parsed,
                delegated_engine_host,
            )
            if renderer_configuration is None:
                return
            app_path = renderer_configuration.app_path
            app_config = renderer_configuration.app_config
            app_prefix = renderer_configuration.app_prefix
            app_bin = renderer_configuration.app_bin
            os_family = renderer_configuration.os_family
            renderer_log_path = renderer_configuration.renderer_log_path

        profiler_output = None
        map_control: Optional[MapControl] = None
        renderer_server: Optional[HTTPServer] = None
        server_thread: Optional[Thread] = None
        if parsed.live_profiler and not host_renderer_only:
            from utils.matrix_profiler import LiveProfilerOutput

            profiler_output = LiveProfilerOutput()
            profiler_output.start()
        # run
        try:
            # - engine
            if run_engine:
                if not parsed.no_pull:
                    engine.pull()
                if not select_map_at_start:
                    engine.start()

            # - renderer
            if run_renderer:
                # wait for the engine (if any) to become healthy
                if run_engine and not select_map_at_start:
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

                if engine is not None and engine.config is not None and can_manage_local_engine(parsed, engine.config):
                    try:
                        map_control = MapControl(engine, Path.cwd())
                        if not browser:
                            renderer_server = MapControlHTTPServer(map_control)
                            server_thread = Thread(target=renderer_server.serve_forever, daemon=True)
                            server_thread.start()
                    except (DockerException, RequestException, OSError, ValueError) as error:
                        if select_map_at_start:
                            dtslogger.error("Could not open startup map selection: %s", error)
                            return
                        dtslogger.warning("Map selection is unavailable for this launch: %s", error)
                        map_control = None

                if delegate_renderer_to_host:
                    dtslogger.info("Launching the native renderer on the host...")
                    host_args = list(args)
                    for flag, enabled in (
                        ("--no-tutorial", parsed.no_tutorial),
                        ("--no-cinematics", no_cinematics),
                    ):
                        if enabled and flag not in host_args:
                            host_args.append(flag)
                    capability = None
                    if map_control is not None:
                        capability = f"{renderer_server.server_port}:{map_control.token}:{int(select_map_at_start)}"
                    try:
                        exit_code = delegate_matrix_run_to_host(
                            host_args,
                            engine_host=delegated_engine_host,
                            renderer_only=True,
                            map_control=capability,
                        )
                    except HostRunnerError as error:
                        dtslogger.error(str(error))
                    else:
                        if exit_code != 0:
                            dtslogger.error(f"Host-side 'dts matrix run' exited with code {exit_code}.")
                    return

                if browser:
                    dtslogger.info("Launching Renderer in browser...")
                    os.chdir(app_path)
                    host = parsed.host
                    server_configuration = create_browser_http_server(host, parsed.port)
                    renderer_server = server_configuration.server
                    renderer_server.map_control = map_control
                    web_host = format_http_host(server_configuration.display_host)
                    renderer_server.map_control_host = (
                        web_host if server_configuration.port == 80 else f"{web_host}:{server_configuration.port}"
                    )
                    server_thread = Thread(target=renderer_server.serve_forever, daemon=True)
                    url = f"http://{web_host}:{server_configuration.port}/?"
                    if parsed.renderer_id is not None:
                        url += f"renderer-id={parsed.renderer_id}&"
                    if parsed.renderer_key is not None:
                        url += f"renderer-key={parsed.renderer_key}&"
                    if parsed.engine_hostname is not None:
                        url += f"engine-hostname={quote(parsed.engine_hostname, safe='')}&"
                    _ep, _ewp = renderer_control_ports(parsed)
                    if _ep is not None:
                        url += f"engine-control-port={_ep}&"
                    if _ewp is not None:
                        url += f"engine-ws-control-port={_ewp}&"
                    if parsed.port_offset:
                        url += f"port-offset={parsed.port_offset}&"
                    if parsed.target_frame_rate is not None:
                        url += f"target-frame-rate={parsed.target_frame_rate}&"
                    url += f"no-spectator-cameras={'true' if parsed.no_spectator_cameras else 'false'}&"
                    if parsed.profiler:
                        url += "profiler=true&"
                    elif parsed.live_profiler:
                        url += "live-profiler=true&"
                    if profiler_level is not None:
                        url += f"profiler-level={profiler_level}&"
                    if profiler_report_interval is not None:
                        url += f"profiler-report-interval={profiler_report_interval}&"
                    url += f"tutorial={'true' if not parsed.no_tutorial and not parsed.no_spectator_cameras else 'false'}&"
                    if no_cinematics:
                        url += "no-cinematics=true&"
                    if select_map_at_start:
                        url += "select-map=true&"
                    if renderer_configuration.screen_billboard:
                        url += f"billboard={quote(renderer_configuration.screen_billboard, safe='')}&"
                    token = shell.profile.secrets.dt_token
                    url += f"token={token}/"
                    fragment = []
                    if renderer_configuration.world_billboards:
                        # Fragments are available to the player without growing the HTTP request.
                        fragment.append(f"billboards={quote(renderer_configuration.world_billboards, safe='')}")
                    if map_control is not None:
                        fragment.append(f"map-token={map_control.token}")
                    if fragment:
                        url += "#" + "&".join(fragment)
                    server_thread.start()
                    browser_opened = False
                    if os_family == "windows" and hasattr(os, "startfile"):
                        try:
                            os.startfile(url)
                            browser_opened = True
                        except (OSError, NotImplementedError) as error:
                            dtslogger.debug(
                                f"Could not open the browser through Windows ({type(error).__name__})."
                            )
                    if not browser_opened:
                        browser_opened = open_browser_url(url)
                    if not browser_opened:
                        dtslogger.warning("Could not open browser.")
                    formatted_url = _format_navigation_url(url, token)
                    dtslogger.info(f"Navigate to {formatted_url}.")
                    # wait for the engine to terminate
                    if map_control is not None:
                        if not map_control.wait_for_engine():
                            # Keep serving the player after a requested stop (or a failed map switch).
                            server_thread.join()
                    elif run_engine:
                        engine.join()
                    else:
                        server_thread.join()
                else:
                    # run the app
                    if select_map_at_start or (forwarded_map_control is not None and forwarded_map_control[2]):
                        app_config += ["--select-map"]
                    os.makedirs("/tmp/Duckietown/Duckiematrix", exist_ok=True)
                    dtslogger.info("Launching Renderer...")
                    time.sleep(2)
                    if container_image:
                        container_cmd, container_name = _build_renderer_container_command(
                            app_bin,
                            app_config,
                            container_image,
                        )
                        dtslogger.info(f"Launching Renderer container ({container_name})...")
                        dtslogger.debug(f"$ > {container_cmd}")
                        renderer, renderer_stream = launch_renderer_process(
                            container_cmd,
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
                            if host_renderer_only and forwarded_map_control is None and not (trace_enabled or metal_capture):
                                app_cmd = build_macos_app_command(app_path, app_config)
                            else:
                                try:
                                    app_path_list = [get_macos_app_executable(app_path)]
                                except FileNotFoundError as error:
                                    error_string = str(error)
                                    dtslogger.error(error_string)
                                    return
                                app_cmd = app_path_list + app_config
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
                        renderer_environment = None
                        if metal_capture:
                            renderer_environment = dict(os.environ, MTL_CAPTURE_ENABLED="1")
                            dtslogger.info("Metal GPU frame capture enabled for this Renderer process.")
                        control_address = forwarded_map_control
                        if map_control is not None:
                            control_address = (str(renderer_server.server_port), map_control.token, select_map_at_start)
                        if control_address is not None:
                            renderer_environment = renderer_environment or dict(os.environ)
                            renderer_environment[MAP_CONTROL_PORT_ENV], renderer_environment[MAP_CONTROL_TOKEN_ENV], _ = control_address
                            if os_family == "windows" and "WSL_DISTRO_NAME" in os.environ:
                                renderer_environment["WSLENV"] = ":".join(filter(None, (
                                    renderer_environment.get("WSLENV"), MAP_CONTROL_PORT_ENV, MAP_CONTROL_TOKEN_ENV,
                                )))
                        try:
                            renderer, renderer_stream = launch_renderer_process(
                                app_cmd,
                                env=renderer_environment,
                            )
                        except OSError as error:
                            if error.errno == errno.ENOEXEC:
                                show_exec_format_error(os_family, app_path)
                                return
                            raise
                        renderer_log_stop_event, renderer_shutdown_event, renderer_log_thread = start_renderer_log_tailer(
                            renderer_log_path,
                            parsed.verbose or parsed.profiler or parsed.live_profiler or trace_enabled or metal_capture,
                            on_line=trace_recording.observe_renderer_line if trace_recording is not None else None,
                        )
                        # this is how we terminate the renderer

                        def terminate_renderer(*_):
                            # noinspection PyBroadException
                            try:
                                if trace_enabled or metal_capture:
                                    renderer.terminate()
                                    if not wait_for_process_exit(renderer, RENDERER_FORCE_KILL_WAIT_SECONDS):
                                        renderer.kill()
                                        wait_for_process_exit(renderer, RENDERER_FORCE_KILL_WAIT_SECONDS)
                                elif os_family == "windows":
                                    # For Windows binaries in WSL, kill by process name since WSL PIDs don't map to Windows
                                    app_basename = os.path.basename(app_path)
                                    subprocess.run(
                                        ["taskkill.exe", "/F", "/IM", app_basename],
                                        stderr=subprocess.DEVNULL,
                                    )
                                elif os_family == "macos" and host_renderer_only and forwarded_map_control is None:
                                    terminate_macos_app(app_path)
                                else:
                                    renderer.kill()
                            except Exception:
                                pass

                    if trace_recording is not None:
                        trace_recording.start(renderer.pid)
                    # wait for the renderer to terminate
                    if renderer_stream is None:
                        raise RuntimeError("Renderer stream was not initialized.")
                    join_renderer(
                        renderer,
                        renderer_stream,
                        parsed.verbose or parsed.profiler or parsed.live_profiler,
                        renderer_shutdown_event,
                        terminate_renderer,
                    )
            else:
                # wait for the engine to terminate
                engine.join()

        except KeyboardInterrupt:
            trace_interrupted = True
            raise
        finally:
            try:
                if renderer_server is not None:
                    if server_thread is not None and server_thread.is_alive():
                        renderer_server.shutdown()
                    renderer_server.server_close()
                if map_control is not None:
                    map_control.close()
                if run_engine:
                    engine.stop()
                if (
                    run_renderer
                    and terminate_renderer is not None
                    and (
                        (os_family == "macos" and host_renderer_only and forwarded_map_control is None)
                        or process_is_running(renderer)
                    )
                ):
                    terminate_renderer()
                stop_renderer_log_tailer(
                    renderer_log_stop_event,
                    renderer_log_thread,
                )
                remove_renderer_log_file(renderer_log_path)
            finally:
                try:
                    if trace_recording is not None:
                        trace_recording.finish(interrupted=trace_interrupted)
                        if trace_recording.output.is_dir():
                            dtslogger.info(f"Renderer trace saved: {trace_recording.output}")
                finally:
                    if profiler_output is not None:
                        profiler_output.stop()

    @staticmethod
    def complete(shell, word, line):
        return []


def join_renderer(
    process: subprocess.Popen,
    stream: BinaryIO,
    verbose: bool = False,
    shutdown_event: Optional[threading.Event] = None,
    terminate_process: Optional[Callable] = None,
):
    output_reader = None
    try:
        if shutdown_event is not None:
            output_reader = Thread(
                target=forward_renderer_shutdown_output,
                args=(stream, False),
                daemon=True,
            )
            output_reader.start()
            wait_for_tailed_renderer_shutdown(
                process,
                shutdown_event,
                terminate_process,
            )
            return
        while True:
            line = read_renderer_stream_line(stream)
            if not line:
                break
            line_text = line.decode("utf-8", errors="replace")
            if EXTERNAL_SHUTDOWN_REQUEST in line_text:
                process.kill()
                wait_for_process_exit(process, RENDERER_FORCE_KILL_WAIT_SECONDS)
                return
            if verbose:
                print(line_text, end="")
    except KeyboardInterrupt:
        if shutdown_event is None:
            output_reader = Thread(
                target=forward_renderer_shutdown_output,
                args=(stream, verbose),
                daemon=True,
            )
            output_reader.start()
        if terminate_process is not None:
            terminate_process()
        else:
            process.terminate()
        if not wait_for_process_exit(process, RENDERER_FORCE_KILL_WAIT_SECONDS):
            process.kill()
            wait_for_process_exit(process, RENDERER_FORCE_KILL_WAIT_SECONDS)
        raise
    finally:
        if output_reader is not None:
            output_reader.join(timeout=RENDERER_FORCE_KILL_WAIT_SECONDS)
        stream.close()


def forward_renderer_shutdown_output(stream: BinaryIO, verbose: bool) -> None:
    try:
        while True:
            line = read_renderer_stream_line(stream)
            if not line:
                return
            if verbose:
                write_renderer_output(line.decode("utf-8", errors="replace"))
    except (OSError, ValueError):
        return


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


def build_macos_app_command(app_path: str, app_config: list[str]) -> list[str]:
    return ["open", "-n", "-W", app_path, "--args", *app_config]


def terminate_macos_app(app_path: str) -> None:
    executable_path = get_macos_app_executable(app_path)
    executable_name = os.path.basename(executable_path)
    exited = False
    deadline = time.monotonic() + RENDERER_MACOS_SHUTDOWN_TIMEOUT_SECONDS
    try:
        subprocess.run(
            [
                "osascript",
                "-e", "on run argv",
                "-e", "if application (item 1 of argv) is running then",
                "-e", "tell application (item 1 of argv) to quit",
                "-e", "end if",
                "-e", "end run",
                app_path,
            ],
            check=False,
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            timeout=RENDERER_MACOS_SHUTDOWN_TIMEOUT_SECONDS,
        )
        while time.monotonic() < deadline:
            running = subprocess.run(
                ["pgrep", "-x", executable_name],
                check=False,
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                timeout=RENDERER_EXIT_POLL_SECONDS,
            )
            if running.returncode == 1:
                exited = True
                return
            if running.returncode != 0:
                break
            time.sleep(RENDERER_EXIT_POLL_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        pass
    finally:
        if not exited:
            subprocess.run(
                ["pkill", "-KILL", "-x", executable_name],
                check=False,
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                timeout=RENDERER_MACOS_SHUTDOWN_TIMEOUT_SECONDS,
            )


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
