import argparse
import getpass
import os
import signal
import sys
import time
import webbrowser

from docker.errors import APIError, ImageNotFound, NotFound

from dt_data_api import APIError
from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError
from duckietown_docker_utils import ENV_REGISTRY
from utils.docker_utils import get_client, get_registry_to_use
from utils.exceptions import InvalidUserInput
from utils.exercises_utils import get_exercise_config
from utils.pip_utils import get_pip_index_url, import_or_install

usage = """

## Basic usage
    This is a helper for the exercises. 
    You must run this command inside an exercise folder. 

    To know more on the `exercises` commands, use `dts exercises -h`.

        $ dts exercises lab 

"""
JUPYTER_WS = "/jupyter_ws"
JUPYTER_HOST = "localhost"
JUPYTER_PORT = "8888"
JUPYTER_URL = f"http://{JUPYTER_HOST}:{JUPYTER_PORT}"
IS_SHUTDOWN = False


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        # to clone the mooc repo
        import_or_install("gitpython", "git")

        # to convert the notebook into a python script
        import_or_install("nbformat", "nbformat")
        import_or_install("nbconvert", "nbconvert")

        prog = "dts exercise lab"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument(
            "--vnc",
            "-v",
            dest="vnc",
            action="store_true",
            default=False,
            help="Should we also start the no VNC browser?",
        )

        parsed = parser.parse_args(args)

        config = get_exercise_config()

        # make sure this exercise has a lab_dir key in its config file and that it points to
        # an existing directory
        labdir_name = config.lab_dir
        if labdir_name is None:
            raise ValueError(
                "The exercise configuration file 'config.yaml' does not have a "
                "'lab_dir' key to indicate where notebooks are stored"
            )
        labdir = os.path.join(config.root, labdir_name)
        if not os.path.exists(labdir) or not os.path.isdir(labdir):
            msg = (
                f"You must run this command inside an exercise directory "
                f"containing a `{labdir_name}` directory."
            )
            raise InvalidUserInput(msg)

        # make sure this exercise has a ws_dir key in its config file and that it points to
        # an existing directory
        wsdir_name = config.ws_dir
        if wsdir_name is None:
            raise ValueError(
                "The exercise configuration file 'config.yaml' does not have a "
                "'ws_dir' key to indicate where code is stored"
            )
        wsdir = os.path.join(config.root, wsdir_name)
        if not os.path.exists(wsdir) or not os.path.isdir(wsdir):
            msg = (
                f"You must run this command inside an exercise directory "
                f"containing a `{wsdir_name}` directory."
            )
            raise InvalidUserInput(msg)

        # make sure this exercise has a Dockerfile.lab file
        dockerfile_lab_name = "Dockerfile.lab"
        dockerfile_lab = os.path.join(config.root, dockerfile_lab_name)
        if not os.path.exists(dockerfile_lab) or not os.path.isfile(dockerfile_lab):
            msg = (
                f"You must run this command inside an exercise directory "
                f"containing a `{dockerfile_lab_name}` file."
            )
            raise InvalidUserInput(msg)

        # build notebook image
        username = getpass.getuser()
        lab_image_name = f"{username}/exercise-{config.exercise_name}-lab"

        # make sure the image exists
        client = get_client()
        try:
            client.images.get(lab_image_name)
        except ImageNotFound:
            dtslogger.error("You must run the command `dts exercises build` before using the lab.")
            exit(1)

        dockerfile = os.path.join(config.root, "Dockerfile.lab")
        if not os.path.exists(dockerfile):
            msg = f"There is no Dockerfile.lab present at {dockerfile}"
            raise UserError(msg)

        docker_build_args = {}

        docker_build_args["PIP_INDEX_URL"] = get_pip_index_url()
        docker_build_args[ENV_REGISTRY] = get_registry_to_use()

        buildargs = {
            "buildargs": docker_build_args,
            "path": labdir,
            "tag": lab_image_name,
            "dockerfile": "Dockerfile.lab",
        }

        logs = client.api.build(**buildargs, decode=True)
        dtslogger.info("Building environment...")
        try:
            for log in logs:
                if "stream" in log:
                    sys.stdout.write(log["stream"])
            sys.stdout.flush()
        except APIError as e:
            dtslogger.error(str(e))
            exit(1)
        dtslogger.info("...environment built.")

        jupyter_container_name = f"dts-exercises-lab-{config.exercise_name}"
        vnc_container_name = f"dts-exercises-lab-{config.exercise_name}-vnc"
        containers_to_monitor = []

        # create a function that opens up the browser to the right URL after 4 seconds
        def open_url():
            # wait 4 seconds, then open the browser
            time.sleep(4)
            dtslogger.info(
                f"Open your browser at the following address to use "
                f'your notebooks, password is "quackquack": {JUPYTER_URL}\n\n\n'
            )
            time.sleep(2)
            webbrowser.open(JUPYTER_URL)

        def run_vnc():
            # run start-gui-tools
            shell.include.start_gui_tools.command(
                shell,
                [
                    "--launcher",
                    "vnc",
                    "--mount",
                    f"{labdir}:{JUPYTER_WS}",
                    "--image",
                    lab_image_name,
                    "--name",
                    vnc_container_name,
                    "--no-scream",
                    "--detach",
                    "LOCAL",
                ],
            )

        def run_jupyter():
            # run start-gui-tools
            shell.include.start_gui_tools.command(
                shell,
                [
                    "--launcher",
                    "jupyter",
                    "--mount",
                    f"{labdir}:{JUPYTER_WS}",
                    "--image",
                    lab_image_name,
                    "--name",
                    jupyter_container_name,
                    "--uid",
                    str(os.getuid()),
                    "--network",
                    "bridge",
                    "--port",
                    f"{JUPYTER_PORT}:8888/tcp",
                    "--no-scream",
                    "--detach",
                    "LOCAL",
                    f"NotebookApp.notebook_dir={os.path.join(JUPYTER_WS, wsdir_name)}",
                    f"NotebookApp.ip=0.0.0.0",
                ],
            )

        def shutdown(*_):
            global IS_SHUTDOWN
            IS_SHUTDOWN = True
            for container_name in containers_to_monitor:
                try:
                    dtslogger.info(f"Stopping container '{container_name}'")
                    container = client.containers.get(container_id=container_name)
                    container.stop()
                except NotFound:
                    # all is good
                    dtslogger.warning(f"Container {container_name} not found.")
                except APIError as _e:
                    print(_e)

        try:
            if parsed.vnc:
                run_vnc()
                containers_to_monitor.append(vnc_container_name)
            run_jupyter()
            containers_to_monitor.append(jupyter_container_name)
            open_url()
            # capture SIGINT and abort
            signal.signal(signal.SIGINT, shutdown)
        except Exception as e:
            print(e)
            return
        global IS_SHUTDOWN
        while not IS_SHUTDOWN:
            time.sleep(1)
