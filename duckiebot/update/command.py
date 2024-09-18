import argparse
import copy
from typing import Optional, List, Dict

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
from utils.networking_utils import best_host_for_robot
from utils.robot_utils import log_event_on_robot

WHEN_NO_DISTRO = "daffy"
OTHER_IMAGES_TO_UPDATE = [
    # TODO: this is disabled for now, too big for the SD card
    # "{registry}/duckietown/dt-gui-tools:{distro}-{arch}",
    # "{registry}/duckietown/dt-core:{distro}-{arch}",
    # "{registry}/duckietown/dt-duckiebot-fifos-bridge:{distro}-{arch}",
    # "{registry}/duckietown/challenge-aido_lf-baseline-duckietown:{distro}-{arch}",
    # "{registry}/duckietown/challenge-aido_lf-template-ros:{distro}-{arch}",
]

STACKS_TO_LOAD = {
    "basics": "robot/basics",
    "duckietown": "duckietown/{robot_type}",
    "ros1": "ros1/{robot_type}",
}


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot update"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument(
            "-k", "--no-clean", action="store_true", default=False, help="Do NOT perform a clean step"
        )
        parser.add_argument(
            "-n", "--no-pull", action="store_true", default=False, help="Do NOT pull new images, just heal the stacks"
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
        registry_to_use = get_registry_to_use()
        distro: str = shell.profile.distro.name
        stacks: Dict[str, str] = copy.deepcopy(STACKS_TO_LOAD)

        # resolve robot hostname
        robot: str = parsed.robot
        hostname: str = best_host_for_robot(robot)

        # open KVStore
        kv: KVStore = KVStore(robot)

        # get the robot type
        rtype: Optional[str]
        if kv.is_available():
            rtype = kv.get(str, "robot/type", None)
        else:
            dtslogger.warning(f"Could not get the robot type from robot '{robot}'")
            rtype = None
        if rtype is None:
            dtslogger.warning(f"Could not get the robot type from robot '{robot}'")
        else:
            dtslogger.info(f"Detected robot type: {rtype}")

        # replace the placeholder in the stacks
        resolved_stacks: Dict[str, str] = {}
        for project, stack_fmt in stacks.items():
            if "{robot_type}" in stack_fmt and rtype is None:
                dtslogger.warning(f"Robot type not available for robot '{robot}', ignoring stack '{project}'")
                continue
            resolved_stacks[project] = stack_fmt.format(robot_type=rtype)
        stacks = resolved_stacks

        # check whether the robot is using a different distro
        rdistro: Optional[str]
        if kv.is_available():
            rdistro = kv.get(str, "robot/distro", WHEN_NO_DISTRO)
        else:
            dtslogger.warning(f"Could not get the distro from robot '{robot}'. Assuming '{WHEN_NO_DISTRO}'")
            rdistro = WHEN_NO_DISTRO

        if rdistro is not None:
            dtslogger.info(f"Detected distro '{rdistro}' on robot '{robot}'")
            if rdistro != distro:
                dtslogger.warning(
                    f"The robot '{robot}' is using the distro '{rdistro}' while your shell is set on '{distro}'. "
                    f"We do not recommend updating the robot with a different distro."
                )
                if parsed.force:
                    dtslogger.warning("Forced!")
                    # take stack down
                    for project, stack in stacks.items():
                        success = shell.include.stack.down.command(
                            shell,
                            ["--machine", robot, "--project", project, stack],
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
                shell.include.duckiebot.clean.command(shell, [robot, "--all"])
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
        log_event_on_robot(robot, "duckiebot/update")

        # stack/up options
        stack_up_options = ["--machine", robot, "--detach"]
        if not parsed.no_pull:
            stack_up_options.append("--pull")

        # call `stack up` command for all stacks to update
        for project, stack in stacks.items():
            dtslogger.info(f"Updating stack `{stack}`...")
            success = shell.include.stack.up.command(shell, stack_up_options + ["--project", project, stack])
            if not success:
                return

        # update non-active images
        if not parsed.no_pull:
            for image in images:
                dtslogger.info(f"Pulling image `{image}`...")
                try:
                    pull_image_OLD(image, client)
                except NotFound:
                    dtslogger.error(f"Image '{image}' not found on registry '{registry_to_use}'. Aborting.")
                    return

        # set the distro on the robot
        if kv.is_available():
            if distro != rdistro:
                dtslogger.info(f"Setting the distro '{distro}' on robot '{robot}'")
            kv.set("robot/distro", distro, persist=True, fail_quietly=True)
        else:
            dtslogger.warning(f"Could not set the distro '{distro}' on robot '{robot}'")

        # clean duckiebot (again)
        if not parsed.no_clean:
            shell.include.duckiebot.clean.command(shell, [robot, "--all", "--yes", "--untagged"])

        dtslogger.info("Update completed!")
