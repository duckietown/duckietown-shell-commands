import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Iterable, Optional
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


HOST_RUNNER_URL_ENV = "DTS_HOST_RUNNER_URL"
HOST_RUNNER_TOKEN_ENV = "DTS_HOST_RUNNER_TOKEN"
HOST_RUNNER_ACTIVE_ENV = "DTS_HOST_RUNNER_ACTIVE"
HOST_RUNNER_ENGINE_HOST_ENV = "DTS_HOST_RUNNER_ENGINE_HOST"
HOST_RUNNER_FRONTEND_URL_ENV = "DTS_HOST_RUNNER_FRONTEND_URL"
HOST_RUNNER_ENGINE_HOST_FORWARD_ENV = "HOST_DTS_HOST_RUNNER_ENGINE_HOST"
HOST_RUNNER_FRONTEND_URL_FORWARD_ENV = "HOST_DTS_HOST_RUNNER_FRONTEND_URL"
HOST_RUNNER_MATRIX_RENDERER_ONLY_ENV = "DTS_HOST_RUNNER_MATRIX_RENDERER_ONLY"
HOST_RUNNER_MATRIX_RENDERER_ONLY_FORWARD_ENV = "HOST_DTS_HOST_RUNNER_MATRIX_RENDERER_ONLY"
HOST_RUNNER_TIMEOUT_ENV = "DTS_HOST_RUNNER_TIMEOUT"
HOST_RUNNER_REQUESTS_DIR_ENV = "DTS_HOST_RUNNER_REQUESTS_DIR"
HOST_RUNNER_EXIT_CODE_PREFIXES = ("===DTS_HOST_RUNNER_EXIT_CODE===",)
HOST_RUNNER_HEALTH_PATH = "/healthz"
HOST_RUNNER_HEALTH_RESPONSE = "host-runner:ok"
HOST_RUNNER_HEALTH_TIMEOUT_SECONDS = 5
HOST_RUNNER_HEALTH_RETRY_WINDOW_SECONDS = 12
HOST_RUNNER_HEALTH_RETRY_INTERVAL_SECONDS = 0.5
HOST_RUNNER_REQUEST_CLAIM_TIMEOUT_SECONDS = 2
DEFAULT_HOST_RUNNER_REQUESTS_DIR_PATH = Path("/tmp/duckietown/host_runner_requests")
DEFAULT_HOST_RUNNER_REQUESTS_DIR = str(DEFAULT_HOST_RUNNER_REQUESTS_DIR_PATH)
HOST_RUNNER_SHARED_ENV_FILE_NAME = "host_runner_endpoint.env"
REQUEST_FILE_SUFFIX = ".request.json"
PROCESSING_FILE_SUFFIX = ".processing.json"
STREAM_FILE_SUFFIX = ".stream"
STREAM_CHUNK_FILE_SUFFIX = ".chunk"
CANCEL_FILE_SUFFIX = ".cancel"
HEARTBEAT_FILE_SUFFIX = ".heartbeat"
HOST_RUNNER_INTERRUPT_GRACE_SECONDS = 5
HOST_RUNNER_HEARTBEAT_INTERVAL_SECONDS = 1
FORWARDED_ENVIRONMENT_KEYS = (
    "HOST_DOCKER_REGISTRY",
    "HOST_DTSHELL_COMMANDS",
    HOST_RUNNER_ENGINE_HOST_FORWARD_ENV,
    HOST_RUNNER_FRONTEND_URL_FORWARD_ENV,
    HOST_RUNNER_MATRIX_RENDERER_ONLY_FORWARD_ENV,
)


class HostRunnerError(RuntimeError):

    def __init__(self, message: str):
        super().__init__(message)


class HostRunnerQueueUnavailableError(HostRunnerError):

    def __init__(self, message: str):
        super().__init__(message)


class HostRunnerQueueBlockedError(HostRunnerQueueUnavailableError):

    def __init__(self, message: str):
        super().__init__(message)


