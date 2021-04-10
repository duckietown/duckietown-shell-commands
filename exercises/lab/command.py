import getpass
import os
import sys
import time
import webbrowser
from threading import Thread

from dt_data_api import APIError
from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError

from utils.docker_utils import get_client
from utils.exceptions import InvalidUserInput
from utils.exercises_utils import get_exercise_config

usage = """

## Basic usage
    This is a helper for the exercises. 
    You must run this command inside an exercise folder. 

    To know more on the `exercises` commands, use `dts exercises -h`.

        $ dts exercises lab 

"""
JUPYTER_WS = "/jupyter_ws"
JUPYTER_URL = "http://localhost:8888"


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args):

        config = get_exercise_config()

        # make sure this exercise has a lab_dir key in its config file and that it points to
        # an existing directory
        labdir_name = config.lab_dir
        if labdir_name is None:
            raise ValueError("The exercise configuration file 'config.yaml' does not have a "
                             "'lab_dir' key to indicate where notebooks are stored")
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
            raise ValueError("The exercise configuration file 'config.yaml' does not have a "
                             "'ws_dir' key to indicate where code is stored")
        wsdir = os.path.join(config.root, wsdir_name)
        if not os.path.exists(wsdir) or not os.path.isdir(wsdir):
            msg = (
                f"You must run this command inside an exercise directory "
                f"containing a `{wsdir_name}` directory."
            )
            raise InvalidUserInput(msg)

        # build notebook image
        username = getpass.getuser()
        lab_image_name = f"{username}/exercise-{config.exercise_name}-lab"
        client = get_client()

        dockerfile = os.path.join(config.root, "Dockerfile.lab")
        if not os.path.exists(dockerfile):
            msg = f'There is no Dockerfile.lab present at {dockerfile}'
            raise UserError(msg)

        logs = client.api.build(
            path=labdir,
            tag=lab_image_name,
            dockerfile="Dockerfile.lab",
            decode=True
        )
        dtslogger.info("Building environment...")
        try:
            for log in logs:
                if 'stream' in log:
                    sys.stdout.write(log['stream'])
            sys.stdout.flush()
        except APIError as e:
            dtslogger.error(str(e))
            exit(1)
        dtslogger.info("Environment built!")

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
                f"dts-exercises-lab-{config.exercise_name}",
                "--no-scream",
                "LOCAL",
                f"NotebookApp.notebook_dir={os.path.join(JUPYTER_WS, wsdir_name)}"
            ],
        )

        waiter.join()
