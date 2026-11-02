import argparse

import docker
from dt_shell import DTCommandAbs, DTShell, dtslogger

from ..gateway import (
    gateway_leader_election,
    has_other_virtual_robots,
    is_gateway_leader,
    refresh_gateway_backends,
)


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
            containers = local_docker.containers
            container_name = f"dts-virtual-{parsed.robot}"
            vbot_container = containers.get(container_name)
            with gateway_leader_election():
                is_leader = is_gateway_leader(vbot_container)
                has_followers = has_other_virtual_robots(local_docker, parsed.robot)
                if is_leader and has_followers:
                    dtslogger.error(
                        f"Virtual robot '{parsed.robot}' is routing fleet browser traffic. "
                        "Stop the other virtual robots first."
                    )
                    return False
                dtslogger.info(f"Shutting down virtual robot '{parsed.robot}', "
                               f"this might take up to a minute...")
                vbot_container.exec_run(cmd="shutdown")
                vbot_container.wait()
                refresh_gateway_backends(local_docker)
            dtslogger.info("Done!")
            return True
        except docker.errors.NotFound:
            # warn and exit
            dtslogger.error(f"No running virtual robot found with name '{parsed.robot}'")
            return False
