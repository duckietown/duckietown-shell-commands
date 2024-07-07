import argparse
from typing import Optional, List

from docker.errors import NotFound

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.profile import DockerCredentials
from utils.docker_utils import (
    get_client_OLD,
    get_endpoint_architecture,
    get_registry_to_use,
    login_client_OLD,
    pull_image_OLD,
)
from utils.exceptions import UserAborted
from utils.kvstore_utils import KVStore
from utils.misc_utils import sanitize_hostname
from utils.robot_utils import log_event_on_robot

WHEN_NO_DISTRO = "daffy"
DEFAULT_STACKS = "robot/basics,duckietown"
OTHER_IMAGES_TO_UPDATE = [
    # TODO: this is disabled for now, too big for the SD card
    # "{registry}/duckietown/dt-gui-tools:{distro}-{arch}",
    # "{registry}/duckietown/dt-core:{distro}-{arch}",
    # "{registry}/duckietown/dt-duckiebot-fifos-bridge:{distro}-{arch}",
    # "{registry}/duckietown/challenge-aido_lf-baseline-duckietown:{distro}-{arch}",
    # "{registry}/duckietown/challenge-aido_lf-template-ros:{distro}-{arch}",
]


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot update"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument(
            "-s", "--stacks", type=str, default=DEFAULT_STACKS, help="Name of the stacks to update (comma-separated)"
        )
        parser.add_argument(
            "-k", "--no-clean", action="store_true", default=False, help="Do NOT perform a clean step"
        )
        parser.add_argument(
            "-d", "--deep-clean", action="store_true", default=False, help="Deep cleans the SD card before updating"
        )
        parser.add_argument(
            "-f", "--force", action="store_true", default=False, help="Force the operation when not recommended"
        )

        parser.add_argument("robot", nargs=1, help="Name of the Robot to update")
        # parse arguments
        parsed = parser.parse_args(args)
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        hostname = sanitize_hostname(parsed.robot)
        registry_to_use = get_registry_to_use()
        distro: str = shell.profile.distro.name
        stacks: List[str] = parsed.stacks.split(",")

        # check whether the robot is using a different distro
        rdistro: Optional[str]
        kv: KVStore = KVStore(parsed.robot)
        if kv.is_available():
            rdistro = kv.get(str, "robot/distro", WHEN_NO_DISTRO)
        else:
            dtslogger.warning(f"Could not get the distro from robot '{parsed.robot}'. Assuming '{WHEN_NO_DISTRO}'")
            rdistro = WHEN_NO_DISTRO

        if rdistro is not None:
            dtslogger.info(f"Detected distro '{rdistro}' on robot '{parsed.robot}'")
            if rdistro != distro:
                dtslogger.warning(
                    f"The robot '{parsed.robot}' is using the distro '{rdistro}' while your shell is set on '{distro}'. "
                    f"We do not recommend updating the robot with a different distro."
                )
                if parsed.force:
                    dtslogger.warning("Forced!")
                    # take stack down
                    for stack in stacks:
                        success = shell.include.stack.down.command(
                            shell,
                            ["--machine", parsed.robot, stack],
                        )
                        if not success:
                            return
                else:
                    dtslogger.warning("You can use the -f/--force flag to force the operation "
                                      "(if you know what you are doing).")
                    dtslogger.warning("Aborting.")
                    return

        # clean duckiebot and offer user abort option
        if parsed.deep_clean:
            try:
                shell.include.duckiebot.clean.command(shell, [parsed.robot, "--all"])
            except UserAborted as e:
                dtslogger.info(e)
                return

        # compile image names
        arch = get_endpoint_architecture(hostname)
        images = [
            img.format(registry=registry_to_use, distro=distro, arch=arch) for img in OTHER_IMAGES_TO_UPDATE
        ]
        client = get_client_OLD(hostname)
        credentials: DockerCredentials = shell.profile.secrets.docker_credentials
        login_client_OLD(client, credentials, registry_to_use, raise_on_error=False)
        # it looks like the update is going to happen, mark the event
        log_event_on_robot(parsed.robot, "duckiebot/update")

        # call `stack up` command for all stacks to update
        for stack in stacks:
            dtslogger.info(f"Updating stack `{stack}`...")
            success = shell.include.stack.up.command(
                shell,
                ["--machine", parsed.robot, "--detach", "--pull", stack],
            )
            if not success:
                return

        # update non-active images
        for image in images:
            dtslogger.info(f"Pulling image `{image}`...")
            try:
                pull_image_OLD(image, client)
            except NotFound:
                dtslogger.error(f"Image '{image}' not found on registry '{registry_to_use}'. Aborting.")
                return

        # set the distro on the robot
        if kv.is_available():
            kv.set("robot/distro", distro, persist=True, fail_quietly=True)
        else:
            dtslogger.warning(f"Could not set the distro '{distro}' on robot '{parsed.robot}'")

        # clean duckiebot (again)
        if not parsed.no_clean:
            shell.include.duckiebot.clean.command(shell, [parsed.robot, "--all", "--yes", "--untagged"])
