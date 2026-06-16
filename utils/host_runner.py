import json
import os
import sys
from typing import Dict, Iterable, Optional, Sequence
from urllib import error as urllib_error
from urllib import request as urllib_request


HOST_RUNNER_URL_ENV = "DTS_HOST_RUNNER_URL"
HOST_RUNNER_TOKEN_ENV = "DTS_HOST_RUNNER_TOKEN"
HOST_RUNNER_ACTIVE_ENV = "DTS_HOST_RUNNER_ACTIVE"
HOST_RUNNER_TIMEOUT_ENV = "DTS_HOST_RUNNER_TIMEOUT"
HOST_RUNNER_EXIT_CODE_PREFIX = "===DTS_HOST_RUNNER_EXIT_CODE==="
DEFAULT_FORWARDED_ENVIRONMENT_KEYS = (
    "DOCKER_REGISTRY",
    "DTSHELL_COMMANDS",
)


class HostRunnerError(RuntimeError):

    def __init__(self, message: str):
        super().__init__(message)


def host_runner_url() -> Optional[str]:
    host_runner_url_env = os.environ.get(HOST_RUNNER_URL_ENV, "")
    return host_runner_url_env.strip() or None


def should_delegate_to_host() -> bool:
    return host_runner_url() is not None and os.environ.get(HOST_RUNNER_ACTIVE_ENV) != "1"


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

    url = host_runner_url()
    if url is None:
        raise HostRunnerError(
            f"{HOST_RUNNER_URL_ENV} is not configured, so host delegation is unavailable."
        )

    timeout_raw = os.environ.get(HOST_RUNNER_TIMEOUT_ENV, "86400")
    try:
        timeout = float(timeout_raw)
    except ValueError as error:
        raise HostRunnerError(
            f"{HOST_RUNNER_TIMEOUT_ENV} must be numeric; got {timeout_raw!r}."
        ) from error

    payload = {
        "command": list(command),
        "argv": list(args),
        "cwd": os.getcwd(),
        "env": _collect_forwarded_environment(
            forwarded_environment_keys,
            extra_env=extra_env,
        ),
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

    host_runner_token_env = os.environ.get(HOST_RUNNER_TOKEN_ENV, "")
    token = host_runner_token_env.strip()
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
