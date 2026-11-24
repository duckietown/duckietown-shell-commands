import argparse
import json
import os
import platform
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dt_shell import dtslogger

from utils.duckiematrix_utils import get_most_recent_version_installed, get_path_to_app
from utils.matrix_trace import copy_trace_bundle, validate_trace_bundle


CAPTURE_OUTPUT_ENV = "DTS_HOST_RUNNER_CAPTURE_OUTPUT"
CAPTURE_MAX_SECONDS = 10
CAPTURE_RESERVE_BYTES = 6 * 1024**3
CAPTURE_INPUT_NAME = "input.gputrace"
CAPTURE_NODE_PATTERN = re.compile(
    r"^/(?:commands|resources|performance|api_calls)"
    r"(?:/[A-Za-z0-9_.\[\]-]+)*$"
)
CAPTURE_REQUEST_PATTERN = re.compile(r"^[0-9a-f]{32}$")
CAPTURE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
ANALYSIS_TIMEOUT_SECONDS = 180


def validate_capture_options(options: argparse.Namespace) -> None:
    for name in ("pid", "boundary", "device"):
        value = getattr(options, name)
        minimum = 0 if name == "device" else 1
        if value is not None and (type(value) is not int or not minimum <= value <= 2_147_483_647):
            raise ValueError(f"--{name} requires an integer from {minimum} to 2147483647.")
    if options.version is not None and not CAPTURE_VERSION_PATTERN.fullmatch(options.version):
        raise ValueError("--version requires a simple installed release identifier.")
    for node in [*options.browse, *options.inspect, *options.fetch]:
        if not CAPTURE_NODE_PATTERN.fullmatch(node) or any(
            part in (".", "..") for part in node.split("/")
        ):
            raise ValueError("Inspection paths must be absolute gpudebug tree paths without traversal or commands.")
    if len(options.browse) + len(options.inspect) + len(options.fetch) > 32:
        raise ValueError("At most 32 inspection/export nodes can be requested.")
    if options.profile_execution is not None:
        if options.profile_execution not in ("overlapping", "serial"):
            raise ValueError("--profile-execution must be overlapping or serial.")
        if not options.profile:
            raise ValueError("--profile-execution requires --profile.")
    if options.profile and not options.input:
        raise ValueError("--profile requires --input; stop the live workload before replay profiling.")
    if options.input and (
        any(value is not None for value in (options.pid, options.boundary, options.version))
        or options.device != 0
    ):
        raise ValueError("--input cannot be combined with live Renderer target options.")
    if options.check and (
        options.input or options.profile or options.browse or options.inspect or options.fetch
        or any(value is not None for value in (options.pid, options.boundary, options.version))
    ):
        raise ValueError("--check cannot be combined with trace analysis or live target options.")


def resolve_capture_output(value: str | None) -> Path:
    if value is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        value = str(
            Path.home() / ".duckietown" / "duckiematrix" / "captures"
            / f"renderer-{timestamp}-{uuid.uuid4().hex[:8]}"
        )
    output = Path(value).expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing to overwrite capture results: {output}")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return output


def capture_artifact_paths(requests: Path, request_id: str) -> tuple[Path, Path, Path]:
    if not CAPTURE_REQUEST_PATTERN.fullmatch(request_id):
        raise ValueError("Invalid capture request identifier.")
    directory = requests / f"{request_id}.capture-artifacts"
    return directory / "result", directory / "complete", directory / CAPTURE_INPUT_NAME


def validate_gpu_trace(path: Path) -> dict:
    if path.suffix != ".gputrace":
        raise ValueError("The capture input must be a .gputrace bundle directory.")
    validate_trace_bundle(path, allow_internal_links=True)
    for name in ("metadata", "index", "store0"):
        if not (path / name).is_file():
            raise ValueError(f"The GPU trace is missing {name}: {path}")
    try:
        with (path / "metadata").open("rb") as stream:
            metadata = plistlib.load(stream)
    except (ValueError, plistlib.InvalidFileException) as error:
        raise ValueError(f"Unsupported GPU capture metadata: {path}") from error
    if not isinstance(metadata, dict):
        raise ValueError(f"Unsupported GPU capture metadata: {path}")
    return metadata


