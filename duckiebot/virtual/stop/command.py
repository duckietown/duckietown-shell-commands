import argparse

import docker
from dt_shell import DTCommandAbs, DTShell, dtslogger


class DTCommand(DTCommandAbs):

    help = "Shuts down a Virtual Duckiebot"

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot virtual stop"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument("robot", nargs=1, help="Name of the Robot to stop")
        # parse arguments
        parsed = parser.parse_args(args)
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        # make sure the virtual robot is actually running
        local_docker = docker.from_env()
        try:
            vbot_container = local_docker.containers.get(f"dts-virtual-{parsed.robot}")
            dtslogger.info(f"Shutting down virtual robot '{parsed.robot}', "
                           f"this might take up to a minute...")
            vbot_container.exec_run(cmd="shutdown")
            vbot_container.wait()
            dtslogger.info("Done!")
            return True
        except docker.errors.NotFound:
            # warn and exit
            dtslogger.error(f"No running virtual robot found with name '{parsed.robot}'")
            return False
