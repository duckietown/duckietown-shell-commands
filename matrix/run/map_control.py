"""Map selection, simulation settings and shutdown for the launcher-owned Engine."""

from __future__ import annotations

import json
import re
import secrets
from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from math import isfinite
from pathlib import Path
from threading import Condition, Thread
from time import monotonic

from docker.errors import ContainerError, DockerException, NotFound
from docker.models.containers import Container
from docker.types import Mount
from requests.exceptions import RequestException

from dt_shell import dtslogger
from utils.docker_utils import get_client_OLD

from ..engine.run.command import MatrixEngine
from .map_preview import read_map_preview


MAP_CONTROL_PATH = "/__duckiematrix/map"
MAP_PREVIEW_PATH = "/__duckiematrix/map/preview"
ENGINE_STOP_PATH = "/__duckiematrix/engine/stop"
MAP_CONTROL_HEADER = "X-Duckiematrix-Map-Token"
MAP_CONTROL_PORT_ENV = "DT_MATRIX_MAP_CONTROL_PORT"
MAP_CONTROL_TOKEN_ENV = "DT_MATRIX_MAP_CONTROL_TOKEN"
MAP_CONTROL_HOSTS = ("localhost", "127.0.0.1", "::1")
SAFE_MAP_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
# Reuse the parser inside the pinned image, where the embedded layer files live.
MAP_CATALOG_COMMAND = Path(__file__).with_name("map_preview.py").read_text(encoding="utf-8") + """
import json

catalog = {}
for path in Path('/maps').iterdir():
    if path.is_dir() and (path / 'main.yaml').is_file():
        try:
            catalog[path.name] = {"tiles": read_map_preview(path)}
        except ValueError as error:
            catalog[path.name] = {"error": str(error)}
print(json.dumps(catalog, allow_nan=False))
"""
MAP_VALIDATE_COMMAND = """
import signal
import sys
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory

signal.alarm(12)
from packages.duckiematrix_engine.map import Map

name, environments = sys.argv[1:]
if int(environments) > 1:
    # Expansion writes assets and removes the old context archive.
    with TemporaryDirectory() as tmp:
        copytree(Path('/maps') / name, Path(tmp) / name)
        Map.from_disk(name, tmp).expand_environments(int(environments))
else:
    Map.from_disk(name, '/maps')
"""


@dataclass(frozen=True)
class MapSelection:
    embedded: bool
    value: str

    @classmethod
    def from_request(cls, data: object, embedded_maps: tuple[str, ...], directory: Path) -> "MapSelection":
        if (not isinstance(data, dict) or type(data.get("embedded")) is not bool
                or not isinstance(data.get("value"), str) or not data["value"].strip()
                or "\0" in data["value"]):
            raise ValueError("Select an embedded map or enter a map directory.")
        value = data["value"]
        if data["embedded"]:
            if value not in embedded_maps:
                raise ValueError("That map is not embedded in this Engine.")
            return cls(True, value)

        try:
            path = (directory / Path(value).expanduser()).resolve(strict=True)
            if not path.is_dir() or not (path / "main.yaml").is_file():
                raise ValueError("The selected directory must contain main.yaml.")
        except (OSError, RuntimeError) as error:
            raise ValueError("The map directory could not be opened on the launcher host.") from error
        return cls(False, str(path))


