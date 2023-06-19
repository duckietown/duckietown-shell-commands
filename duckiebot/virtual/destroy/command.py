import argparse
import os
import re
import shutil

import docker
from dt_shell import DTCommandAbs, DTShell, dtslogger

from utils.cli_utils import \
    ask_confirmation
from utils.duckietown_utils import USER_DATA_DIR

DISK_NAME = "root"
VIRTUAL_FLEET_DIR = os.path.join(USER_DATA_DIR, "virtual_robots")


class DTCommand(DTCommandAbs):

    help = "Destroy an existing Virtual Duckiebot"

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot virtual destroy"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument("robot", nargs=1, help="Name of the Robot to destroy")
        parser.add_argument(
            "-y",
            "--yes",
            action="store_true",
            default=False,
            help="Do not ask for confirmation"
        )
        # parse arguments
        parsed = parser.parse_args(args)

        # sanitize arguments
        parsed.robot = parsed.robot[0]
        if not re.match("[a-z][a-z0-9]", parsed.robot):
            dtslogger.error(
                "Robot name can only contain letters and numbers and cannot start with a number.")
            return
        dtslogger.info(f"Robot to destroy: {parsed.robot}")

        # find dirs
        vbot_dir = os.path.join(VIRTUAL_FLEET_DIR, parsed.robot)
        # make sure the virtual duckiebot exists
        if not os.path.exists(vbot_dir):
            dtslogger.error(f"No virtual robot was found with the name '{parsed.robot}'.")
            return

        # make sure the virtual robot is not running
        local_docker = docker.from_env()
        try:
            local_docker.containers.get(f"dts-virtual-{parsed.robot}")
            dtslogger.error(f"The virtual robot '{parsed.robot}' is running, stop it first.")
            return
        except docker.errors.NotFound:
            # good
            pass

        # ask for confirmation (unless skipped)
        confirmed = ask_confirmation(
            f"The virtual robot '{parsed.robot}' will be destroyed together will all its data. "
            f"This cannot be undone.",
            default="n"
        ) if not parsed.yes else True
        if not confirmed:
            dtslogger.info("Sounds good! I won't touch anything then.")
            return

        # remove virtual robot
        dtslogger.info(f"Destroying virtual robot '{parsed.robot}'...")

        local_docker.containers.run(
            image="alpine",
            remove=True,
            detach=False,
            volumes={
                vbot_dir: {
                    "bind": "/destroy",
                    "mode": "rw"
                }
            },
            command=["rm", "-rf", f"/destroy/{DISK_NAME}"]
        )

        shutil.rmtree(vbot_dir)
        dtslogger.info("Your virtual robot was successfully destroyed.")
