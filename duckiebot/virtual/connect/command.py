import argparse
import subprocess

import docker
from dt_shell import DTCommandAbs, DTShell, dtslogger

from disk_image.create.utils import run_cmd


class DTCommand(DTCommandAbs):

    help = "Connects a terminal to a Virtual Duckiebot"

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot virtual connect"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument("robot", nargs=1, help="Name of the Robot to connect to")
        # parse arguments
        parsed = parser.parse_args(args)
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        # make sure the virtual robot exists
        local_docker = docker.from_env()
        try:
            local_docker.containers.get(f"dts-virtual-{parsed.robot}")
        except docker.errors.NotFound:
            dtslogger.error(f"No running virtual robot found with name '{parsed.robot}'")
            return
        # attach a terminal to the robot's container
        dtslogger.info(f"Opening terminal on virtual robot '{parsed.robot}':")
        try:
            run_cmd([
                "docker",
                "exec",
                "-it",
                f"dts-virtual-{parsed.robot}",
                "/bin/bash"
            ])
        except subprocess.CalledProcessError:
            dtslogger.warn("The connection to the virtual robot was interrupted abruptly. "
                           "Just a heads up.")