@dataclass
class EngineSettings:
    mode: str = "realtime"
    environments: int = 1
    delta_t: float = 0.0  # Zero means no command-line override.

    @classmethod
    def from_command(cls, command: list[str]) -> EngineSettings:
        return cls(
            _option(command, "--mode", "realtime"),
            int(_option(command, "--environments", "1")),
            float(_option(command, "--delta-t", "0")),
        )

    @classmethod
    def from_request(cls, data: object) -> EngineSettings:
        if not isinstance(data, dict) or set(data) != {"mode", "environments", "delta_t"}:
            raise ValueError("Invalid simulation settings.")
        mode, environments, delta_t = data["mode"], data["environments"], data["delta_t"]
        if mode not in ("realtime", "gym"):
            raise ValueError("Choose Realtime or Gym mode.")
        if type(environments) is not int or not 1 <= environments <= 2_147_483_647:
            raise ValueError("Enter a positive whole number of environments.")
        try:
            valid_step = type(delta_t) in (float, int) and isfinite(delta_t) and delta_t >= 0
        except OverflowError:
            valid_step = False
        if not valid_step or (mode != "gym" and delta_t != 0):
            raise ValueError("A positive time step can only be set in Gym mode.")
        return cls(mode, environments, float(delta_t))

    def write_to(self, command: list[str], original: EngineSettings) -> None:
        if self.mode != original.mode:
            _set_option(command, "--mode", self.mode)
        if self.environments != original.environments:
            _set_option(command, "--environments", str(self.environments) if self.environments > 1 else None)
        if self.delta_t != original.delta_t:
            _set_option(command, "--delta-t", str(self.delta_t) if self.delta_t else None)


def _option(command: list[str], flag: str, default: str) -> str:
    return command[command.index(flag) + 1] if flag in command else default


def _set_option(command: list[str], flag: str, value: str | None) -> None:
    if flag in command:
        index = command.index(flag)
        if value is None:
            del command[index:index + 2]
        else:
            command[index + 1] = value
    elif value is not None:
        command.extend((flag, value))


@dataclass
class MapChange:
    ticket: str
    selection: MapSelection
    config: dict
    settings: EngineSettings
    expires: float
    result: dict | None = None


@dataclass
class EngineStop:
    ticket: str
    container: Container
    expires: float
    started: bool = False
    result: dict | None = None