def _write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def _run_tool(
    command: list[str], output: Path, environment: dict[str, str], *, timeout: int = 30,
    capture: bool = False,
) -> None:
    with output.open("x") as stdout, output.with_suffix(output.suffix + ".stderr").open("x") as stderr:
        os.fchmod(stdout.fileno(), 0o600)
        os.fchmod(stderr.fileno(), 0o600)
        process = subprocess.Popen(
            command, env=environment, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
        )
        try:
            process.wait(timeout=timeout - 2 if capture else timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if isinstance(error, KeyboardInterrupt):
                raise
            raise RuntimeError(f"Timed out running {Path(command[0]).name}; see {output}") from error
    if process.returncode:
        raise RuntimeError(
            f"{Path(command[0]).name} exited with code {process.returncode}; "
            f"see {output} and {output}.stderr"
        )


def _find_tools(output: Path) -> tuple[dict[str, str], dict[str, str]]:
    if platform.system() != "Darwin":
        raise ValueError("Metal capture/analysis requires macOS and the native host runner.")
    environment = os.environ.copy()
    developer = Path("/Applications/Xcode.app/Contents/Developer")
    if "DEVELOPER_DIR" not in environment and developer.is_dir():
        environment["DEVELOPER_DIR"] = str(developer)
    tools = {}
    for name in ("gpucapture", "gpudebug"):
        found = subprocess.run(
            ["/usr/bin/xcrun", "--find", name], env=environment, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=15, check=False,
        )
        path = found.stdout.strip()
        if found.returncode or not path or not Path(path).is_file():
            raise ValueError(
                f"{name} is unavailable. Headless Metal capture/analysis requires "
                "macOS 27 or later and the corresponding Apple GPU tools."
            )
        tools[name] = path
        _run_tool([path, "--help"], output / f"{name}-help.txt", environment)
        _run_tool([path, "--version"], output / f"{name}-version.txt", environment)
    help_text = (output / "gpudebug-help.txt").read_text()
    if not all(option in help_text for option in ("--oneshot", "--json", "--timeout")):
        raise ValueError("gpudebug lacks required --oneshot/--json/--timeout support; update the host GPU tools.")
    return tools, environment


def _process_executables() -> list[tuple[int, Path]]:
    result = subprocess.run(
        ["/bin/ps", "-axww", "-o", "pid=,uid=,comm="], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=True, timeout=15,
    )
    processes = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            if int(fields[1]) == os.getuid():
                processes.append((int(fields[0]), Path(fields[2]).resolve()))
    return processes


def _renderer_target(version: str | None, pid: int | None) -> tuple[int, str]:
    version = version or get_most_recent_version_installed("macos")
    app = get_path_to_app("macos", version) if version is not None else None
    if app is None:
        raise ValueError("No matching installed macOS Renderer; specify --version.")
    bundle = Path(app)
    with (bundle / "Contents" / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    executable = info.get("CFBundleExecutable") if isinstance(info, dict) else None
    if (
        not isinstance(executable, str) or Path(executable).name != executable
        or executable in (".", "..")
    ):
        raise ValueError("The Renderer bundle has an invalid CFBundleExecutable.")
    expected = (bundle / "Contents" / "MacOS" / executable).resolve()
    candidates = [
        candidate for candidate, path in _process_executables()
        if path == expected and (pid is None or pid == candidate)
    ]
    if len(candidates) != 1:
        raise ValueError(
            "Expected exactly one current-user Renderer of the selected version. "
            "Launch it with dts matrix run --metal-capture, or disambiguate with --pid."
        )
    return candidates[0], str(expected)


def _debugger_commands(options: argparse.Namespace, output: Path) -> list[str]:
    commands = [
        "status", "go /commands", "list --all",
        "go /resources/render_pipelines", "list --all",
        "go /resources/libraries", "list --all",
    ]
    if options.profile:
        commands.extend([
            "profile load",
            "status",
            "go /performance", "list --all",
            "go /performance/shaders", "list --all",
            "go /performance/encoders", "list --all",
            "go /performance/commands", "list --all",
        ])
    for node in options.browse:
        commands.extend([f"go {node}", "list --all"])
    for node in options.inspect:
        parent, name = node.rsplit("/", 1)
        commands.extend([f"go {parent}", f"info {name} --all"])
        if re.fullmatch(r"/resources/libraries/lib[0-9]+", node):
            commands.extend([f"go {node}", "list --all"])
    for index, node in enumerate(options.fetch):
        parent, name = node.rsplit("/", 1)
        destination = shlex.quote(str(output / "resources" / f"resource-{index}"))
        commands.extend([f"go {parent}", f"fetch {name} --out {destination}"])
    rooted_commands = []
    for command in commands:
        if command.startswith("go /"):
            # gpudebug can resolve absolute paths from the current subtree.
            rooted_commands.append("go /")
        rooted_commands.append(command)
    return rooted_commands


def _read_debugger_results(path: Path) -> list[object]:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("error:"):
            raise ValueError(f"gpudebug reported {line}; raw output remains at {path}")
    results = []
    decoder = json.JSONDecoder()
    offset = 0
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        if text.startswith("Profile data already loaded.", offset):
            notice = text[offset:].partition("\n")[0]
            if notice == "Profile data already loaded.":
                dtslogger.info(f"gpudebug: {notice}")
                offset += len(notice)
                continue
        try:
            result, offset = decoder.raw_decode(text, offset)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"gpudebug did not return valid JSON at line {error.lineno}; raw output remains at {path}"
            ) from error
        if isinstance(result, dict) and (
            result.get("success") is False or result.get("error")
        ):
            raise ValueError(f"gpudebug reported an unsuccessful operation; see {path}")
        results.append(result)
    if not results:
        raise ValueError(f"gpudebug produced no analysis results; see {path}")
    return results


def capture_matrix(options: argparse.Namespace, output: Path) -> None:
    validate_capture_options(options)
    output.mkdir(mode=0o700)
    tools, environment = _find_tools(output)
    free = shutil.disk_usage(output).free
    if free < CAPTURE_RESERVE_BYTES:
        raise ValueError(f"Insufficient host capture space: {free} bytes free; at least 6 GiB required.")
    report = {
        "schema_version": 1, "host_os": platform.platform(), "tools": tools,
        "host_free_bytes_before": free, "capture_max_seconds": CAPTURE_MAX_SECONDS,
        "replay_profiling": options.profile, "replay_gpu_policy": "default" if options.profile else None,
        "replay_execution": (options.profile_execution or "overlapping") if options.profile else None,
        "debugger_session_mode": "oneshot", "check_only": options.check,
    }
    if options.check:
        _write_json(output / "report.json", report)
        return
    if options.input:
        trace = Path(options.input).expanduser().absolute()
        validate_gpu_trace(trace)
        report["input_trace"] = str(trace)
        if options.profile and any(
            "duckiematrix.app/Contents/MacOS/" in str(path)
            for _, path in _process_executables()
        ):
            raise ValueError("Stop the live Duckiematrix Renderer before replay profiling.")
        if options.profile:
            copy_bytes = sum(entry.stat().st_size for entry in trace.rglob("*") if entry.is_file())
            required = copy_bytes + CAPTURE_RESERVE_BYTES
            if free < required:
                raise ValueError(f"Insufficient host profiling space: {free} bytes free; {required} required.")
            profiled = output / "profiled.gputrace"
            copy_trace_bundle(trace, profiled, allow_internal_links=True)
            trace = profiled
            report["profiled_trace"] = profiled.name
    else:
        pid, executable = _renderer_target(options.version, options.pid)
        report["renderer"] = {"pid": pid, "executable": executable, "version": options.version}
        target = ["--pid", str(pid), "--device", str(options.device)]
        _run_tool([tools["gpucapture"], "boundaries", *target], output / "boundaries.txt", environment)
        trace = output / "renderer.gputrace"
        command = [tools["gpucapture"], "start", *target, "--count", "1", "--output", str(trace)]
        if options.boundary is not None:
            command.extend(["--boundary", str(options.boundary)])
        started = time.monotonic()
        _run_tool(
            command, output / "capture.txt", environment,
            timeout=CAPTURE_MAX_SECONDS, capture=True,
        )
        elapsed = time.monotonic() - started
        metadata = validate_gpu_trace(trace)
        frames = metadata.get("DYCaptureEngine.captured_frames_count")
        if elapsed > CAPTURE_MAX_SECONDS or type(frames) is not int or frames != 1:
            raise ValueError("Capture must contain exactly one complete frame and finish within ten actual seconds.")
        report.update({"capture_elapsed_seconds": elapsed, "captured_frames": frames})
    (output / "resources").mkdir(mode=0o700)
    debugger = [
        tools["gpudebug"], "--oneshot", "--json", "--quiet", "--timeout", "15",
        "--gputrace", str(trace), "--output", str(output / "resources"),
    ]
    if options.profile:
        collection = [
            f"profile run --gpu-state default --exec {options.profile_execution or 'overlapping'} --embed",
        ]
        raw_profile = output / "profile-collection.stdout"
        _run_tool(
            [*debugger, "-c", collection[0]], raw_profile, environment,
            timeout=ANALYSIS_TIMEOUT_SECONDS,
        )
        _write_json(output / "profile-collection.json", {
            "commands": collection, "results": _read_debugger_results(raw_profile),
        })
        report["profile_collection"] = "profile-collection.json"
    commands = _debugger_commands(options, output)
    _write_json(output / "debugger-commands.json", commands)
    for command in commands:
        debugger.extend(["-c", command])
    raw = output / "gpudebug.stdout"
    _run_tool(debugger, raw, environment, timeout=ANALYSIS_TIMEOUT_SECONDS)
    _write_json(output / "analysis.json", {
        "commands": commands, "results": _read_debugger_results(raw),
    })
    report["debugger_output"] = "analysis.json"
    report["requested_browse_nodes"] = options.browse
    report["requested_inspection_nodes"] = options.inspect
    report["requested_resource_nodes"] = options.fetch
    _write_json(output / "report.json", report)