def _candidate_is_configured(candidate: dict[str, str]) -> bool:
    return bool(
        candidate[HOST_RUNNER_URL_ENV]
        or candidate[HOST_RUNNER_REQUESTS_DIR_ENV]
    )


def _runtime_host_runner_candidate() -> dict[str, str]:
    runtime_values = {key: str(value) for key, value in os.environ.items()}
    return _host_runner_candidate_from_values(runtime_values)


def _read_host_runner_env_file(env_file: Path) -> dict[str, str]:
    if not env_file.is_file():
        return {}

    values: dict[str, str] = {}
    env_text = env_file.read_text()
    env_lines = env_text.splitlines()
    for raw_line in env_lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _alias_value(values: dict[str, str], *names: str) -> str:
    for name in names:
        raw_value = values.get(name, "")
        value = raw_value.strip()
        if value:
            return value
    return ""


def _format_pending_processing_message(requests_path: Path) -> str:
    processing_paths = sorted(requests_path.glob(f"*{PROCESSING_FILE_SUFFIX}"))
    if not processing_paths:
        return (
            f"{requests_path} is not actually shared with the host, or the host runner "
            f"is not watching that directory."
        )
    processing_names = [path.name for path in processing_paths[:3]]
    processing_message = ", ".join(processing_names)
    if len(processing_paths) > 3:
        processing_message += ", ..."
    return (
        "the shared queue is visible, but the host runner already has a stuck or long-running "
        f"request: {processing_message}. Restart the host runner or clear the stale request."
    )


def _host_runner_candidate_from_values(values: dict[str, str]) -> dict[str, str]:
    candidate = {
        HOST_RUNNER_URL_ENV: _alias_value(values, HOST_RUNNER_URL_ENV),
        HOST_RUNNER_TOKEN_ENV: _alias_value(values, HOST_RUNNER_TOKEN_ENV),
        HOST_RUNNER_TIMEOUT_ENV: _alias_value(values, HOST_RUNNER_TIMEOUT_ENV),
        HOST_RUNNER_REQUESTS_DIR_ENV: _alias_value(
            values,
            HOST_RUNNER_REQUESTS_DIR_ENV,
        ),
    }
    if candidate[HOST_RUNNER_URL_ENV] and not candidate[HOST_RUNNER_REQUESTS_DIR_ENV]:
        candidate[HOST_RUNNER_REQUESTS_DIR_ENV] = DEFAULT_HOST_RUNNER_REQUESTS_DIR
    return candidate


def _shared_host_runner_env_files() -> list[Path]:
    runtime_requests_dir = os.environ.get(HOST_RUNNER_REQUESTS_DIR_ENV, "").strip()

    request_dirs = [DEFAULT_HOST_RUNNER_REQUESTS_DIR_PATH]
    if runtime_requests_dir:
        request_dirs.append(Path(runtime_requests_dir))

    shared_env_files: list[Path] = []
    seen_paths: set[str] = set()
    for request_dir in request_dirs:
        shared_env_file = request_dir / HOST_RUNNER_SHARED_ENV_FILE_NAME
        shared_env_path = str(shared_env_file)
        if shared_env_path in seen_paths:
            continue
        seen_paths.add(shared_env_path)
        shared_env_files.append(shared_env_file)
    return shared_env_files


def _host_runner_env_candidates() -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    runtime_candidate = _runtime_host_runner_candidate()

    for shared_env_file in _shared_host_runner_env_files():
        shared_values = _read_host_runner_env_file(shared_env_file)
        shared_candidate = _host_runner_candidate_from_values(shared_values)
        if not _candidate_is_configured(shared_candidate):
            continue
        if shared_candidate not in candidates:
            candidates.append(shared_candidate)

    if _candidate_is_configured(runtime_candidate) and runtime_candidate not in candidates:
        candidates.append(runtime_candidate)
    return candidates


