import argparse
import logging
import os
import subprocess
import time
from threading import Thread
from typing import Optional

from docker.models.containers import Container

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.docker_utils import DEFAULT_REGISTRY, get_client
from utils.duckiematrix_utils import \
    APP_NAME
from utils.duckietown_utils import get_distro_version

DUCKIEMATRIX_ENGINE_IMAGE_FMT = "{registry}/duckietown/dt-duckiematrix:{distro}-amd64"
EXTERNAL_SHUTDOWN_REQUEST = "===REQUESTED-EXTERNAL-SHUTDOWN==="

DUCKIEMATRIX_ENGINE_IMAGE_CONFIG = {
    "network_mode": "host"
}
MAX_RENDERERS = 4


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

    def configure(self, shell: DTShell, parsed: argparse.Namespace) -> Optional[dict]:
        self.verbose = parsed.verbose
        # check for conflicting arguments
        # - map VS sandbox
        if parsed.sandbox and parsed.map is not None:
            dtslogger.error("Sandbox mode (--sandbox) and custom map (-m/--map) "
                            "cannot be used together.")
            return
        # make sure the map is given (when not in sandbox standalone mode)
        if not parsed.map and not parsed.sandbox:
            dtslogger.error("You need to specify a map with -m/--map or choose to run in "
                            "--sandbox mode to use a default map.")
            return
        # make sure the map path exists when given
        map_dir = os.path.abspath(parsed.map) if parsed.map is not None else None
        map_name = os.path.basename(parsed.map) if parsed.map is not None else None
        if map_dir is not None and not os.path.isdir(map_dir):
            dtslogger.error(f"The given path '{map_dir}' does not exist.")
            return
        # make sure the map itself exists when given
        if map_dir is not None and not os.path.isdir(os.path.join(map_dir, "main.yaml")):
            dtslogger.error(f"The given path '{map_dir}' does not contain a valid map.")
            return
        # make sure the time step is only given in gym mode
        if parsed.delta_t is not None and not parsed.simulation:
            dtslogger.error("You can specify a --delta-t only when running with "
                            "--gym/--simulation.")
            return
        # configure engine
        dtslogger.info("Configuring Engine...")
        docker_registry = os.environ.get("DOCKER_REGISTRY", DEFAULT_REGISTRY)
        if docker_registry != DEFAULT_REGISTRY:
            dtslogger.warning(f"Using custom DOCKER_REGISTRY='{docker_registry}'.")
        # compile engine image name
        engine_image = DUCKIEMATRIX_ENGINE_IMAGE_FMT.format(
            registry=docker_registry,
            distro=get_distro_version(shell)
        )
        # engine container configuration
        engine_config = {
            "image": engine_image,
            "command": ["--"],
            "auto_remove": True,
            "detach": True,
            "stdout": True,
            "stderr": True,
            "environment": {
                "PYTHONUNBUFFERED": "1"
            },
            "name": f"dts-matrix-engine"
        }
        engine_config.update(DUCKIEMATRIX_ENGINE_IMAGE_CONFIG)
        # set the mode
        engine_mode = "realtime" if not parsed.simulation else "gym"
        engine_config["command"] += ["--mode", engine_mode]
        # set the number of renderers
        num_renderers = min(max(1, parsed.renderers), MAX_RENDERERS)
        engine_config["command"] += ["--renderers", str(num_renderers)]
        # set the map
        if parsed.sandbox:
            engine_config["command"] += [
                "--maps-dir", "/embedded_maps",
                "--map", "sandbox"
            ]
        else:
            map_location = f"/maps/{map_name}"
            engine_config["volumes"] = {
                map_dir: {
                    'bind': map_location,
                    'mode': 'ro'
                }
            }
            engine_config["command"] += ["--map", map_name]
        # delta t
        if parsed.delta_t is not None:
            engine_config["command"] += ["--delta-t", parsed.delta_t]
        # robot links
        for link in parsed.links:
            engine_config["command"] += ["--link", *link]
        # debug mode
        if dtslogger.level <= logging.DEBUG:
            engine_config["command"] += ["--debug"]
        # run engine container
        dtslogger.debug(engine_config)
        self.config = engine_config
        dtslogger.info("Engine configured!")

    def stop(self):
        if self.config is None:
            raise ValueError("Configure the engine first.")
        if not self.is_running:
            return
        # noinspection PyBroadException
        try:
            dtslogger.info("Cleaning up containers...")
            self.engine.stop()
        except Exception:
            dtslogger.warn("We couldn't ensure that the engine container was removed. "
                           "Just a heads up that it might still be running.")
        self.engine = None

    def start(self, join: bool = False) -> bool:
        if self.config is None:
            raise ValueError("Configure the engine first.")
        # create docker client
        docker = get_client()
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
        except BaseException:
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
            self.engine.reload()
            if self.engine.status not in ["created", "running"]:
                raise ValueError(f"Container was found in status '{self.engine.status}'")
            attrs = self.engine.attrs
            if "State" in attrs and "Health" in attrs["State"]:
                health = attrs["State"]["Health"]["Status"]
                # check health
                if health == "healthy":
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
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-m",
            "--map",
            default=None,
            type=str,
            help="Directory containing the map to load"
        )
        parser.add_argument(
            "--sandbox",
            default=False,
            action="store_true",
            help="Run in a sandbox map"
        )
        parser.add_argument(
            "-n",
            "--renderers",
            default=1,
            type=int,
            help="(Advanced) Number of renderers to run"
        )
        parser.add_argument(
            "--gym",
            "--simulation",
            dest="simulation",
            default=False,
            action="store_true",
            help="Run in simulation mode"
        )
        parser.add_argument(
            "-t", "-dt",
            "--delta-t",
            default=None,
            type=float,
            help="Time step (gym mode only)",
        )
        parser.add_argument(
            "--link",
            dest="links",
            nargs=2,
            action="append",
            default=[],
            metavar=("matrix", "world"),
            help="Link robots inside the matrix to robots outside",
        )
        parser.add_argument(
            "-vv",
            "--verbose",
            default=False,
            action="store_true",
            help="Run in verbose mode"
        )
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def make_engine(shell: DTShell, parsed: argparse.Namespace, use_defaults: bool = False) \
            -> MatrixEngine:
        if use_defaults:
            defaults = DTCommand._parse_args([])
            defaults.__dict__.update(parsed.__dict__)
            parsed = defaults
        # create engine
        engine = MatrixEngine()
        engine.configure(shell, parsed)
        return engine

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand._parse_args(args)
        # ---
        engine = DTCommand.make_engine(shell, parsed)
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
