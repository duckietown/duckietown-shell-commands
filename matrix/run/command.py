import argparse
import logging
import os
import signal
import subprocess
import time
from threading import Thread
from types import SimpleNamespace
from typing import Optional

from docker.models.containers import Container

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.docker_utils import DEFAULT_REGISTRY, get_client
from utils.duckiematrix_utils import \
    APP_NAME, \
    DCSS_SPACE_NAME, \
    APP_RELEASES_DIR, \
    get_most_recent_version_installed, \
    remote_zip_obj, \
    get_latest_version, get_path_to_binary

from utils.duckietown_utils import get_distro_version
from utils.misc_utils import versiontuple


DUCKIEMATRIX_ENGINE_IMAGE_FMT = "{registry}/duckietown/dt-duckiematrix:{distro}-amd64"

DUCKIEMATRIX_ENGINE_IMAGE_CONFIG = {
    "network_mode": "host"
}
MAX_RENDERERS = 4


class DTCommand(DTCommandAbs):

    help = f'Runs the {APP_NAME} application'

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-v",
            "--version",
            default=None,
            type=str,
            help="Run a specific version"
        )
        parser.add_argument(
            "-s",
            "--standalone",
            default=False,
            action="store_true",
            help="Run both engine and renderer"
        )
        parser.add_argument(
            "--engine-only",
            default=False,
            action="store_true",
            help="(Advanced) Run both engine and renderer"
        )
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
            "-vk",
            "--force-vulkan",
            default=False,
            action="store_true",
            help="(Advanced) Force the use of the Vulkan rendering API"
        )
        parser.add_argument(
            "-gl",
            "--force-opengl",
            default=False,
            action="store_true",
            help="(Advanced) Force the use of the OpenGL rendering API"
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
    def command(shell: DTShell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand._parse_args(args)
        # ---
        # check for conflicting arguments
        # - standalone VS engine-only
        if parsed.standalone and parsed.engine_only:
            dtslogger.error("Standalone (-s/--standalone) and Engine-Only (--engine-only) "
                            "modes cannot be used together.")
            return
        run_engine = parsed.standalone or parsed.engine_only
        run_app = not parsed.engine_only
        # - sandbox VS engine-only
        if parsed.standalone and parsed.engine_only:
            dtslogger.error("Sandbox (--sandbox) and Engine-Only (--engine-only) "
                            "modes cannot be used together.")
            return
        # - map VS sandbox
        if parsed.sandbox and parsed.map is not None:
            dtslogger.error("Sandbox mode (--sandbox) and custom map (-m/--map) "
                            "cannot be used together.")
            return
        # - vulkan VS opengl
        if parsed.force_vulkan and parsed.force_opengl:
            dtslogger.error("You cannot use --force-vulkan and --force-opengl together.")
            return
        # make sure the map is given (in standalone mode)
        if (parsed.standalone or parsed.engine_only) and not parsed.map and not parsed.sandbox:
            dtslogger.error("You need to specify a map with -m/--map when running in "
                            "either Standalone or Engine-Only mode.")
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
        # run the engine if in standalone or engine mode
        engine: Optional[Container] = None
        if run_engine:
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
            # create docker client
            docker = get_client()
            # run engine container
            dtslogger.debug(engine_config)
            engine = docker.containers.run(**engine_config)
            # attach ctrl-c handler

            def on_sigint(*_):
                # noinspection PyBroadException
                try:
                    dtslogger.info("Cleaning up containers...")
                    engine.stop()
                except Exception:
                    dtslogger.warn("We couldn't ensure that the engine container was removed. "
                                   "Just a heads up that it might still be running.")

            # capture SIGINT and abort
            signal.signal(signal.SIGINT, on_sigint)

            # print out logs if we are in verbose mode
            if parsed.verbose:
                def verbose_reader(stream):
                    try:
                        while True:
                            line = next(stream).decode("utf-8")
                            print(line, end="")
                    except StopIteration:
                        dtslogger.info('Engine container terminated.')

                container_stream = engine.logs(stream=True)
                Thread(target=verbose_reader, args=(container_stream,), daemon=True).start()

        # run the app
        if run_app:
            version = parsed.version if parsed.version else get_most_recent_version_installed()
            dtslogger.debug(f"Will try to run {version}...")
            # make sure the app is installed
            if version is None:
                extra = f"version v{parsed.version} " if parsed.version is not None else ""
                dtslogger.error(f"The app {extra}was not found on your disk.\n"
                                f"Use the command `dts matrix install` to download it.")
                return
            # app configuration
            app_bin = get_path_to_binary(version)
            app_config = [
                "-logfile", "/dev/stdout"
            ]
            # graphics API
            if parsed.force_opengl:
                app_config += ["-force-opengl"]
            elif parsed.force_vulkan:
                app_config += ["-force-vulkan"]
            else:
                # by default we use Vulkan
                app_config += ["-force-vulkan"]
            # wait for the engine to become healthy
            # TODO: not sure how to get the container's health
            # run the app
            app_cmd = [app_bin] + app_config
            dtslogger.debug(f"$ > {app_cmd}")
            time.sleep(5)
            subprocess.check_call(app_cmd, shell=True)

            if run_engine:
                on_sigint()

            # thread = Thread(
            #     target=subprocess.Popen,
            #     args=(app_cmd,),
            #     kwargs={"shell": True},
            #     daemon=True
            # )
            # thread.start()
            # # attach to app if we are not attaching to the
            # if not parsed.verbose:
            #     thread.join()


    @staticmethod
    def complete(shell, word, line):
        return []
