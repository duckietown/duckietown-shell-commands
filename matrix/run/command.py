import time
from pathlib import Path

import argparse
import subprocess
import platform
from typing import Optional, Callable

from dt_shell import DTCommandAbs, dtslogger, DTShell
from ..engine.run.command import MatrixEngine
from utils.duckiematrix_utils import \
    APP_NAME, \
    get_most_recent_version_installed, \
    get_path_to_binary

EXTERNAL_SHUTDOWN_REQUEST: str = "===REQUESTED-EXTERNAL-SHUTDOWN==="
IS_MACOS: bool = platform.system() == "Darwin"


class DTCommand(DTCommandAbs):

    help = f'Runs the {APP_NAME} renderer'

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
            "-S",
            "--standalone",
            default=False,
            action="store_true",
            help="Run both engine and renderer"
        )
        parser.add_argument(
            "-m",
            "--map",
            default=None,
            type=str,
            help="Directory containing the map to load"
        )
        parser.add_argument(
            "-e",
            "--engine",
            dest="engine_hostname",
            default=None,
            type=str,
            help="Hostname or IP address of the engine to connect to"
        )
        parser.add_argument(
            "-r",
            "--renderer-id",
            default=None,
            type=int,
            help="(Advanced) Use a specific `renderer_id`"
        )
        parser.add_argument(
            "-k",
            "--renderer-key",
            default=None,
            type=str,
            help="(Advanced) Authenticate the renderer using a key"
        )
        parser.add_argument(
            "-s",
            "--sandbox",
            default=False,
            action="store_true",
            help="Run in a sandbox map"
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
            "--no-pull",
            default=False,
            action="store_true",
            help="Do not attempt to update the engine container image"
        )
        parser.add_argument(
            "--expose-ports",
            default=False,
            action="store_true",
            help="Expose all the ports with the host"
        )
        parser.add_argument(
            "--static-ports",
            default=False,
            action="store_true",
            help="Assign default values to all the ports"
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
        run_engine: bool = parsed.standalone
        run_renderer: bool = True
        # - map VS sandbox
        if parsed.sandbox and parsed.map is not None:
            dtslogger.error("Sandbox mode (--sandbox) and custom map (-m/--map) "
                            "cannot be used together.")
            return
        # - vulkan VS opengl
        if parsed.force_vulkan and parsed.force_opengl:
            dtslogger.error("You cannot use --force-vulkan and --force-opengl together.")
            return
        # - links VS renderer-only
        if len(parsed.links) > 0 and not run_engine:
            dtslogger.error("You cannot use --links without -S/--standalone.")
            return
        # make sure the map is given (in standalone mode)
        if run_engine and not parsed.map and not parsed.sandbox:
            dtslogger.error("You need to specify a map with -m/--map when running in "
                            "Standalone mode, or use a default map with -s/--sandbox.")
            return
        # make sure the time step is only given in gym mode
        if parsed.delta_t is not None and not parsed.simulation:
            dtslogger.error("You can specify a --delta-t only when running with "
                            "--gym/--simulation.")
            return
        # configure the engine if in standalone
        engine: Optional[MatrixEngine] = None
        if run_engine:
            engine = shell.include.matrix.engine.run.make_engine(shell, parsed, use_defaults=True)
            if engine is None:
                return
            # ENGINE is now configured
            # -------------------------------------------------------------------------------------

        # configure renderer
        app_bin: Optional[str] = None
        app_config: list = []
        terminate_renderer: Optional[Callable] = None
        if run_renderer:
            version = parsed.version if parsed.version else get_most_recent_version_installed()
            dtslogger.info(f"Configuring Renderer ({version})...")
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
                # by default, we use Vulkan
                app_config += ["-force-vulkan"]
            # custom engine
            if parsed.engine_hostname is not None:
                app_config += ["--engine-hostname", parsed.engine_hostname]
            # custom renderer ID
            if parsed.renderer_id is not None:
                app_config += ["--id", f"renderer_{parsed.renderer_id}"]
            # custom renderer key
            if parsed.renderer_key is not None:
                app_config += ["--key", parsed.renderer_key]
            # ---
            dtslogger.info("Renderer configured!")
            # RENDERER is now configured
            # -------------------------------------------------------------------------------------

        # run
        try:
            # - engine
            if run_engine:
                if not parsed.no_pull:
                    engine.pull()
                engine.start()

            # - renderer
            if run_renderer:
                # wait for the engine (if any) to become healthy
                if run_engine:
                    timeout = 20
                    dtslogger.info(f"Waiting up to {timeout} seconds for the Engine to start...")
                    try:
                        engine.wait_until_healthy(timeout)
                    except Exception as e:
                        dtslogger.error(f"The Engine failed to become healthy within {timeout} "
                                        f"seconds. Try running with the --verbose flag to gain "
                                        f"insights into the problem.\n"
                                        f"The error reads:\n{e}")
                        engine.stop()
                        return

                # on MacOS, we open the location of the app
                if IS_MACOS:
                    app_location: str = str(Path(app_bin).parent)
                    dtslogger.info(f"\n===================\n"
                                   f"  The Duckiematrix app is located at:\n\n\t{app_location}/\n\n"
                                   f"===================")
                    dtslogger.info(f"Finder should open this location automatically now.\n"
                                   f"         If it doesn't, use the command `open {app_location}` from your terminal "
                                   f"or, navigate to the path using Finder.")
                    subprocess.call(["open", app_location])
                    # wait for the engine to terminate
                    if run_engine:
                        engine.join()
                else:
                    # run the app
                    dtslogger.info("Launching Renderer...")
                    app_cmd = [app_bin] + app_config
                    dtslogger.debug(f"$ > {app_cmd}")
                    time.sleep(2)
                    renderer = subprocess.Popen(app_cmd, stdout=subprocess.PIPE)
                    # this is how we terminate the renderer

                    def terminate_renderer(*_):
                        # noinspection PyBroadException
                        try:
                            renderer.kill()
                        except Exception:
                            pass

                    # wait for the renderer to terminate
                    join_renderer(renderer, parsed.verbose)
            else:
                # wait for the engine to terminate
                engine.join()

        finally:
            if run_engine:
                engine.stop()
            if run_renderer and terminate_renderer:
                terminate_renderer()

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