class MapControl:
    def __init__(self, engine: MatrixEngine, directory: Path):
        if engine.config is None:
            raise ValueError("Map selection requires a configured Engine.")
        self.token = secrets.token_hex(32)
        self._engine = engine
        self._directory = directory
        self._condition = Condition()
        self._worker: Thread | None = None
        self._closed = False
        self._change: MapChange | None = None
        self._stop: EngineStop | None = None
        self._stopped = False

        self._base = deepcopy(engine.config)
        command = self._base["command"]
        self._launch_settings = self._settings = EngineSettings.from_command(command)
        self._gym_only = bool(self._base.get("environment", {}).get("DTSHELL_SHM_PATH"))
        self._can_replicate = (_option(command, "--renderers", "1") == "1"
                               and "--link" not in command and "--build-assets" not in command)
        self._name_index = command.index("--map") + 1 if "--map" in command else None
        self._current: MapSelection | None = None
        if self._name_index is None:
            if engine.engine is not None:
                raise ValueError("Startup map selection requires an Engine that has not started.")
            client = get_client_OLD()
            image = client.images.get(self._base["image"])
        else:
            if engine.engine is None:
                raise ValueError("Map switching requires a running Engine.")
            name = command[self._name_index]
            volumes = self._base.get("volumes", {})
            custom = next((path for path, mount in volumes.items()
                           if mount["bind"] == f"/maps/{name}"), None)
            if custom is None:
                self._current = MapSelection(True, name)
            else:
                self._current = MapSelection(False, str(Path(custom).resolve()))
                del volumes[custom]
            client, image = engine.engine.client, engine.engine.image
        self._factory = self._current

        # Pin the image for the catalog, validation and the subsequent Engine start.
        self._base["image"] = image.id
        self._containers = client.containers
        catalog = json.loads(self._probe(MAP_CATALOG_COMMAND))
        self._embedded_previews = {name: preview for name, preview in catalog.items()
                                   if SAFE_MAP_NAME.fullmatch(name)}
        self._embedded = tuple(sorted(self._embedded_previews))

    def status(self) -> dict:
        with self._condition:
            if self._stopped:
                return {"error": "The launcher-owned Engine was stopped."}
            return {
                "embedded_maps": self._embedded,
                "can_preview_maps": True,
                "current": asdict(self._current) if self._current is not None else None,
                "factory": asdict(self._factory) if self._factory is not None else None,
                "engine_settings": asdict(self._settings),
                "factory_engine_settings": asdict(EngineSettings(mode="gym" if self._gym_only else "realtime")),
                "can_replicate": self._can_replicate,
                "gym_only": self._gym_only,
                "awaiting_selection": self._current is None,
                "ready": self._current is not None and self._engine.engine is not None and self._worker is None,
            }

    def _probe(self, script: str, *args: str, mounts: list[Mount] | None = None) -> bytes:
        return self._containers.run(
            self._base["image"], ["-c", script, *args], entrypoint=["python3"],
            network_disabled=True, remove=True, mounts=mounts or [],
        )

    def preview(self, data: object) -> dict:
        selection = MapSelection.from_request(data, self._embedded, self._directory)
        if selection.embedded:
            preview = self._embedded_previews[selection.value]
            if "error" in preview:
                raise ValueError(preview["error"])
            return preview
        return {"tiles": read_map_preview(Path(selection.value))}

    def prepare(self, data: object) -> dict:
        selection = MapSelection.from_request(data, self._embedded, self._directory)
        with self._condition:
            if selection == self._current:
                raise ValueError("That map is already loaded.")
            return self._prepare(selection, self._settings)

    def prepare_engine_settings(self, data: object) -> dict:
        settings = EngineSettings.from_request(data)
        with self._condition:
            if self._current is None or self._engine.engine is None:
                raise ValueError("Start the Engine with a map first.")
            if settings == self._settings:
                raise ValueError("The Engine is already using these settings.")
            if self._gym_only and settings.mode != "gym":
                raise ValueError("This Engine uses shared memory and must stay in Gym mode.")
            if settings.environments > 1 and not self._can_replicate:
                raise ValueError("Replication requires one Renderer and no physical links or asset building.")
            return self._prepare(self._current, settings)

    def _prepare(self, selection: MapSelection, settings: EngineSettings) -> dict:
        if (self._closed or self._stopped or self._worker is not None
                or (self._change is not None and self._change.result is None
                    and monotonic() < self._change.expires)):
            raise ValueError("The Engine is already changing settings or shutting down.")
        config = deepcopy(self._base)
        name = selection.value
        mounts = []
        if not selection.embedded:
            name = Path(selection.value).name
            if not SAFE_MAP_NAME.fullmatch(name):
                name = "local-" + sha256(selection.value.encode()).hexdigest()[:12]
            mounts.append(Mount(
                target=f"/maps/{name}", source=selection.value, type="bind", read_only=True,
            ))
            config.setdefault("mounts", []).extend(mounts)
        command = config["command"]
        if self._name_index is None:
            command.extend(("--map", name))
        else:
            command[self._name_index] = name
        settings.write_to(command, self._launch_settings)
        try:
            if selection != self._current or settings.environments != self._settings.environments:
                self._probe(MAP_VALIDATE_COMMAND, name, str(settings.environments), mounts=mounts)
        except ContainerError as error:
            raise ValueError("The Engine rejected this map. Check its YAML layers and environment count.") from error
        except (DockerException, RequestException) as error:
            dtslogger.warning("Could not validate the selected map: %s", error)
            raise ValueError("Could not open this map in the Engine. Check the directory and Docker access.") from error
        self._change = MapChange(secrets.token_hex(16), selection, config, settings, monotonic() + 60)
        return {"ticket": self._change.ticket}

    def apply(self, ticket: object) -> dict:
        with self._condition:
            change = self._change
            if self._closed or self._stopped or self._engine.config is None:
                return {"error": "The Engine is shutting down. Restart dts matrix run."}
            if change is None or ticket != change.ticket:
                return {"error": "There is no matching Engine change. Open Settings and try again."}
            if change.result is not None:
                return change.result
            if self._worker is not None:
                return {"switching": True}
            if monotonic() >= change.expires:
                return {
                    "ready": self._current is not None and self._engine.engine is not None,
                    "error": "The Engine change expired. Open Settings and try again.",
                }
            previous = None if self._current is None else {**self._engine.config, "image": self._base["image"]}
            self._worker = Thread(target=self._switch, args=(change, previous))
            self._worker.start()
            return {"switching": True}

    def _restart(self, config: dict) -> None:
        if self._engine.engine is not None:
            self._engine.stop()
        self._engine.config = config
        if not self._engine.start():
            raise DockerException("The Engine could not start.")
        try:
            self._engine.wait_until_healthy(20)
        except TimeoutError as error:
            raise TimeoutError("The Engine did not become healthy within 20 seconds.") from error

    def _switch(self, change: MapChange, previous: dict | None) -> None:
        map_change = change.selection != self._current
        subject = "map" if map_change else "simulation settings"
        result = {"error": f"Could not change the {subject}. Restart dts matrix run."}
        try:
            self._restart(change.config)
        except (DockerException, RequestException, TimeoutError) as error:
            dtslogger.warning("Could not apply the selected %s: %s", subject, error)
            if previous is None:
                self._engine.stop()
                self._engine.config = self._base
                result = {"error": "Could not start the Engine with this map. Check dts matrix run and try again."}
            else:
                try:
                    self._restart(previous)
                except (DockerException, RequestException, TimeoutError) as restore_error:
                    dtslogger.error("Could not restore the previous %s: %s", subject, restore_error)
                else:
                    restored = "map was" if map_change else "simulation settings were"
                    result = {"ready": True, "error": f"The change failed. The previous {restored} restored."}
        else:
            result = {"ready": True}
        finally:
            with self._condition:
                if "error" not in result:
                    self._current = change.selection
                    self._settings = change.settings
                    if self._factory is None:
                        self._factory = change.selection
                change.result = result
                self._worker = None
                self._condition.notify_all()

    def prepare_stop(self) -> dict:
        with self._condition:
            container = self._engine.engine
            if self._closed or self._worker is not None or container is None:
                raise ValueError("The launcher-owned Engine is unavailable or changing maps.")
            self._stop = EngineStop(secrets.token_hex(16), container, monotonic() + 120)
            return {"ticket": self._stop.ticket}

    def stop(self, ticket: object) -> dict:
        with self._condition:
            stop = self._stop
            if stop is None or ticket != stop.ticket:
                raise ValueError("The Engine stop request is invalid. No Engine was stopped.")
            if stop.result is not None:
                return stop.result
            if stop.started:
                return {"switching": True}
            if (self._closed or self._worker is not None or stop.container is not self._engine.engine
                    or monotonic() >= stop.expires):
                raise ValueError("The previous Engine changed or the stop request expired. No Engine was stopped.")
            stop.started = True
            self._worker = Thread(target=self._stop_engine, args=(stop,))
            self._worker.start()
            return {"switching": True}

    def _stop_engine(self, stop: EngineStop) -> None:
        result = {"error": "Could not confirm that the previous Engine stopped. Check dts matrix run."}
        try:
            self._engine.stop()
            try:
                stop.container.reload()
            except NotFound:
                pass
            else:
                if stop.container.status not in ("exited", "dead"):
                    raise DockerException(f"Previous Engine status: {stop.container.status}.")
        except (DockerException, RequestException) as error:
            dtslogger.warning("Could not confirm Engine shutdown: %s", error)
            # MatrixEngine.stop() may clear its handle even if Docker did not stop the container.
            self._engine.engine = stop.container
        else:
            result = {"ready": True}
        finally:
            with self._condition:
                self._stopped = result.get("ready", False)
                stop.result = result
                self._worker = None

    def wait_for_engine(self) -> bool:
        while True:
            with self._condition:
                # A failed first start leaves the picker and browser server available for another Save.
                self._condition.wait_for(lambda: self._closed or self._current is not None)
                if self._closed:
                    return False
                worker, container = self._worker, self._engine.engine
                if self._stopped:
                    return False
                if worker is None and self._change and self._change.result and not self._change.result.get("ready"):
                    # Leave the browser server up so the Renderer can report the failure.
                    return False
            if worker is not None:
                worker.join()
                continue
            if container is None:
                return True
            try:
                container.wait()
            except (DockerException, RequestException) as error:
                dtslogger.debug("Engine wait ended: %s", error)
            with self._condition:
                if self._stopped:
                    return False
                if self._worker is None and container is self._engine.engine:
                    self._closed = True
                    return True

    def close(self) -> None:
        with self._condition:
            self._closed = True
            worker = self._worker
            self._condition.notify_all()
        if worker is not None:
            worker.join()


