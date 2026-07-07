import os
import shlex
import subprocess
import sys
import tarfile
from datetime import datetime
from io import BytesIO

import docker as dockerpy

from utils.cli_utils import ensure_command_is_installed
from utils.networking_utils import is_local_virtual_robot_running
from utils.resolve import resolve_robot_host

SSH_USERNAME = "duckie"
STARTUP_LOG_FILES = ("/data/logs/first_boot_init.log", "/data/logs/this_boot_init.log")
STARTUP_LOG_POLL_INTERVAL_SECONDS = 0.1
STARTUP_LOG_COMPLETION_MARKERS = (
    "Setting up completed!",
    "Robot configured!",
)
STARTUP_LOG_STREAM_SCRIPT_CONTAINER_PATH = "/tmp/dts-startup-log-stream.py"
STARTUP_LOG_STREAM_SCRIPT_HOST_PATH = os.path.join(os.path.dirname(__file__), "startup_log_stream.py")


def stream_startup_logs(robot_name, startup_started_at=None):
    normalized_robot_name = robot_name[:-6] if robot_name.endswith(".local") else robot_name
    if is_local_virtual_robot_running(normalized_robot_name):
        stream_local_virtual_robot_startup_logs(
            normalized_robot_name,
            startup_started_at=startup_started_at,
        )
        return
    stream_remote_robot_startup_logs(robot_name, startup_started_at=startup_started_at)


def stream_local_virtual_robot_startup_logs(robot_name, startup_started_at=None, local_docker=None):
    docker_client = local_docker
    if docker_client is None:
        docker_client = dockerpy.from_env()
    container_name = f"dts-virtual-{robot_name}"
    container = docker_client.containers.get(container_name)
    if startup_started_at is None:
        startup_started_at = _get_container_started_at(container)
    try:
        if not _copy_startup_log_stream_script(container):
            return
        result = container.exec_run(
            [
                "python3",
                STARTUP_LOG_STREAM_SCRIPT_CONTAINER_PATH,
                "--startup-started-at",
                str(int(startup_started_at)),
                "--poll-interval",
                str(STARTUP_LOG_POLL_INTERVAL_SECONDS),
                *_completion_marker_args(),
                *STARTUP_LOG_FILES,
            ],
            stderr=False,
            stream=True,
        )
    except dockerpy.errors.APIError as error:
        raise RuntimeError(str(error)) from error
    output_stream = result.output if hasattr(result, "output") else result[1]
    if output_stream is None:
        return
    pending_fragment = ""
    for chunk in output_stream:
        normalized_chunk = _normalize_exec_output_chunk(chunk)
        if not normalized_chunk:
            continue
        pending_fragment = _log_output_lines(normalized_chunk, pending_fragment)
    if pending_fragment.strip():
        message = pending_fragment.rstrip()
        print(message)


def stream_remote_robot_startup_logs(robot_name, startup_started_at=None):
    hostname = resolve_robot_host(robot_name)
    if startup_started_at is None:
        startup_started_at = _get_remote_boot_started_at(hostname)
    ensure_command_is_installed("ssh", dependant="dts duckiebot startup_logs")
    remote_args = [
        "python3",
        "-",
        "--startup-started-at",
        str(int(startup_started_at)),
        "--poll-interval",
        str(STARTUP_LOG_POLL_INTERVAL_SECONDS),
        *_completion_marker_args(),
        *STARTUP_LOG_FILES,
    ]
    command = _ssh_remote_command(hostname, remote_args)
    with open(STARTUP_LOG_STREAM_SCRIPT_HOST_PATH, "rb") as script_file:
        result = subprocess.run(
            command,
            stdin=script_file,
            stdout=sys.stdout,
            stderr=sys.stderr,
            check=False,
        )
    if result.returncode not in [0, 130]:
        raise RuntimeError(
            f"Failed to stream startup logs from '{robot_name}' ({hostname}). "
            f"The ssh command exited with code {result.returncode}."
        )


def _copy_startup_log_stream_script(container):
    archive = BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        arcname = os.path.basename(STARTUP_LOG_STREAM_SCRIPT_CONTAINER_PATH)
        tar.add(STARTUP_LOG_STREAM_SCRIPT_HOST_PATH, arcname=arcname)
    archive.seek(0)
    path = os.path.dirname(STARTUP_LOG_STREAM_SCRIPT_CONTAINER_PATH)
    return container.put_archive(path=path, data=archive)


def _get_container_started_at(container):
    started_at = container.attrs.get("State", {}).get("StartedAt", "")
    if not started_at:
        raise RuntimeError(f"Unable to determine when container '{container.name}' started.")
    return int(datetime.fromisoformat(started_at.replace("Z", "+00:00")).timestamp())


def _get_remote_boot_started_at(hostname):
    ensure_command_is_installed("ssh", dependant="dts duckiebot startup_logs")
    remote_args = [
        "python3",
        "-c",
        "import time; print(int(time.time() - float(open('/proc/uptime').read().split()[0])))",
    ]
    command = _ssh_remote_command(hostname, remote_args)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"Failed to determine the boot time for robot host '{hostname}'. {stderr}"
        )
    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError(f"Robot host '{hostname}' returned an empty boot time.")
    try:
        return int(stdout)
    except ValueError as error:
        raise RuntimeError(
            f"Robot host '{hostname}' returned an invalid boot time: '{stdout}'."
        ) from error


def _log_output_lines(chunk, pending_fragment):
    lines = f"{pending_fragment}{chunk}".replace("\r", "\n")
    lines = lines.split("\n")
    pending_fragment = lines.pop()
    for line in lines:
        if line.strip():
            message = line.rstrip()
            print(message)
    return pending_fragment


def _normalize_exec_output_chunk(chunk):
    if isinstance(chunk, tuple):
        chunk = b"".join(part for part in chunk if part)
    if not chunk:
        return ""
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8", errors="replace")
    return str(chunk)


def _ssh_base_command(hostname):
    return [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        "-o",
        "ConnectTimeout=5",
        f"{SSH_USERNAME}@{hostname}",
    ]


def _ssh_remote_command(hostname, remote_args):
    command = _ssh_base_command(hostname)
    command.append(shlex.join(remote_args))
    return command


def _completion_marker_args():
    args = []
    for marker in STARTUP_LOG_COMPLETION_MARKERS:
        args.extend(["--completion-marker", marker])
    return args