def _host_runner_endpoint_candidates() -> list[tuple[str, str, float]]:
    endpoint_candidates: list[tuple[str, str, float]] = []
    for candidate in _host_runner_env_candidates():
        url = candidate[HOST_RUNNER_URL_ENV]
        if not url:
            continue
        token = candidate[HOST_RUNNER_TOKEN_ENV]
        timeout_raw = candidate[HOST_RUNNER_TIMEOUT_ENV] or "86400"
        try:
            timeout = float(timeout_raw)
        except ValueError as error:
            raise HostRunnerError(
                f"{HOST_RUNNER_TIMEOUT_ENV} must be numeric; got {timeout_raw!r}."
            ) from error
        endpoint_candidates.append((url, token, timeout))
    return endpoint_candidates


def host_runner_url() -> Optional[str]:
    for candidate in _host_runner_env_candidates():
        url = candidate[HOST_RUNNER_URL_ENV]
        if url:
            return url
    return None


def host_runner_engine_host() -> Optional[str]:
    runtime_values = {key: str(value) for key, value in os.environ.items()}
    runtime_host = _alias_value(runtime_values, HOST_RUNNER_ENGINE_HOST_ENV)
    if runtime_host:
        return runtime_host
    return None


def _is_native_host_platform() -> bool:
    return sys.platform.startswith(("darwin", "win32", "cygwin"))


def should_delegate_to_host() -> bool:
    active_value = os.environ.get(HOST_RUNNER_ACTIVE_ENV, "")
    host_runner_env_candidates_ = _host_runner_env_candidates()
    return (
        bool(host_runner_env_candidates_)
        and active_value != "1"
        and not _is_native_host_platform()
    )


def should_delegate_matrix_run() -> bool:
    return should_delegate_to_host()


def _host_runner_container_root() -> Path:
    file_path = Path(__file__)
    resolved_path = file_path.resolve()
    repo_root = resolved_path.parents[1]
    return repo_root.parent


def _host_runner_fallback_cwd() -> str:
    container_root_path = _host_runner_container_root()
    workspace_root_path = container_root_path / "workspace"
    if workspace_root_path.is_dir():
        return str(workspace_root_path)
    return str(container_root_path)


def _path_is_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _normalize_host_delegated_cwd(cwd: str) -> str:
    fallback_cwd = _host_runner_fallback_cwd()
    try:
        cwd_path = Path(cwd).resolve(strict=True)
        container_root_path = _host_runner_container_root().resolve(strict=True)
    except FileNotFoundError:
        return fallback_cwd

    if _path_is_within_root(cwd_path, container_root_path):
        return str(cwd_path)
    return fallback_cwd


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
            body_bytes = response.read()
            body_text = body_bytes.decode("utf-8", errors="replace")
            body = body_text.strip()
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


def _resolve_host_runner_requests_dir(verbose: bool = False) -> Optional[tuple[str, float]]:
    for shared_env_file in _shared_host_runner_env_files():
        shared_values = _read_host_runner_env_file(shared_env_file)
        shared_requests_dir = _alias_value(
            shared_values,
            HOST_RUNNER_REQUESTS_DIR_ENV,
        )
        shared_url = _alias_value(shared_values, HOST_RUNNER_URL_ENV)
        if shared_url and not shared_requests_dir:
            shared_requests_dir = DEFAULT_HOST_RUNNER_REQUESTS_DIR
        if shared_requests_dir:
            timeout_raw = _alias_value(shared_values, HOST_RUNNER_TIMEOUT_ENV)
            if not timeout_raw:
                timeout_raw = "86400"
            try:
                timeout = float(timeout_raw)
            except ValueError as error:
                raise HostRunnerError(
                    f"{HOST_RUNNER_TIMEOUT_ENV} must be numeric; got {timeout_raw!r}."
                ) from error
            if verbose:
                sys.stdout.write(
                    f"[host-runner-client] trying requests_dir: {shared_requests_dir}\n"
                )
                sys.stdout.flush()
            return shared_requests_dir, timeout
    for candidate in _host_runner_env_candidates():
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
            sys.stdout.write(
                f"[host-runner-client] trying requests_dir: {requests_dir}\n"
            )
            sys.stdout.flush()
        return requests_dir, timeout
    return None


