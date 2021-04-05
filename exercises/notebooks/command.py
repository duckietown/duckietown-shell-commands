import os

from dt_shell import DTCommandAbs, DTShell, UserError

from utils.cli_utils import start_command_in_subprocess

usage = """

## Basic usage
    This is a helper for the exercises. 
    You must run this command inside an exercise folder. 

    To know more on the `exercise` commands, use `dts duckiebot exercise -h`.

        $ dts exercise notebooks 

"""

BRANCH = "daffy"
ARCH = "amd64"
# AIDO_REGISTRY = "registry-stage.duckietown.org"
ROS_TEMPLATE_IMAGE = "duckietown/challenge-aido_lf-template-ros:" + BRANCH + "-" + ARCH


class InvalidUserInput(UserError):
    pass


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts exercise notebooks"
        working_dir = os.getcwd()
        CF = "config.yaml"
        fn = os.path.join(working_dir, CF)
        if not os.path.exists(fn):
            msg = f"You must run this command inside an exercise directory containing a `{CF}` file."
            raise InvalidUserInput(msg)
        start_command_in_subprocess("cd notebooks && jupyter notebook")
