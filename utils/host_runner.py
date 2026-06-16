import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib import parse as urllib_parse


HOST_RUNNER_URL_ENV = "DTS_HOST_RUNNER_URL"
HOST_RUNNER_TOKEN_ENV = "DTS_HOST_RUNNER_TOKEN"
HOST_RUNNER_ACTIVE_ENV = "DTS_HOST_RUNNER_ACTIVE"
HOST_RUNNER_TIMEOUT_ENV = "DTS_HOST_RUNNER_TIMEOUT"
HOST_RUNNER_EXIT_CODE_PREFIX = "===DTS_HOST_RUNNER_EXIT_CODE==="
HOST_RUNNER_REQUESTS_DIR_ENV = "DTS_HOST_RUNNER_REQUESTS_DIR"
HOST_RUNNER_HEALTH_PATH = "/healthz"
HOST_RUNNER_HEALTH_RESPONSE = "duckietown-host-runner:ok"
HOST_RUNNER_HEALTH_TIMEOUT_SECONDS = 5.0
HOST_RUNNER_REQUEST_CLAIM_TIMEOUT_SECONDS = 2.0
WORKSPACE_HOST_RUNNER_ENV_FILE = Path("/home/ubuntu/duckietown/workspace/.devcontainer/.env")
DEFAULT_HOST_RUNNER_REQUESTS_DIR = str(
    WORKSPACE_HOST_RUNNER_ENV_FILE.parent / ".duckietown_host_runner_requests"
)
REQUEST_FILE_SUFFIX = ".request.json"
STREAM_FILE_SUFFIX = ".stream"
DEFAULT_FORWARDED_ENVIRONMENT_KEYS = (
    "DOCKER_REGISTRY",
    "DTSHELL_COMMANDS",
)


class HostRunnerError(RuntimeError):

    def __init__(self, message: str):
        super().__init__(message)


def _read_workspace_host_runner_env() -> dict[str, str]:
    if not WORKSPACE_HOST_RUNNER_ENV_FILE.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in WORKSPACE_HOST_RUNNER_ENV_FILE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _host_runner_env_candidates() -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []

    runtime_candidate = {
        HOST_RUNNER_URL_ENV: os.environ.get(HOST_RUNNER_URL_ENV, "").strip(),
        HOST_RUNNER_TOKEN_ENV: os.environ.get(HOST_RUNNER_TOKEN_ENV, "").strip(),
        HOST_RUNNER_TIMEOUT_ENV: os.environ.get(HOST_RUNNER_TIMEOUT_ENV, "").strip(),
        HOST_RUNNER_REQUESTS_DIR_ENV: os.environ.get(HOST_RUNNER_REQUESTS_DIR_ENV, "").strip(),
    }
    if runtime_candidate[HOST_RUNNER_URL_ENV] and not runtime_candidate[HOST_RUNNER_REQUESTS_DIR_ENV]:
        runtime_candidate[HOST_RUNNER_REQUESTS_DIR_ENV] = DEFAULT_HOST_RUNNER_REQUESTS_DIR
    if runtime_candidate[HOST_RUNNER_URL_ENV] or runtime_candidate[HOST_RUNNER_REQUESTS_DIR_ENV]:
        candidates.append(runtime_candidate)

    workspace_values = _read_workspace_host_runner_env()
    workspace_candidate = {
        HOST_RUNNER_URL_ENV: workspace_values.get(HOST_RUNNER_URL_ENV, "").strip(),
        HOST_RUNNER_TOKEN_ENV: workspace_values.get(HOST_RUNNER_TOKEN_ENV, "").strip(),
        HOST_RUNNER_TIMEOUT_ENV: workspace_values.get(HOST_RUNNER_TIMEOUT_ENV, "").strip(),
        HOST_RUNNER_REQUESTS_DIR_ENV: workspace_values.get(HOST_RUNNER_REQUESTS_DIR_ENV, "").strip(),
    }
    if workspace_candidate[HOST_RUNNER_URL_ENV] and not workspace_candidate[HOST_RUNNER_REQUESTS_DIR_ENV]:
        workspace_candidate[HOST_RUNNER_REQUESTS_DIR_ENV] = DEFAULT_HOST_RUNNER_REQUESTS_DIR
    if (workspace_candidate[HOST_RUNNER_URL_ENV] or workspace_candidate[HOST_RUNNER_REQUESTS_DIR_ENV]) and workspace_candidate not in candidates:
        candidates.append(workspace_candidate)

    return candidates


def _host_runner_value(name: str) -> str:
    runtime_value = os.environ.get(name, "").strip()
    if runtime_value:
        return runtime_value

    workspace_values = _read_workspace_host_runner_env()
    return workspace_values.get(name, "").strip()


def host_runner_url() -> Optional[str]:
    return _host_runner_value(HOST_RUNNER_URL_ENV) or None