def _collect_forwarded_environment(
    extra_forwarded_env: Optional[dict[str, str]] = None,
) -> dict:
    forwarded: dict[str, str] = {}
    for key in FORWARDED_ENVIRONMENT_KEYS:
        value = os.environ.get(key)
        if value:
            forwarded[key] = value
    if extra_forwarded_env is not None:
        for key, value in extra_forwarded_env.items():
            if value:
                forwarded[key] = value
    return forwarded


def _parse_exit_code_line(line: str) -> Optional[int]:
    for prefix in HOST_RUNNER_EXIT_CODE_PREFIXES:
        if not line.startswith(prefix):
            continue
        line_segment = line[len(prefix):]
        raw_exit_code = line_segment.strip()
        try:
            return int(raw_exit_code)
        except ValueError as error:
            raise HostRunnerError(
                f"Host runner returned an invalid exit code marker {raw_exit_code!r}."
            ) from error
    return None


def _cleanup_request_artifacts(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue


def _fsync_parent_directory(path: Path) -> None:
    directory_fd: int | None = None
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
        os.fsync(directory_fd)
    except OSError:
        pass
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _write_request_file(request_file: Path, payload_json: str) -> None:
    with request_file.open("w", encoding="utf-8") as request_stream:
        request_stream.write(payload_json)
        request_stream.flush()
        os.fsync(request_stream.fileno())
    _fsync_parent_directory(request_file)


def _stream_chunk_path(stream_file: Path, index: int) -> Path:
    chunk_name = f"{stream_file.name}.{index:08d}{STREAM_CHUNK_FILE_SUFFIX}"
    return stream_file.with_name(chunk_name)


def _cancel_file_path(requests_path: Path, request_id: str) -> Path:
    return requests_path / f"{request_id}{CANCEL_FILE_SUFFIX}"


def _heartbeat_file_path(requests_path: Path, request_id: str) -> Path:
    return requests_path / f"{request_id}{HEARTBEAT_FILE_SUFFIX}"


def _cleanup_stream_artifacts(
    request_file: Path,
    processing_file: Path,
    stream_file: Path,
) -> None:
    _cleanup_request_artifacts(
        request_file,
        processing_file,
        stream_file,
    )
    chunk_pattern = f"{stream_file.name}.*{STREAM_CHUNK_FILE_SUFFIX}"
    for chunk_path in stream_file.parent.glob(chunk_pattern):
        _cleanup_request_artifacts(chunk_path)


def _write_request_control_file(path: Path, payload: str = "") -> None:
    with path.open("w", encoding="utf-8") as control_stream:
        control_stream.write(payload)
        control_stream.flush()
        os.fsync(control_stream.fileno())
    _fsync_parent_directory(path)


def _refresh_request_heartbeat(path: Path) -> None:
    heartbeat_payload = f"{time.time():.6f}\n"
    _write_request_control_file(path, heartbeat_payload)


def _drain_buffered_stream_text(
    request_file: Path,
    processing_file: Path,
    stream_file: Path,
    *,
    buffered: str,
) -> tuple[Optional[int], str]:
    while True:
        newline_index = buffered.find("\n")
        carriage_index = buffered.find("\r")

        if newline_index == -1 and carriage_index == -1:
            return None, buffered

        delimiter_indexes = [
            index for index in (newline_index, carriage_index) if index != -1
        ]
        delimiter_index = min(delimiter_indexes)
        segment = buffered[: delimiter_index + 1]
        buffered = buffered[delimiter_index + 1 :]

        if segment.endswith("\n"):
            exit_code = _parse_exit_code_line(segment)
            if exit_code is not None:
                _cleanup_stream_artifacts(
                    request_file,
                    processing_file,
                    stream_file,
                )
                return exit_code, buffered

        sys.stdout.write(segment)
        sys.stdout.flush()


def _drain_request_stream_output(
    request_file: Path,
    processing_file: Path,
    stream_file: Path,
    *,
    buffered: str,
    offset: int,
    next_chunk_index: int,
) -> tuple[Optional[int], str, int, int]:
    while True:
        chunk_path = _stream_chunk_path(stream_file, next_chunk_index)
        if not chunk_path.exists():
            break
        chunk = chunk_path.read_bytes()
        next_chunk_index += 1
        if not chunk:
            continue
        text = chunk.decode("utf-8", errors="replace")
        buffered += text
        exit_code, buffered = _drain_buffered_stream_text(
            request_file,
            processing_file,
            stream_file,
            buffered=buffered,
        )
        if exit_code is not None:
            return exit_code, buffered, offset, next_chunk_index
    if next_chunk_index == 0 and stream_file.exists():
        with stream_file.open("rb") as stream:
            stream.seek(offset)
            chunk = stream.read()
            offset += len(chunk)
        if chunk:
            text = chunk.decode("utf-8", errors="replace")
            buffered += text
            exit_code, buffered = _drain_buffered_stream_text(
                request_file,
                processing_file,
                stream_file,
                buffered=buffered,
            )
            if exit_code is not None:
                return exit_code, buffered, offset, next_chunk_index
    return None, buffered, offset, next_chunk_index


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
    processing_file = requests_path / f"{request_id}{PROCESSING_FILE_SUFFIX}"
    stream_file = requests_path / f"{request_id}{STREAM_FILE_SUFFIX}"
    cancel_file = _cancel_file_path(requests_path, request_id)
    heartbeat_file = _heartbeat_file_path(requests_path, request_id)
    payload_json = json.dumps(payload)
    _refresh_request_heartbeat(heartbeat_file)
    _write_request_file(request_file, payload_json)
    deadline = time.monotonic() + timeout
    claim_timeout = timeout
    if claim_timeout > HOST_RUNNER_REQUEST_CLAIM_TIMEOUT_SECONDS:
        claim_timeout = HOST_RUNNER_REQUEST_CLAIM_TIMEOUT_SECONDS
    claim_deadline = time.monotonic() + claim_timeout
    offset = 0
    next_chunk_index = 0
    buffered = ""
    next_heartbeat_refresh = (
        time.monotonic() + HOST_RUNNER_HEARTBEAT_INTERVAL_SECONDS
    )
    try:
        while time.monotonic() < deadline:
            if time.monotonic() >= next_heartbeat_refresh:
                _refresh_request_heartbeat(heartbeat_file)
                next_heartbeat_refresh = (
                    time.monotonic() + HOST_RUNNER_HEARTBEAT_INTERVAL_SECONDS
                )
            first_chunk_path = _stream_chunk_path(stream_file, 0)
            if (
                time.monotonic() >= claim_deadline
                and request_file.exists()
                and not processing_file.exists()
                and not stream_file.exists()
                and not first_chunk_path.exists()
            ):
                try:
                    request_file.unlink()
                except FileNotFoundError:
                    pass
                pending_processing_paths = sorted(
                    requests_path.glob(f"*{PROCESSING_FILE_SUFFIX}")
                )
                if pending_processing_paths:
                    pending_message = _format_pending_processing_message(requests_path)
                    raise HostRunnerQueueBlockedError(
                        "Host runner did not claim the queued request within "
                        f"{HOST_RUNNER_REQUEST_CLAIM_TIMEOUT_SECONDS:g}s. This usually means "
                        f"{pending_message}"
                    )
                raise HostRunnerQueueUnavailableError(
                    "Host runner did not claim the queued request within "
                    f"{HOST_RUNNER_REQUEST_CLAIM_TIMEOUT_SECONDS:g}s. This usually means "
                    f"{requests_dir} is not actually shared with the host, or the host runner "
                    f"is not watching that directory."
                )
            exit_code, buffered, offset, next_chunk_index = _drain_request_stream_output(
                request_file,
                processing_file,
                stream_file,
                buffered=buffered,
                offset=offset,
                next_chunk_index=next_chunk_index,
            )
            if exit_code is not None:
                return exit_code
            time.sleep(0.1)
    except KeyboardInterrupt:
        if request_file.exists() and not processing_file.exists():
            _cleanup_request_artifacts(
                heartbeat_file,
                request_file,
                cancel_file,
            )
            return 130

        _write_request_control_file(cancel_file, "interrupt\n")
        interrupt_deadline = time.monotonic() + HOST_RUNNER_INTERRUPT_GRACE_SECONDS
        while time.monotonic() < interrupt_deadline:
            exit_code, buffered, offset, next_chunk_index = _drain_request_stream_output(
                request_file,
                processing_file,
                stream_file,
                buffered=buffered,
                offset=offset,
                next_chunk_index=next_chunk_index,
            )
            if exit_code is not None:
                return 130
            time.sleep(0.1)
        return 130
    raise HostRunnerError(
        f"Host runner request via {requests_dir} timed out after {timeout:g}s."
    )


def _delegate_command_via_http(
    payload: dict,
    *,
    cwd: str,
    emit_client_context: bool,
) -> int:
    endpoint_candidates = _host_runner_endpoint_candidates()
    if not endpoint_candidates:
        raise HostRunnerError(
            f"{HOST_RUNNER_URL_ENV} is not configured, so host delegation is unavailable."
        )
    json_string = json.dumps(payload)
    request_data = json_string.encode("utf-8")
    retry_deadline = time.monotonic() + HOST_RUNNER_HEALTH_RETRY_WINDOW_SECONDS
    announced_urls: set[str] = set()
    retry_notice_emitted = False
    failures: list[str] = []
    while True:
        current_failures: list[str] = []
        for url, token, timeout in endpoint_candidates:
            if emit_client_context and url not in announced_urls:
                sys.stdout.write(f"[host-runner-client] trying: {url}\n")
                sys.stdout.flush()
                announced_urls.add(url)
            try:
                _assert_host_runner_healthy(url)
            except HostRunnerError as error:
                current_failures.append(str(error))
                continue

            if emit_client_context:
                host_dtshell_commands = os.environ.get("HOST_DTSHELL_COMMANDS", "")
                sys.stdout.write(f"[host-runner-client] url: {url}\n")
                sys.stdout.write(f"[host-runner-client] cwd: {cwd}\n")
                if host_dtshell_commands:
                    sys.stdout.write(
                        f"[host-runner-client] HOST_DTSHELL_COMMANDS={host_dtshell_commands}\n"
                    )
                sys.stdout.flush()

            request = urllib_request.Request(
                url,
                data=request_data,
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
                        parsed_exit_code = _parse_exit_code_line(line)
                        if parsed_exit_code is not None:
                            exit_code = parsed_exit_code
                            continue
                        sys.stdout.write(line)
                        sys.stdout.flush()
                    return exit_code
            except urllib_error.HTTPError as error:
                error_string = error.read()
                decoded_error_string = error_string.decode("utf-8", errors="replace")
                message = decoded_error_string.strip() or error.reason
                current_failures.append(
                    f"Host runner request failed with HTTP {error.code}: {message}"
                )
            except urllib_error.URLError as error:
                current_failures.append(
                    f"Could not reach host runner at {url}: {error.reason}"
                )

        failures = current_failures or failures
        if time.monotonic() >= retry_deadline:
            raise HostRunnerError(" | ".join(failures))

        if emit_client_context and not retry_notice_emitted:
            sys.stdout.write(
                "[host-runner-client] waiting for host runner to become healthy...\n"
            )
            sys.stdout.flush()
            retry_notice_emitted = True
        time.sleep(HOST_RUNNER_HEALTH_RETRY_INTERVAL_SECONDS)


def delegate_command_to_host(
    command: Iterable[str],
    args: Iterable[str],
    *,
    cwd: Optional[str] = None,
    emit_client_context: bool = False,
    forwarded_env: Optional[dict[str, str]] = None,
) -> int:
    command_list = list(command)
    if not command_list:
        raise HostRunnerError("Host runner command path must not be empty.")
    if not all(isinstance(part, str) and part for part in command_list):
        raise HostRunnerError(
            "Host runner command path must contain only non-empty strings."
        )
    args_list = list(args)
    forwarded_environment = _collect_forwarded_environment(forwarded_env)
    requested_working_directory = cwd
    if requested_working_directory is None:
        requested_working_directory = os.getcwd()
    working_directory = _normalize_host_delegated_cwd(
        requested_working_directory,
    )
    payload = {
        "command": command_list,
        "argv": args_list,
        "cwd": working_directory,
        "env": forwarded_environment,
    }

    resolved_requests_dir = _resolve_host_runner_requests_dir(verbose=emit_client_context)
    if resolved_requests_dir is not None:
        requests_dir, timeout = resolved_requests_dir
        if emit_client_context:
            host_dtshell_commands = os.environ.get("HOST_DTSHELL_COMMANDS", "")
            sys.stdout.write(f"[host-runner-client] requests_dir: {requests_dir}\n")
            if working_directory != requested_working_directory:
                sys.stdout.write(
                    "[host-runner-client] cwd outside delegated workspace; "
                    f"using {working_directory}\n"
                )
            sys.stdout.write(f"[host-runner-client] cwd: {working_directory}\n")
            if host_dtshell_commands:
                sys.stdout.write(
                    f"[host-runner-client] HOST_DTSHELL_COMMANDS={host_dtshell_commands}\n"
                )
            sys.stdout.flush()
        try:
            return _delegate_command_via_requests_dir(
                requests_dir,
                payload,
                timeout=timeout,
            )
        except HostRunnerQueueUnavailableError as queue_error:
            if host_runner_url() is None:
                raise
            if emit_client_context:
                retry_message = (
                    "[host-runner-client] queue unavailable\n"
                )
                if isinstance(queue_error, HostRunnerQueueBlockedError):
                    retry_message = (
                        "[host-runner-client] queue blocked\n"
                    )
                sys.stdout.write(
                    retry_message
                )
                sys.stdout.flush()
            try:
                return _delegate_command_via_http(
                    payload,
                    cwd=working_directory,
                    emit_client_context=emit_client_context,
                )
            except HostRunnerError as http_error:
                raise HostRunnerError(
                    f"{queue_error} Fallback via HTTP host runner also failed: {http_error}"
                ) from http_error
    return _delegate_command_via_http(
        payload,
        cwd=working_directory,
        emit_client_context=emit_client_context,
    )


def get_current_dts_cli_options(argv: Optional[list[str]] = None) -> list[str]:
    parsed_argv = list(sys.argv[1:] if argv is None else argv)
    forwarded_options: list[str] = []
    index = 0
    while index < len(parsed_argv):
        arg = parsed_argv[index]
        if not arg.startswith("-"):
            break
        if arg in ("--debug", "--verbose", "-vv", "--quiet", "-q"):
            forwarded_options.append(arg)
            index += 1
            continue
        if arg == "--profile":
            if index + 1 >= len(parsed_argv):
                break
            forwarded_options.extend([arg, parsed_argv[index + 1]])
            index += 2
            continue
        if arg.startswith("--profile="):
            forwarded_options.append(arg)
            index += 1
            continue
        index += 1
    return forwarded_options


def delegate_matrix_run_to_host(
    args: Iterable[str],
    *,
    engine_host: Optional[str] = None,
    renderer_only: bool = False,
) -> int:
    args_list = list(args)
    emit_client_context = "--verbose" in args_list or "-vv" in args_list
    forwarded_env: dict[str, str] = {}
    delegated_cwd: Optional[str] = None
    command_prefix = get_current_dts_cli_options()
    if engine_host:
        forwarded_env[HOST_RUNNER_ENGINE_HOST_FORWARD_ENV] = engine_host
    if renderer_only:
        forwarded_env[HOST_RUNNER_MATRIX_RENDERER_ONLY_FORWARD_ENV] = "1"
        delegated_cwd = _host_runner_fallback_cwd()
    return delegate_command_to_host(
        [*command_prefix, "matrix", "run"],
        args_list,
        cwd=delegated_cwd,
        emit_client_context=emit_client_context,
        forwarded_env=forwarded_env or None,
    )
