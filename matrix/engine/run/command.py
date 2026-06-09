import argparse
import logging
import os
import platform
import subprocess
import time
from threading import Thread
from typing import Optional, Dict

import yaml
from docker.models.containers import Container

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.docker_utils import DEFAULT_REGISTRY, get_client_OLD, pull_image_OLD, get_endpoint_architecture
from utils.duckiematrix_utils import \
    APP_NAME

DUCKIEMATRIX_ENGINE_IMAGE_FMT = "{registry}/duckietown/dt-duckiematrix:{distro}-{arch}"
EXTERNAL_SHUTDOWN_REQUEST = "===REQUESTED-EXTERNAL-SHUTDOWN==="

DUCKIEMATRIX_ENGINE_IMAGE_CONFIG = {}
MAX_RENDERERS = 4

DEFAULT_STATIC_NETWORK_PORTS: Dict[str, int] = {
    "world-control-out-port": 7501,
    "matrix-control-out-port": 7502,
    "matrix-websocket-bridge-control-out-port": 7503,
    "matrix-websocket-bridge-data-out-port": 7504,
    "matrix-websocket-bridge-data-in-port": 7505,
    "matrix-data-out-port": 17510,
    "matrix-data-in-port": 17511,
    "world-data-out-port": 17512,
    "world-data-in-port": 17513,
    "robot-data-out-port": 17514,
    "robot-data-in-port": 17515,
    "layer-data-out-port": 17516,
    "layer-data-in-port": 17517,
}


