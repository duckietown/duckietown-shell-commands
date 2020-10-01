
from dt_shell import DTCommandAbs, dtslogger
from utils.cli_utils import start_command_in_subprocess
import os
usage = """

## Basic usage
    This is a helper for the exercises. 
    You must run this command inside an exercise folder. 

    To know more on the `exercise` commands, use `dts duckiebot exercise -h`.

        $ dts exercise notebooks 

"""



BRANCH="daffy"
ARCH="amd64"
AIDO_REGISTRY="registry-stage.duckietown.org"
ROS_TEMPLATE_IMAGE="duckietown/challenge-aido_lf-template-ros:" + BRANCH + "-" + ARCH



class InvalidUserInput(Exception):
    pass


from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts exercise notebooks"
        working_dir = os.getcwd()
        if not os.path.exists(working_dir + "/config.yaml"):
            msg = "You must run this command inside the exercise directory"
            raise InvalidUserInput(msg)
        start_command_in_subprocess("cd notebooks && jupyter notebook")
