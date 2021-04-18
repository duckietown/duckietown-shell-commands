import argparse

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.docker_utils import get_endpoint_architecture, get_client, pull_image
from utils.duckietown_utils import get_distro_version
from utils.misc_utils import sanitize_hostname
from utils.robot_utils import log_event_on_robot

DEFAULT_STACK = "duckietown"
OTHER_IMAGES_TO_UPDATE = [
    # TODO: this is disabled for now, too big for the SD card
    # "duckietown/dt-gui-tools:{distro}-{arch}",
    "duckietown/dt-core:{distro}-{arch}",
    "duckietown/dt-duckiebot-fifos-bridge:{distro}-{arch}",
    "duckietown/challenge-aido_lf-baseline-duckietown:{distro}-{arch}",
    "duckietown/challenge-aido_lf-template-ros:{distro}-{arch}",
]


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot update"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument(
            "-s", "--stack", type=str, default=DEFAULT_STACK, help="Name of the Stack to update"
        )
        parser.add_argument("robot", nargs=1, help="Name of the Robot to update")
        # parse arguments
        parsed = parser.parse_args(args)
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        hostname = sanitize_hostname(parsed.robot)
        # clean duckiebot
        shell.include.duckiebot.clean.command(shell, [parsed.robot, "--all"])
        # compile image names
        arch = get_endpoint_architecture(hostname)
        distro = get_distro_version(shell)
        images = [img.format(distro=distro, arch=arch) for img in OTHER_IMAGES_TO_UPDATE]
        client = get_client(hostname)
        # it looks like the update is going to happen, mark the event
        log_event_on_robot(parsed.robot, "duckiebot/update")
        # do update
        # call `stack up` command
        shell.include.stack.up.command(shell, ["--machine", parsed.robot, "--detach", "--pull", parsed.stack])
        # update non-active images
        for image in images:
            dtslogger.info(f"Pulling image `{image}`...")
            pull_image(image, client)
        # clean duckiebot (again)
        shell.include.duckiebot.clean.command(shell, [parsed.robot, "--all", "--yes", "--untagged"])