def host_runner_requests_dir() -> Optional[str]:
    return _host_runner_value(HOST_RUNNER_REQUESTS_DIR_ENV) or DEFAULT_HOST_RUNNER_REQUESTS_DIR


def should_delegate_to_host() -> bool:
    return bool(_host_runner_env_candidates()) and os.environ.get(HOST_RUNNER_ACTIVE_ENV) != "1"


def _host_runner_health_url(url: str) -> str:
    parsed = urllib_parse.urlsplit(url)
    return urllib_parse.urlunsplit(
        (parsed.scheme, parsed.netloc, HOST_RUNNER_HEALTH_PATH, "", "")
    )


def _assert_host_runner_healthy(url: str) -> None:
    health_url = _host_runner_health_url(url)
    request = urllib_request.Request(health_url, method="GET")

    try:
        with urllib_request.urlopen(request, timeout=HOST_RUNNER_HEALTH_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace").strip()
            if response.status != 200 or body != HOST_RUNNER_HEALTH_RESPONSE:
                raise HostRunnerError(
                    f"Host runner at {url} failed health check {health_url}: "
                    f"HTTP {response.status} body {body!r}."
                )
    except urllib_error.URLError as error:
        raise HostRunnerError(
            f"Host runner at {url} failed health check {health_url}: {error.reason}."
        ) from error
    except TimeoutError as error:
        raise HostRunnerError(
            f"Host runner at {url} failed health check {health_url}: timed out after "
            f"{HOST_RUNNER_HEALTH_TIMEOUT_SECONDS:g}s."
        ) from error


def _resolve_host_runner_endpoint(verbose: bool = False) -> tuple[str, str, str]:
    candidates = _host_runner_env_candidates()
    if not candidates:
        raise HostRunnerError(
            f"{HOST_RUNNER_URL_ENV} is not configured, so host delegation is unavailable."
        )

    failures: list[str] = []
    for candidate in candidates:
        url = candidate[HOST_RUNNER_URL_ENV]
        token = candidate[HOST_RUNNER_TOKEN_ENV]
        timeout_raw = candidate[HOST_RUNNER_TIMEOUT_ENV] or "86400"
        try:
            timeout = float(timeout_raw)
        except ValueError as error:
            raise HostRunnerError(
                f"{HOST_RUNNER_TIMEOUT_ENV} must be numeric; got {timeout_raw!r}."
            ) from error

        if verbose:
            sys.stdout.write(f"[duckietown-host-runner-client] trying: {url}\n")
            sys.stdout.flush()

        try:
            _assert_host_runner_healthy(url)
            return url, token, str(timeout)
        except HostRunnerError as error:
            failures.append(str(error))

    joined_failures = " | ".join(failures)
    raise HostRunnerError(joined_failures)


def _resolve_host_runner_requests_dir(verbose: bool = False) -> Optional[tuple[str, float]]:
    candidates = _host_runner_env_candidates()
    for candidate in candidates:
        requests_dir = candidate[HOST_RUNNER_REQUESTS_DIR_ENV]
        if not requests_dir:
            continue
        timeout_raw = candidate[HOST_RUNNER_TIMEOUT_ENV] or "86400"
        try:
            timeout = float(timeout_raw)
        except ValueError as error:
            raise HostRunnerError(
                f"{HOST_RUNNER_TIMEOUT_ENV} must be numeric; got {timeout_raw!r}."
            ) from error
        if verbose:
            sys.stdout.write(f"[duckietown-host-runner-client] trying requests_dir: {requests_dir}\n")
            sys.stdout.flush()
        return requests_dir, timeout
    return None


def _delegate_command_via_requests_dir(
    requests_dir: str,
    payload: dict,
    *,
    timeout: float,
) -> int:
    requests_path = Path(requests_dir)
    requests_path.mkdir(parents=True, exist_ok=True)

    request_id = uuid.uuid4().hex
    request_file = requests_path / f"{request_id}{REQUEST_FILE_SUFFIX}"
    stream_file = requests_path / f"{request_id}{STREAM_FILE_SUFFIX}"

    request_file.write_text(json.dumps(payload))

    deadline = time.monotonic() + timeout
    claim_deadline = time.monotonic() + min(timeout, HOST_RUNNER_REQUEST_CLAIM_TIMEOUT_SECONDS)
    offset = 0
    buffered = ""

    while time.monotonic() < deadline:
        if time.monotonic() >= claim_deadline and request_file.exists() and not stream_file.exists():
            try:
                request_file.unlink()
            except FileNotFoundError:
                pass
            raise HostRunnerError(
                "Host runner did not claim the queued request within "
                f"{HOST_RUNNER_REQUEST_CLAIM_TIMEOUT_SECONDS:g}s. This usually means "
                f"{requests_dir} is not actually shared with the host, or the host-side "
                "duckietown_host_runner.py is still an older copy without request-queue support."
            )

        if stream_file.exists():
            with stream_file.open("rb") as stream:
                stream.seek(offset)
                chunk = stream.read()
                offset += len(chunk)
            if chunk:
                text = chunk.decode("utf-8", errors="replace")
                buffered += text
                while "\n" in buffered:
                    line, buffered = buffered.split("\n", 1)
                    line = line + "\n"
                    if line.startswith(HOST_RUNNER_EXIT_CODE_PREFIX):
                        raw_exit_code = line[len(HOST_RUNNER_EXIT_CODE_PREFIX):].strip()
                        try:
                            return int(raw_exit_code)
                        finally:
                            try:
                                request_file.unlink()
                            except FileNotFoundError:
                                pass
                    sys.stdout.write(line)
                    sys.stdout.flush()
        time.sleep(0.1)

    raise HostRunnerError(
        f"Host runner request via {requests_dir} timed out after {timeout:g}s."
    )


def _collect_forwarded_environment(
    forwarded_environment_keys: Sequence[str],
    extra_env: Optional[Dict[str, str]] = None,
) -> dict:
    forwarded = {}
    for key in forwarded_environment_keys:
        value = os.environ.get(key)
        if value:
            forwarded[key] = value
    if extra_env:
        for key, value in extra_env.items():
            if isinstance(key, str) and isinstance(value, str) and value:
                forwarded[key] = value
    return forwarded


def delegate_command_to_host(
    command: Sequence[str],
    args: Iterable[str],
    *,
    forwarded_environment_keys: Sequence[str] = DEFAULT_FORWARDED_ENVIRONMENT_KEYS,
    extra_env: Optional[Dict[str, str]] = None,
) -> int:
    if not command or not all(isinstance(part, str) and part for part in command):
        raise HostRunnerError(
            "Host command path must be a non-empty sequence of strings."
        )

    args_list = list(args)
    forwarded_env = _collect_forwarded_environment(
        forwarded_environment_keys,
        extra_env=extra_env,
    )
    emit_client_context = "--verbose" in args_list or "-vv" in args_list

    resolved_requests_dir = _resolve_host_runner_requests_dir(verbose=emit_client_context)
    if resolved_requests_dir is not None:
        requests_dir, timeout = resolved_requests_dir
        if emit_client_context:
            sys.stdout.write(f"[duckietown-host-runner-client] requests_dir: {requests_dir}\n")
            sys.stdout.write(f"[duckietown-host-runner-client] cwd: {os.getcwd()}\n")
            if forwarded_env.get("DTSHELL_COMMANDS"):
                sys.stdout.write(
                    "[duckietown-host-runner-client] "
                    f"DTSHELL_COMMANDS={forwarded_env['DTSHELL_COMMANDS']}\n"
                )
            sys.stdout.flush()

        payload = {
            "command": list(command),
            "argv": args_list,
            "cwd": os.getcwd(),
            "env": forwarded_env,
        }
        return _delegate_command_via_requests_dir(
            requests_dir,
            payload,
            timeout=timeout,
        )

    url, token, timeout_raw = _resolve_host_runner_endpoint(verbose=emit_client_context)
    timeout = float(timeout_raw)
    if emit_client_context:
        sys.stdout.write(f"[duckietown-host-runner-client] url: {url}\n")
        sys.stdout.write(f"[duckietown-host-runner-client] cwd: {os.getcwd()}\n")
        if forwarded_env.get("DTSHELL_COMMANDS"):
            sys.stdout.write(
                "[duckietown-host-runner-client] "
                f"DTSHELL_COMMANDS={forwarded_env['DTSHELL_COMMANDS']}\n"
            )
        sys.stdout.flush()

    payload = {
        "command": list(command),
        "argv": args_list,
        "cwd": os.getcwd(),
        "env": forwarded_env,
    }

    json_string = json.dumps(payload)
    request = urllib_request.Request(
        url,
        data=json_string.encode("utf-8"),
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            exit_code = 0
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace")
                if line.startswith(HOST_RUNNER_EXIT_CODE_PREFIX):
                    line_segment = line[len(HOST_RUNNER_EXIT_CODE_PREFIX):]
                    raw_exit_code = line_segment.strip()
                    try:
                        exit_code = int(raw_exit_code)
                    except ValueError as error:
                        raise HostRunnerError(
                            "Host runner returned an invalid exit code marker "
                            f"{raw_exit_code!r}."
                        ) from error
                    continue
                sys.stdout.write(line)
                sys.stdout.flush()
            return exit_code
    except urllib_error.HTTPError as error:
        error_data = error.read()
        decoded_error_data = error_data.decode("utf-8", errors="replace")
        detail = decoded_error_data.strip()
        message = detail or error.reason
        raise HostRunnerError(
            f"Host runner request failed with HTTP {error.code}: {message}"
        ) from error
    except urllib_error.URLError as error:
        raise HostRunnerError(
            f"Could not reach host runner at {url}: {error.reason}"
        ) from error
