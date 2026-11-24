import json
import os
import platform
import plistlib
import re
import shutil
import signal
import stat
import subprocess
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Optional

TRACE_OUTPUT_ENV = "DTS_HOST_RUNNER_TRACE_OUTPUT"
TRACE_FINALIZE_TIMEOUT_SECONDS = 120
TRACE_EXPORT_TIMEOUT_SECONDS = 120
TRACE_CONFIGURATION_TIMEOUT_SECONDS = 30
TRACE_TEMPLATE_DEFAULT = "Metal System Trace"
TRACE_PERFORMANCE_STATES = ("default", "minimum", "medium", "maximum")
TRACE_THREAD_SETTINGS = {
    "waiting_threads": "recordWaitingThreads",
    "kernel_callstacks": "recordKernelStacks",
    "context_switch_sampling": "contextSwitchSampling",
}
TRACE_RECORDED_THREAD_SETTINGS = {
    "waiting_threads": "record-waiting-threads",
    "kernel_callstacks": "needs-kernel-callstack",
    "context_switch_sampling": "context-switch-sampling",
}
TRACE_DURATION_DEFAULT = 30
TRACE_DURATION_MAX = 300
TRACE_WINDOW_DEFAULT = 10
TRACE_WINDOW_MAX = 60
TRACE_START_SESSION_MAX = 1_000_000
TRACE_PROFILER_PREFIX = "===DTS_MATRIX_PROFILER==="
TRACE_REQUEST_PATTERN = re.compile(r"^[0-9a-f]{32}$")
TRACE_EXPORT_SCHEMAS = {
    "metal-gpu-submission-to-command-buffer-id", "metal-application-encoders-list",
    "metal-object-label", "time-info", "metal-command-buffer-completed",
    "metal-driver-intervals", "metal-gpu-intervals",
    "metal-application-command-buffer-submissions",
    "metal-command-buffer-to-accelerator-id", "gpu-performance-state-info",
    "gpu-performance-state-intervals", "gpu-performance-device-state-intervals",
    "device-thermal-state-intervals", "process-info", "thread-info",
    "time-profile", "time-sample", "dyld-library-load", "context-switch-sample",
}


@dataclass(frozen=True)
class TraceSettings:
    template: str | None = None
    performance_state: str | None = None
    waiting_threads: bool = False
    kernel_callstacks: bool = False
    context_switch_sampling: bool = False

    @property
    def customized(self) -> bool:
        return (
            self.template is not None or self.performance_state is not None
            or any(getattr(self, name) for name in TRACE_THREAD_SETTINGS)
        )

    def validate(self) -> None:
        if self.performance_state is not None and self.performance_state not in TRACE_PERFORMANCE_STATES:
            raise ValueError("--trace-performance-state requires default, minimum, medium, or maximum.")
        if self.performance_state not in (None, "default") and self.template is None:
            raise ValueError(
                "A non-default --trace-performance-state requires --trace-template "
                "saved with that GPU performance state in Instruments."
            )
        for name in TRACE_THREAD_SETTINGS:
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"--trace-{name.replace('_', '-')} must be a boolean.")


