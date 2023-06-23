import argparse

from docker.errors import NotFound

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.docker_utils import (
    get_client,
    get_endpoint_architecture,
    get_registry_to_use,
    login_client_OLD,
    pull_image,
)
from utils.duckietown_utils import get_distro_version
from utils.exceptions import UserAborted
from utils.misc_utils import sanitize_hostname
from utils.robot_utils import log_event_on_robot

DEFAULT_STACK = "duckietown"
OTHER_IMAGES_TO_UPDATE = [
    # TODO: this is disabled for now, too big for the SD card
    # "{registry}/duckietown/dt-gui-tools:{distro}-{arch}",
    "{registry}/duckietown/dt-core:{distro}-{arch}",
    "{registry}/duckietown/dt-duckiebot-fifos-bridge:{distro}-{arch}",
    "{registry}/duckietown/challenge-aido_lf-baseline-duckietown:{distro}-{arch}",
    "{registry}/duckietown/challenge-aido_lf-template-ros:{distro}-{arch}",
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
        parser.add_argument(
            "--no-clean", action="store_true", default=False, help="Do NOT perform a clean step"
        )

        parser.add_argument("robot", nargs=1, help="Name of the Robot to update")
        # parse arguments
        parsed = parser.parse_args(args)
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        hostname = sanitize_hostname(parsed.robot)
        registry_to_use = get_registry_to_use()
        # clean duckiebot and offer user abort option
        if not parsed.no_clean:
            try:
                shell.include.duckiebot.clean.command(shell, [parsed.robot, "--all"])
            except UserAborted as e:
                dtslogger.info(e)
                return

        # compile image names
        arch = get_endpoint_architecture(hostname)
        distro = get_distro_version(shell)
        images = [
            img.format(registry=registry_to_use, distro=distro, arch=arch) for img in OTHER_IMAGES_TO_UPDATE
        ]
        client = get_client(hostname)
        login_client_OLD(client, shell.shell_config, registry_to_use, raise_on_error=False)
        # it looks like the update is going to happen, mark the event
        log_event_on_robot(parsed.robot, "duckiebot/update")
        # do update
        # call `stack up` command
        success = shell.include.stack.up.command(
            shell,
            ["--machine", parsed.robot, "--detach", "--pull", parsed.stack],
        )
        if not success:
            return
        # update non-active images
        for image in images:
            dtslogger.info(f"Pulling image `{image}`...")
            try:
                pull_image(image, client)
            except NotFound:
                dtslogger.error(f"Image '{image}' not found on registry '{registry_to_use}'. " f"Aborting.")
                return
        # clean duckiebot (again)
        if not parsed.no_clean:
            shell.include.duckiebot.clean.command(shell, [parsed.robot, "--all", "--yes", "--untagged"])
