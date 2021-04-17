import os
import time
import getpass
import webbrowser
from pathlib import Path
from threading import Thread

import docker

from utils.docker_utils import get_client
from utils.yaml_utils import load_yaml
from dt_shell import DTCommandAbs, DTShell, UserError, dtslogger

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


class InvalidUserInput(UserError):
    pass


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args):
        working_dir = os.getcwd()
        exercise_name = Path(working_dir).stem
        dtslogger.info(f"Exercise name: {exercise_name}")
        # make sure we are in an exercise directory
        cfile_name = "config.yaml"
        cfile = os.path.join(working_dir, cfile_name)
        if not os.path.exists(cfile):
            msg = (
                f"You must run this command inside an exercise directory "
                f"containing a `{cfile_name}` file."
            )
            raise InvalidUserInput(msg)
        config = load_yaml(cfile)

        # make sure this exercise has a lab_dir key in its config file and that it points to
        # an existing directory
        labdir_name = config.get("lab_dir", None)
        if labdir_name is None:
            raise ValueError("The exercise configuration file 'config.yaml' does not have a "
                             "'lab_dir' key to indicate where notebooks are stored")
        labdir = os.path.join(working_dir, labdir_name)
        if not os.path.exists(labdir) or not os.path.isdir(labdir):
            msg = (
                f"You must run this command inside an exercise directory "
                f"containing a `{labdir_name}` directory."
            )
            raise InvalidUserInput(msg)

        # make sure this exercise has a ws_dir key in its config file and that it points to
        # an existing directory
        wsdir_name = config.get("ws_dir", None)
        if wsdir_name is None:
            raise ValueError("The exercise configuration file 'config.yaml' does not have a "
                             "'ws_dir' key to indicate where code is stored")

        # compile image name
        lab_image_name = f"{getpass.getuser()}/exercise-{exercise_name}-lab"

        # make sure the image exists
        client = get_client()
        try:
            client.images.get(lab_image_name)
        except docker.errors.ImageNotFound:
            dtslogger.error("You must run the command `dts exercises build` before using the lab.")
            exit(1)

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

        waiter = Thread(target=open_url)
        waiter.start()

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
                f"dts-exercises-lab-{exercise_name}",
                "--uid",
                str(os.getuid()),
                "--network",
                "bridge",
                "--port",
                f"{JUPYTER_PORT}:8888/tcp",
                "--no-scream",
                "LOCAL",
                f"NotebookApp.notebook_dir={os.path.join(JUPYTER_WS, wsdir_name)}",
                f"NotebookApp.ip=0.0.0.0"
            ],
        )

        waiter.join()
