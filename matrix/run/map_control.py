"""Map selection for an Engine owned by the local Duckiematrix launcher."""

from __future__ import annotations

import json
import re
import secrets
from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Lock, Thread
from time import monotonic

from docker.errors import ContainerError, DockerException
from docker.types import Mount
from requests.exceptions import RequestException

from dt_shell import dtslogger

from ..engine.run.command import MatrixEngine
from .map_preview import read_map_preview


MAP_CONTROL_PATH = "/__duckiematrix/map"
MAP_PREVIEW_PATH = "/__duckiematrix/map/preview"
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
class MapChange:
    ticket: str
    selection: MapSelection
    config: dict
    expires: float
    result: dict | None = None


class MapControl:
    def __init__(self, engine: MatrixEngine, directory: Path):
        if engine.config is None or engine.engine is None:
            raise ValueError("Map selection requires a running Engine.")
        self.token = secrets.token_hex(32)
        self._engine = engine
        self._directory = directory
        self._lock = Lock()
        self._worker: Thread | None = None
        self._closed = False
        self._change: MapChange | None = None

        self._base = deepcopy(engine.config)
        self._name_index = self._base["command"].index("--map") + 1
        name = self._base["command"][self._name_index]
        volumes = self._base.get("volumes", {})
        custom = next((path for path, mount in volumes.items()
                       if mount["bind"] == f"/maps/{name}"), None)
        if custom is None:
            self._current = MapSelection(True, name)
        else:
            self._current = MapSelection(False, str(Path(custom).resolve()))
            del volumes[custom]
        self._factory = self._current

        # Inspect the packaged image, not the live /maps mount, which can shadow an embedded map.
        self._base["image"] = engine.engine.image.id
        self._containers = engine.engine.client.containers
        catalog = json.loads(self._probe(MAP_CATALOG_COMMAND))
        self._embedded_previews = {name: preview for name, preview in catalog.items()
                                   if SAFE_MAP_NAME.fullmatch(name)}
        self._embedded = tuple(sorted(self._embedded_previews))

    def status(self) -> dict:
        with self._lock:
            return {
                "embedded_maps": self._embedded,
                "can_preview_maps": True,
                "current": asdict(self._current),
                "factory": asdict(self._factory),
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
        with self._lock:
            if (self._closed or self._worker is not None
                    or (self._change is not None and self._change.result is None
                        and monotonic() < self._change.expires)):
                raise ValueError("The Engine is already changing maps or shutting down.")
            if selection == self._current:
                raise ValueError("That map is already loaded.")
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
            config["command"][self._name_index] = name
            command = config["command"]
            environments = command[command.index("--environments") + 1] if "--environments" in command else "1"
            try:
                self._probe(MAP_VALIDATE_COMMAND, name, environments, mounts=mounts)
            except ContainerError as error:
                raise ValueError("The Engine rejected this map. Check its YAML layers and environment count.") from error
            except (DockerException, RequestException) as error:
                dtslogger.warning("Could not validate the selected map: %s", error)
                raise ValueError("Could not open this map in the Engine. Check the directory and Docker access.") from error
            self._change = MapChange(secrets.token_hex(16), selection, config, monotonic() + 60)
            return {"ticket": self._change.ticket}

    def apply(self, ticket: object) -> dict:
        with self._lock:
            change = self._change
            if self._worker is not None:
                return {"switching": True}
            if self._closed or self._engine.config is None:
                return {"error": "The Engine is shutting down. Restart dts matrix run."}
            if change is not None and change.result is not None:
                if ticket == change.ticket or not change.result.get("ready"):
                    return change.result
            if change is None or ticket != change.ticket or monotonic() >= change.expires:
                return {"ready": True, "error": "The map selection expired. Open the Map panel and try again."}
            previous = {**self._engine.config, "image": self._base["image"]}
            self._worker = Thread(target=self._switch, args=(change, previous))
            self._worker.start()
            return {"switching": True}

    def _restart(self, config: dict) -> None:
        self._engine.stop()
        self._engine.config = config
        if not self._engine.start():
            raise DockerException("The Engine could not start.")
        try:
            self._engine.wait_until_healthy(20)
        except TimeoutError as error:
            raise TimeoutError("The Engine did not become healthy within 20 seconds.") from error

    def _switch(self, change: MapChange, previous: dict) -> None:
        result = {"error": "Could not change maps. Restart dts matrix run."}
        try:
            self._restart(change.config)
        except (DockerException, RequestException, TimeoutError) as error:
            dtslogger.warning("Could not load the selected map: %s", error)
            try:
                self._restart(previous)
            except (DockerException, RequestException, TimeoutError) as restore_error:
                dtslogger.error("Could not restore the previous map: %s", restore_error)
            else:
                result = {"ready": True, "error": "The selected map could not load. The previous map was restored."}
        else:
            result = {"ready": True}
        finally:
            with self._lock:
                if "error" not in result:
                    self._current = change.selection
                change.result = result
                self._worker = None

    def wait_for_engine(self) -> bool:
        while True:
            with self._lock:
                worker, container = self._worker, self._engine.engine
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
            with self._lock:
                if self._worker is None and container is self._engine.engine:
                    self._closed = True
                    return True

    def close(self) -> None:
        with self._lock:
            self._closed = True
            worker = self._worker
        if worker is not None:
            worker.join()


def serve_map_request(request: BaseHTTPRequestHandler) -> bool:
    if request.path not in (MAP_CONTROL_PATH, MAP_PREVIEW_PATH):
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

    previewing = request.path == MAP_PREVIEW_PATH
    if previewing and request.command != "POST":
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
            status, result = HTTPStatus.BAD_REQUEST, {"error": "Invalid map selection request."}
        else:
            try:
                if previewing:
                    result = control.preview(data)
                else:
                    result = (control.apply(data["ticket"])
                              if isinstance(data, dict) and "ticket" in data else control.prepare(data))
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
        if not serve_map_request(self):
            self.send_error(HTTPStatus.NOT_FOUND)

    do_POST = do_GET


class MapControlHTTPServer(HTTPServer):
    def __init__(self, control: MapControl):
        self.map_control = control
        super().__init__(("127.0.0.1", 0), MapControlRequestHandler)
        self.map_control_host = f"127.0.0.1:{self.server_port}"
