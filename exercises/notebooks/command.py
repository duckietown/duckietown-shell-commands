import os
import time
import webbrowser
from pathlib import Path
from threading import Thread

from dt_shell import DTCommandAbs, DTShell, UserError, dtslogger

usage = """

## Basic usage
    This is a helper for the exercises. 
    You must run this command inside an exercise folder. 

    To know more on the `exercise` commands, use `dts duckiebot exercise -h`.

        $ dts exercises notebooks 

"""

JUPYTER_WS = "/jupyter_ws"
JUPYTER_URL = "http://localhost:8888"


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
            msg = f"You must run this command inside an exercise directory " \
                  f"containing a `{cfile_name}` file."
            raise InvalidUserInput(msg)
        # make sure this exercise has a notebooks directory in it
        notesdir_name = "notebooks"
        notesdir = os.path.join(working_dir, notesdir_name)
        if not os.path.exists(notesdir) or not os.path.isdir(notesdir):
            msg = f"You must run this command inside an exercise directory " \
                  f"containing a `{notesdir_name}` directory."
            raise InvalidUserInput(msg)

        # create a function that opens up the browser to the right URL after 4 seconds
        def open_url():
            # wait 4 seconds, then open the browser
            time.sleep(4)
            dtslogger.info(f"Open your browser at the following address to use "
                           f"your notebooks: {JUPYTER_URL}\n\n\n")
            webbrowser.open(JUPYTER_URL)

        waiter = Thread(target=open_url)
        waiter.start()

        # run start-gui-tools
        shell.include.start_gui_tools.command(shell, [
            "--launcher", "jupyter",
            "--mount", f"{notesdir}:{JUPYTER_WS}",
            "--name", f"dts-exercises-notebooks-{exercise_name}",
            "--no-scream"
        ])

        waiter.join()
