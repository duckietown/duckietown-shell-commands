import argparse

from dt_shell import DTCommandAbs, dtslogger
from dt_shell import DTShell

from utils.docker_utils import get_endpoint_architecture, get_client
from utils.duckietown_utils import get_distro_version
from utils.misc_utils import sanitize_hostname

IMAGE_FMT = "duckietown/dt-commons:{DISTRO}-{ARCH}"


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot reboot"
        parser = argparse.ArgumentParser(prog=prog)
        parser.add_argument(
            "robot",
            nargs=1,
            type=str,
            help="Duckiebot to reboot",
        )
        parsed = parser.parse_args(args)
        # ---
        robot = parsed.robot[0]
        hostname = sanitize_hostname(robot)
        distro = get_distro_version(shell)
        arch = get_endpoint_architecture(hostname)
        image = IMAGE_FMT.format(DISTRO=distro, ARCH=arch)
        container = f"dts-reboot-trigger-{robot}"
        command = ['dt-set-trigger', 'reboot', 'dts']
        # get docker client
        client = get_client(hostname)
        # ---
        dtslogger.info(f"Shutting down {robot}...")
        dtslogger.debug("Running command %s" % command)
        try:
            client.containers.run(
                image=image,
                command=command,
                volumes={
                    "/triggers": {"bind": "/triggers"}
                },
                name=container,
                remove=True
            )
        except BaseException as e:
            dtslogger.error(str(e))
            return
        # ---
        dtslogger.info("Signal sent, the robot should reboot soon.")