class MatrixEngine:

    def __init__(self):
        self.config: Optional[dict] = None
        self.engine: Optional[Container] = None
        self.verbose = False

    @property
    def is_configured(self) -> bool:
        return self.config is not None

    @property
    def is_running(self) -> bool:
        return self.engine is not None and self.engine.status == "running"

    def configure(self, shell: DTShell, parsed: argparse.Namespace) -> bool:
        self.verbose = parsed.verbose
        # check for conflicting arguments
        # - map VS sandbox
        sandbox = parsed.sandbox
        map = parsed.map
        if sandbox and map is not None:
            dtslogger.error("Sandbox mode (--sandbox) and custom map (-m/--map) "
                            "cannot be used together.")
            return False
        # make sure the map is given (when not in sandbox standalone mode)
        if not map and not sandbox:
            dtslogger.error("You need to specify a map with -m/--map or choose to run in "
                            "--sandbox mode to use a default map.")
            return False
        # make sure the map path exists when given
        embedded = parsed.embedded
        if sandbox:
            embedded = True
            map_name = "sandbox"
        else:
            map_name = os.path.basename(map.rstrip("/")) if map is not None else None
        map_dir = os.path.abspath(map) if map is not None and not embedded else None
        if map_dir is not None and not os.path.isdir(map_dir):
            dtslogger.error(f"The given path '{map_dir}' does not exist.")
            return False
        # make sure the map itself exists when given
        if map_dir is not None and not os.path.isfile(os.path.join(map_dir, "main.yaml")):
            dtslogger.error(f"The given path '{map_dir}' does not contain a valid map.")
            return False
        # make sure the time step is only given in gym mode
        if parsed.delta_t is not None and not parsed.simulation:
            dtslogger.error("You can specify a --delta-t only when running with "
                            "--gym/--simulation.")
            return False
        # configure engine
        dtslogger.info("Configuring Engine...")
        docker_registry = os.environ.get("DOCKER_REGISTRY", DEFAULT_REGISTRY)
        if docker_registry != DEFAULT_REGISTRY:
            dtslogger.warning(f"Using custom DOCKER_REGISTRY='{docker_registry}'.")
        # compile engine image name
        engine_image = DUCKIEMATRIX_ENGINE_IMAGE_FMT.format(
            registry=docker_registry,
            distro=shell.profile.distro.name,
            arch=get_endpoint_architecture()
        )
        # check if a default-named engine container already exists
        engine_container_name: str = parsed.engine_name if parsed.engine_name else "dts-matrix-engine"
        if not parsed.engine_name:
            docker = get_client_OLD()
            existing = [
                c for c in docker.containers.list(all=True, filters={"name": "dts-matrix-engine"})
                if c.name == "dts-matrix-engine"
            ]
            if existing:
                dtslogger.error(
                    "A Duckiematrix engine container named 'dts-matrix-engine' already exists.\n"
                    "To launch a second instance, provide an explicit name and port offset, e.g.:\n"
                    "  --engine-name dts-matrix-engine-1 --port-offset 10\n"
                    "Adjust the port offset as needed to avoid conflicts."
                )
                return False
        # engine container configuration
        engine_config = {
            "image": engine_image,
            "command": ["--"],
            "detach": True,
            "stdout": True,
            "stderr": True,
            "environment": {
                "PYTHONUNBUFFERED": "1",
                "IMPERSONATE_UID": os.getuid(),
                "IMPERSONATE_GID": os.getgid(),
            },
            "ports": {},
            "name": engine_container_name
        }
        engine_config.update(DUCKIEMATRIX_ENGINE_IMAGE_CONFIG)
        # set the mode
        engine_mode = "realtime" if not parsed.simulation else "gym"
        engine_config["command"] += ["--mode", engine_mode]
        # set the number of renderers
        num_renderers = min(max(1, parsed.renderers), MAX_RENDERERS)
        engine_config["command"] += ["--renderers", str(num_renderers)]
        # set the map
        if embedded:
            engine_config["command"] += [
                "--maps-dir", "/maps",
                "--map", map_name
            ]
        else:
            map_location = f"/maps/{map_name}"
            engine_config["volumes"] = {
                map_dir: {
                    'bind': map_location,
                    'mode': 'rw' if parsed.build_assets else 'ro'
                }
            }
            engine_config["command"] += ["--map", map_name]
        # delta t
        if parsed.delta_t is not None:
            engine_config["command"] += ["--delta-t", str(parsed.delta_t)]
        # robot links
        for link in parsed.links:
            engine_config["command"] += ["--link", *link]
        # build assets
        if parsed.build_assets:
            engine_config["command"] += ["--build-assets"]
        # debug mode
        if dtslogger.level <= logging.DEBUG:
            engine_config["command"] += ["--debug"]
        # (MacOS only) privileged mode
        if platform.system() == "Darwin":
            engine_config["privileged"] = True
        # configure ports
        expose_ports: bool = parsed.expose_ports or platform.system() == "Darwin"
        static_ports: bool = parsed.static_ports
        port_offset: int = parsed.port_offset
        if port_offset:
            static_ports = True
        # expose ports defined in the connector_ports layer + static ports
        if expose_ports or static_ports:
            connector_ports: Dict[str, int] = {}
            if map_dir is not None:
                # we are using a custom map
                connector_ports_fpath: str = os.path.join(map_dir, "connector_ports.yaml")
                if os.path.isfile(connector_ports_fpath):
                    with open(connector_ports_fpath, "rt") as fin:
                        connector_ports = yaml.safe_load(fin).get("connector_ports", {})
            else:
                # we are using an embedded map
                connector_ports = DEFAULT_STATIC_NETWORK_PORTS
            # add ports that are not already defined
            for name, port in DEFAULT_STATIC_NETWORK_PORTS.items():
                if (name not in connector_ports) or static_ports:
                    connector_ports[name] = port
            # add ports to the engine configuration
            for name, port in connector_ports.items():
                port += port_offset
                # expose port to the host
                if expose_ports:
                    engine_config["ports"][f"{port}/tcp"] = port
                # configure the engine to use this port
                engine_config["command"] += [f"--{name}", str(port)]
        # (Linux only) use network mode host
        if platform.system() == "Linux" and not parsed.expose_ports:
            engine_config["network_mode"] = "host"
        # profiler
        if parsed.profiler:
            engine_config["command"] += ["--profiler"]
        # run engine container
        dtslogger.debug(engine_config)
        self.config = engine_config
        dtslogger.info("Engine configured!")
        return True

    def stop(self):
        if self.config is None:
            raise ValueError("Configure the engine first.")
        dtslogger.info("Cleaning up containers...")
        if self.is_running:
            # noinspection PyBroadException
            try:
                self.engine.stop()
            except Exception:
                dtslogger.warn("We couldn't ensure that the engine container was stopped. "
                               "Just a heads up that it might still be running.")
        # noinspection PyBroadException
        try:
            self.engine.remove()
        except Exception:
            dtslogger.warn("We couldn't ensure that the engine container was removed. "
                           "Just a heads up that it might still be there.")
        self.engine = None

    def pull(self):
        # download engine image
        image: str = self.config["image"]
        dtslogger.info(f"Download image '{image}'...")
        pull_image_OLD(image)
        dtslogger.info(f"Image downloaded!")

    def start(self, join: bool = False) -> bool:
        if self.config is None:
            raise ValueError("Configure the engine first.")
        # create docker client
        docker = get_client_OLD()
        # run
        try:
            dtslogger.info("Launching Engine...")
            self.engine = docker.containers.run(**self.config)
            # print out logs if we are in verbose mode
            if self.verbose:
                def verbose_reader(stream):
                    try:
                        while True:
                            line = next(stream).decode("utf-8")
                            print(line, end="")
                    except StopIteration:
                        dtslogger.info('Engine container terminated.')

                container_stream = self.engine.logs(stream=True)
                Thread(target=verbose_reader, args=(container_stream,), daemon=True).start()
        except BaseException as e:
            dtslogger.error(f"An error occurred while running the engine. The error reads:\n{e}")
            self.stop()
            return False
        # make sure the engine is running
        try:
            self.engine.reload()
        except BaseException as e:
            dtslogger.error(f"An error occurred while running the engine. The error reads:\n{e}")
            self.stop()
            return False
        # join (if needed)
        return True if not join else self.join()

    def wait_until_healthy(self, timeout: int = -1):
        if self.config is None:
            raise ValueError("Configure the engine first.")
        if self.engine is None:
            raise ValueError("Run the engine first.")
        # ---
        stime = time.time()
        while True:
            _, health = self.engine.exec_run("cat /health", stderr=False)
            if health == b"healthy":
                return
            # ---
            time.sleep(1)
            if 0 < timeout < time.time() - stime:
                raise TimeoutError()

    def join(self) -> bool:
        try:
            # wait for the engine to terminate
            self.engine.wait()
        except BaseException:
            return False
        finally:
            self.stop()
        return True


class DTCommand(DTCommandAbs):

    help = f'Runs the {APP_NAME} engine'

    @staticmethod
    def make_engine(shell: DTShell, parsed: argparse.Namespace, use_defaults: bool = False) \
            -> Optional[MatrixEngine]:
        if use_defaults:
            parsed = DTCommand._resolve_parsed([], parsed)
        # create engine
        engine = MatrixEngine()
        configured = engine.configure(shell, parsed)
        if not configured:
            return None
        # ---
        return engine

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        # ---
        engine = DTCommand.make_engine(shell, parsed)
        if engine is None:
            return
        # ---
        if not parsed.no_pull:
            engine.pull()
        engine.start()
        engine.join()

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