def serve_launcher_request(request: BaseHTTPRequestHandler) -> bool:
    if request.path not in (MAP_CONTROL_PATH, MAP_PREVIEW_PATH, ENGINE_STOP_PATH):
        return False
    control = getattr(request.server, "map_control", None)
    if not isinstance(control, MapControl):
        request.send_error(HTTPStatus.NOT_FOUND)
        return True
    token = request.headers.get(MAP_CONTROL_HEADER, "")
    origin = request.headers.get("Origin")
    host = request.headers.get("Host")
    control_host = getattr(request.server, "map_control_host", None)
    if (not secrets.compare_digest(token.encode(), control.token.encode())
            or host != control_host or (origin is not None and origin != f"http://{control_host}")):
        request.send_error(HTTPStatus.FORBIDDEN)
        return True

    stopping = request.path == ENGINE_STOP_PATH
    previewing = request.path == MAP_PREVIEW_PATH
    if (stopping or previewing) and request.command != "POST":
        request.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
        return True
    status = HTTPStatus.OK
    if request.command == "GET":
        result = control.status()
    else:
        try:
            length = int(request.headers.get("Content-Length", "0"))
            if not 0 < length <= 32 * 1024 or request.headers.get_content_type() != "application/json":
                raise ValueError
            request.connection.settimeout(5)
            data = json.loads(request.rfile.read(length))
        except (UnicodeError, ValueError, TimeoutError):
            status, result = HTTPStatus.BAD_REQUEST, {"error": "Invalid Engine control request."}
        else:
            try:
                if previewing:
                    result = control.preview(data)
                elif stopping:
                    if not isinstance(data, dict) or data.keys() - {"ticket"}:
                        raise ValueError("Invalid Engine stop request.")
                    result = control.stop(data["ticket"]) if data else control.prepare_stop()
                elif isinstance(data, dict) and data.keys() == {"ticket"}:
                    result = control.apply(data["ticket"])
                elif isinstance(data, dict) and data.keys() == {"engine_settings"}:
                    result = control.prepare_engine_settings(data["engine_settings"])
                else:
                    result = control.prepare(data)
            except ValueError as error:
                status, result = HTTPStatus.BAD_REQUEST, {"error": str(error)}
            else:
                if result.get("switching"):
                    status = HTTPStatus.ACCEPTED
    payload = json.dumps(result).encode()
    request.send_response(status)
    request.send_header("Content-Type", "application/json")
    request.send_header("Content-Length", str(len(payload)))
    request.send_header("Cache-Control", "no-store")
    request.end_headers()
    request.wfile.write(payload)
    return True


class MapControlRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not serve_launcher_request(self):
            self.send_error(HTTPStatus.NOT_FOUND)

    do_POST = do_GET


class MapControlHTTPServer(HTTPServer):
    def __init__(self, control: MapControl):
        self.map_control = control
        super().__init__(("127.0.0.1", 0), MapControlRequestHandler)
        self.map_control_host = f"127.0.0.1:{self.server_port}"