def resolve_trace_template(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if path.suffix != ".tracetemplate" or not path.is_file():
        raise ValueError("--trace-template must name an existing .tracetemplate file.")
    return path


def read_trace_settings(path: Path, *, recorded: bool = False) -> dict[str, str | bool]:
    message = f"Cannot validate Instruments settings in {path}: unsupported template format."
    try:
        with path.open("rb") as stream:
            archive = plistlib.load(stream)
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        raise ValueError(f"Cannot read Instruments settings in {path}: {error}") from error
    if not isinstance(archive, dict) or archive.get("$archiver") != "NSKeyedArchiver":
        raise ValueError(message)
    objects = archive.get("$objects")
    top = archive.get("$top")
    if not isinstance(objects, list) or not isinstance(top, dict):
        raise ValueError(message)

    def resolve(value: object) -> object:
        if isinstance(value, plistlib.UID):
            if not 0 <= value.data < len(objects):
                raise ValueError(message)
            return objects[value.data]
        return value

    def dictionary(value: object) -> dict[str, object]:
        value = resolve(value)
        if not isinstance(value, dict):
            raise ValueError(message)
        keys, values = value.get("NS.keys"), value.get("NS.objects")
        if not isinstance(keys, list) or not isinstance(values, list) or len(keys) != len(values):
            raise ValueError(message)
        result: dict[str, object] = {}
        for key, item in zip(keys, values):
            key = resolve(key)
            if not isinstance(key, str) or key in result:
                raise ValueError(message)
            result[key] = resolve(item)
        return result

    names = [dictionary(stub).get("name") for stub in dictionary(top.get("stubInfoByUUID")).values()]
    if "Metal Application" not in names or "Time Profiler" not in names:
        raise ValueError(f"{path} must include the Metal Application and Time Profiler instruments.")
    command = resolve(top.get("templateRunCommand"))
    if not isinstance(command, dict):
        raise ValueError(message)
    control = resolve(command.get("_recordingControlState"))
    if not isinstance(control, dict):
        raise ValueError(message)
    state = dictionary(control.get("state"))
    performance = state.get("gpuperformancestate")
    if type(performance) is not int or not 0 <= performance < len(TRACE_PERFORMANCE_STATES):
        raise ValueError(message)
    settings: dict[str, str | bool] = {"performance_state": TRACE_PERFORMANCE_STATES[performance]}
    if not recorded:
        for name, key in TRACE_THREAD_SETTINGS.items():
            value = state.get(key)
            if type(value) is not bool:
                raise ValueError(message)
            settings[name] = value
        return settings

    # Runtime overrides change table parameters, not the saved UI defaults.
    profiles = [
        dictionary(value.get("attributes")) for value in objects
        if isinstance(value, dict) and resolve(value.get("schemaName")) == "time-profile"
    ]
    if not profiles:
        raise ValueError(f"No recorded Time Profiler table parameters found in {path}.")
    for profile in profiles:
        for name, key in TRACE_RECORDED_THREAD_SETTINGS.items():
            value = profile.get(key)
            if type(value) not in (int, bool) or value not in (0, 1):
                raise ValueError(message)
            if name in settings and settings[name] != bool(value):
                raise ValueError(f"Conflicting recorded Time Profiler parameters in {path}.")
            settings[name] = bool(value)
    return settings


def _trace_recording_command(executable: str, template: str) -> list[str]:
    command = [executable, "record", "--template", template]
    if template == TRACE_TEMPLATE_DEFAULT:
        command.extend(["--instrument", "Time Profiler"])
    return command


def trace_recording_options(
    executable: str, environment: dict[str, str], template: str, settings: TraceSettings,
) -> dict[str, object] | None:
    requested = {
        key: True for name, key in TRACE_THREAD_SETTINGS.items() if getattr(settings, name)
    }
    if not requested:
        return None
    command = _trace_recording_command(executable, template)
    try:
        result = subprocess.run(
            [*command, "--no-prompt", "--show-recording-options"],
            env=environment, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, check=False, timeout=TRACE_CONFIGURATION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("Timed out checking Instruments recording-option support.") from error
    if result.returncode:
        raise ValueError(
            "The requested thread settings require xctrace --show-recording-options "
            f"and --recording-options support. Update Xcode if needed.\n{result.stderr.strip()}"
        )
    try:
        options = json.loads(result.stdout)
    except ValueError as error:
        raise ValueError("Instruments returned invalid recording-options JSON.") from error
    profiler = options.get("Time Profiler") if isinstance(options, dict) else None
    if not isinstance(options, dict) or not isinstance(profiler, dict):
        raise ValueError("Instruments does not expose Time Profiler recording options.")
    for key in requested:
        if type(profiler.get(key)) is not bool:
            raise ValueError(f"Instruments does not expose the requested Time Profiler option {key}.")
    # Xcode requires the complete document, including unchanged fields.
    profiler.update(requested)
    return options


def trace_start_session(value: int | None) -> int | None:
    if value is not None and (type(value) is not int or not 1 <= value <= TRACE_START_SESSION_MAX):
        raise ValueError("--trace-start-session must be an integer from 1 to 1000000.")
    return value


def trace_trigger_snapshot(line: str, minimum_session: int) -> dict | None:
    marker = line.find(TRACE_PROFILER_PREFIX)
    if marker < 0:
        return None
    try:
        snapshot = json.loads(line[marker + len(TRACE_PROFILER_PREFIX):])
    except ValueError:
        return None
    if not isinstance(snapshot, dict) or snapshot.get("source") != "Renderer":
        return None
    session = snapshot.get("sessionID")
    if type(session) is not int or session < minimum_session:
        return None
    return snapshot


def trace_export_path(output: Path) -> Path:
    return output.with_suffix(".trace-export")


def select_trace_export_tables(toc: Path) -> tuple[str, list[str], list[str]]:
    root = ET.parse(toc).getroot()
    runs = root.findall("run")
    if root.tag != "trace-toc" or len(runs) != 1:
        raise ValueError("Trace export requires exactly one recorded run.")
    number = runs[0].get("number", "")
    if re.fullmatch(r"[1-9][0-9]*", number) is None:
        raise ValueError("The trace contains an invalid run number.")
    available = sorted({table.get("schema", "") for table in runs[0].findall("data/table")})
    selected = [schema for schema in available if schema in TRACE_EXPORT_SCHEMAS]
    if not selected:
        raise ValueError("The recording contains no supported CPU or Metal tables.")
    return number, selected, available


def export_trace(
    executable: str, environment: dict[str, str], output: Path, log_path: Path,
    *, duration: int | None = None, window: int | None = None,
    trigger: dict | None = None,
    settings: TraceSettings | None = None,
    effective_settings: dict[str, str | bool] | None = None,
) -> Path:
    directory = trace_export_path(output)
    directory.mkdir(mode=0o700)
    toc = directory / "toc.xml"
    events = directory / "events.xml"
    command = [executable, "export", "--input", str(output)]
    try:
        with log_path.open("ab") as log:
            os.fchmod(log.fileno(), 0o600)
            subprocess.run(
                [*command, "--toc", "--output", str(toc)], env=environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                check=True, timeout=TRACE_EXPORT_TIMEOUT_SECONDS,
            )
            number, selected, available = select_trace_export_tables(toc)
            envelope = ET.parse(toc).findtext("run/info/summary/duration")
            predicate = " or ".join(f"@schema='{schema}'" for schema in selected)
            xpath = f"/trace-toc/run[@number='{number}']/data/table[{predicate}]"
            subprocess.run(
                [*command, "--xpath", xpath, "--output", str(events)], env=environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                check=True, timeout=TRACE_EXPORT_TIMEOUT_SECONDS,
            )
        if not events.is_file() or events.stat().st_size == 0:
            raise ValueError("Instruments did not produce an event-table export.")
        manifest = directory / "manifest.json"
        with manifest.open("x", encoding="utf-8") as stream:
            json.dump({
                "version": 1, "run": int(number), "selected_schemas": selected,
                "available_schemas": available,
                "requested_duration_seconds": duration,
                "requested_window_seconds": window,
                "run_envelope_seconds": float(envelope) if envelope is not None else None,
                "trigger": trigger,
                "requested_settings": asdict(settings or TraceSettings()),
                "effective_recording_settings": effective_settings,
                "effective_settings_source": "form.template" if effective_settings is not None else None,
                "gpu_hardware_state_verified": False,
            }, stream, indent=2, allow_nan=False)
            stream.write("\n")
        validate_trace_bundle(directory)
        for path in directory.rglob("*"):
            if path.is_file():
                path.chmod(0o600)
    except (OSError, ValueError, ET.ParseError, subprocess.SubprocessError) as error:
        raise RuntimeError(
            f"Trace export failed; the raw recording remains at {output}. See {log_path}"
        ) from error
    return directory


def trace_limits(duration: int, window: Optional[int]) -> tuple[int, int]:
    if type(duration) is not int or (duration != -1 and not 1 <= duration <= TRACE_DURATION_MAX):
        raise ValueError("--trace-duration must be -1 or an integer from 1 to 300.")
    if window is None:
        window = min(TRACE_WINDOW_DEFAULT, duration) if duration > 0 else TRACE_WINDOW_DEFAULT
    if type(window) is not int or (window != -1 and not 1 <= window <= TRACE_WINDOW_MAX):
        raise ValueError("--trace-window must be -1 or an integer from 1 to 60.")
    if duration > 0 and window > duration:
        raise ValueError("--trace-window cannot exceed --trace-duration.")
    return duration, window


def resolve_trace_output(value: Optional[str] = None, *, export: bool = False) -> Path:
    if value is None:
        root = Path.home() / ".duckietown" / "duckiematrix" / "traces"
        timestamp = datetime.now(timezone.utc)
        identifier = uuid.uuid4().hex[:8]
        output = root / f"renderer-{timestamp:%Y%m%dT%H%M%SZ}-{identifier}.trace"
    else:
        output = Path(value)
        output = output.expanduser()
    output = output.absolute()
    if output.suffix != ".trace":
        raise ValueError("--trace-output must end in .trace.")
    destinations = [output]
    if export:
        destinations.append(trace_export_path(output))
    for destination in destinations:
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Refusing to overwrite trace output: {destination}")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return output


def trace_artifact_paths(requests_dir: Path, request_id: str) -> tuple[Path, Path]:
    if TRACE_REQUEST_PATTERN.fullmatch(request_id) is None:
        raise ValueError("Invalid trace request identifier.")
    directory = requests_dir / f"{request_id}.trace-artifacts"
    return directory / "renderer.trace", directory / "complete"


def validate_trace_bundle(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("A completed trace must be a regular directory.")
    files = 0
    for entry in path.rglob("*"):
        mode = entry.lstat().st_mode
        if stat.S_ISREG(mode):
            files += 1
        elif not stat.S_ISDIR(mode):
            raise ValueError("Trace bundles cannot contain links or special files.")
    if files == 0:
        raise ValueError("The trace bundle contains no recording data.")


def _copy_trace_file(source: str, destination: str) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    with os.fdopen(descriptor, "rb") as incoming:
        if not stat.S_ISREG(os.fstat(incoming.fileno()).st_mode):
            raise ValueError("Only regular trace files can be copied.")
        with open(destination, "xb") as outgoing:
            os.fchmod(outgoing.fileno(), 0o600)
            shutil.copyfileobj(incoming, outgoing)


def collect_delegated_trace(
    requests_dir: Path, request_id: str, output: Path, *, export: bool = False,
) -> bool:
    source, ready = trace_artifact_paths(requests_dir, request_id)
    if source.parent.is_symlink() or ready.is_symlink():
        raise ValueError("Trace artifacts cannot be symbolic links.")
    if not ready.is_file():
        return False
    artifacts = [(source, output)]
    if export:
        artifacts.append((trace_export_path(source), trace_export_path(output)))
    for incoming, destination in artifacts:
        validate_trace_bundle(incoming)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Refusing to overwrite trace output: {destination}")
    with TemporaryDirectory(prefix=".matrix-trace-", dir=output.parent) as directory:
        staged_artifacts = []
        for incoming, destination in artifacts:
            staged = Path(directory) / destination.name
            shutil.copytree(incoming, staged, symlinks=True, copy_function=_copy_trace_file)
            validate_trace_bundle(staged)
            staged.chmod(0o700)
            staged_artifacts.append((staged, destination))
        for staged, destination in staged_artifacts:
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(f"Refusing to overwrite trace output: {destination}")
            staged.rename(destination)
    ready.unlink()
    shutil.rmtree(source.parent)
    return True


def find_xctrace() -> tuple[str, dict[str, str]]:
    if platform.system() != "Darwin":
        raise ValueError("--trace requires a native macOS Renderer and Xcode Instruments.")
    environment = os.environ.copy()
    developer = Path("/Applications/Xcode.app/Contents/Developer")
    if "DEVELOPER_DIR" not in environment and developer.is_dir():
        environment["DEVELOPER_DIR"] = str(developer)
    result = subprocess.run(
        ["/usr/bin/xcrun", "--find", "xctrace"], env=environment,
        capture_output=True, text=True, check=False,
    )
    executable = result.stdout.strip()
    if result.returncode or not executable or not Path(executable).is_file():
        raise ValueError("--trace requires a full Xcode installation with Instruments.")
    return executable, environment


def build_trace_command(
    executable: str, renderer_pid: int, output: Path, duration: int, window: int,
    *, template: str = TRACE_TEMPLATE_DEFAULT, recording_options: Path | None = None,
) -> list[str]:
    duration, window = trace_limits(duration, window)
    if type(renderer_pid) is not int or renderer_pid <= 0:
        raise ValueError("A trace must target the launched Renderer process.")
    command = _trace_recording_command(executable, template)
    command.extend(["--no-prompt", "--output", str(output)])
    if recording_options is not None:
        command.extend(["--recording-options", str(recording_options)])
    if duration != -1:
        command.extend(["--time-limit", f"{duration}s"])
    if window != -1 and (duration == -1 or window < duration):
        command.extend(["--window", f"{window}s"])
    command.extend(["--attach", str(renderer_pid)])
    return command


class RendererTrace:
    def __init__(
        self, output: Path, duration: int, window: int, *, export: bool = False,
        start_session: int | None = None,
        settings: TraceSettings | None = None,
    ):
        self.settings = settings or TraceSettings()
        self.settings.validate()
        self.template = TRACE_TEMPLATE_DEFAULT
        self._expected_settings: dict[str, str | bool] = {}
        if self.settings.template is not None:
            template = resolve_trace_template(self.settings.template)
            self.template = str(template)
            self._expected_settings = read_trace_settings(template)
        if self.settings.performance_state is not None:
            configured = self._expected_settings.get("performance_state", "default")
            if configured != self.settings.performance_state:
                raise ValueError(
                    f"--trace-template selects {configured}, not the requested "
                    f"{self.settings.performance_state} GPU performance state."
                )
            self._expected_settings["performance_state"] = self.settings.performance_state
        for name in TRACE_THREAD_SETTINGS:
            if getattr(self.settings, name):
                self._expected_settings[name] = True
        self.output = output
        self.export_enabled = export
        self.start_session = trace_start_session(start_session)
        self.trigger_session: int | None = None
        self._renderer_pid: int | None = None
        self._closed = False
        self._lock = Lock()
        self._start_error: OSError | None = None
        self.duration, self.window = trace_limits(duration, window)
        self.executable, self.environment = find_xctrace()
        self.recording_options = trace_recording_options(
            self.executable, self.environment, self.template, self.settings,
        )
        self._options_directory: TemporaryDirectory | None = None
        self.process: Optional[subprocess.Popen] = None
        self.log_path = output.parent / f"{output.stem}-instruments.log"

    def start(self, renderer_pid: int) -> None:
        if type(renderer_pid) is not int or renderer_pid <= 0:
            raise ValueError("A trace must target the launched Renderer process.")
        with self._lock:
            if self._closed or self._renderer_pid is not None:
                raise RuntimeError("The Renderer trace has already been armed or closed.")
            self._renderer_pid = renderer_pid
            self._start_if_ready()

    def observe_renderer_line(self, line: str) -> None:
        if self.start_session is None or self.process is not None or self._closed:
            return
        snapshot = trace_trigger_snapshot(line, self.start_session)
        if snapshot is None:
            return
        with self._lock:
            if self._closed or self.process is not None or self._start_error is not None:
                return
            if self.trigger_session is None:
                self.trigger_session = snapshot["sessionID"]
            try:
                self._start_if_ready()
            except OSError as error:
                self._start_error = error

    def _start_if_ready(self) -> None:
        if self._renderer_pid is None:
            return
        if self.start_session is not None and self.trigger_session is None:
            return
        options_path = None
        if self.recording_options is not None:
            self._options_directory = TemporaryDirectory(prefix=".matrix-instruments-", dir=self.output.parent)
            options_path = Path(self._options_directory.name) / "recording-options.json"
            with options_path.open("x", encoding="utf-8") as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(self.recording_options, stream, allow_nan=False)
        command = build_trace_command(
            self.executable, self._renderer_pid, self.output, self.duration, self.window,
            template=self.template, recording_options=options_path,
        )
        with self.log_path.open("xb") as log:
            os.fchmod(log.fileno(), 0o600)
            self.process = subprocess.Popen(
                command, env=self.environment, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT,
            )

    def finish(self, *, interrupted: bool = False) -> None:
        with self._lock:
            self._closed = True
        try:
            if self._start_error is not None:
                raise RuntimeError(f"Could not start Instruments; see {self.log_path}") from self._start_error
            if self.process is None:
                if self._renderer_pid is not None and self.start_session is not None and self.trigger_session is None:
                    raise RuntimeError(
                        f"The Renderer exited before trace session {self.start_session}; no recording was started."
                    )
                return
            if self.process.poll() is None and not interrupted:
                self.process.send_signal(signal.SIGINT)
            try:
                result = self.process.wait(timeout=TRACE_FINALIZE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as error:
                self.process.kill()
                self.process.wait()
                raise RuntimeError(f"Instruments could not finalize the trace; see {self.log_path}") from error
            if result not in (0, 130):
                raise RuntimeError(f"Instruments exited with code {result}; see {self.log_path}")
            validate_trace_bundle(self.output)
            self.output.chmod(0o700)
            effective_settings = None
            if self.settings.customized:
                try:
                    effective_settings = read_trace_settings(self.output / "form.template", recorded=True)
                    for name, value in self._expected_settings.items():
                        if effective_settings[name] != value:
                            raise ValueError(
                                f"Instruments recorded {name}={effective_settings[name]!r}, "
                                f"not the requested {value!r}."
                            )
                except ValueError as error:
                    raise RuntimeError(
                        f"Trace settings verification failed: {error} "
                        f"The raw recording remains at {self.output}. See {self.log_path}"
                    ) from error
            if self.export_enabled:
                export_trace(
                    self.executable, self.environment, self.output, self.log_path,
                    duration=self.duration, window=self.window,
                    trigger={
                        "requested_session": self.start_session,
                        "observed_session": self.trigger_session,
                    },
                    settings=self.settings, effective_settings=effective_settings,
                )
            if os.environ.get(TRACE_OUTPUT_ENV):
                marker = self.output.parent / "complete"
                with marker.open("xb") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.flush()
                    os.fsync(stream.fileno())
        finally:
            self.process = None
            if self._options_directory is not None:
                self._options_directory.cleanup()
                self._options_directory = None
