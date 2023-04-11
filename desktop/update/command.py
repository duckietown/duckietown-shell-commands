import argparse

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.docker_utils import (
    DEFAULT_MACHINE,
    get_client,
    get_endpoint_architecture,
    get_registry_to_use,
    login_client_OLD,
    pull_image,
)
from utils.duckietown_utils import get_distro_version
from utils.disk_space_utils import (
    check_enough_disk,
    num_bytes_to_simple_friendly_str,
)
from utils.cli_utils import ask_confirmation

OTHER_IMAGES_TO_UPDATE = [
    "{registry}/duckietown/dt-gui-tools:{distro}-{arch}",
    "{registry}/duckietown/dt-core:{distro}-{arch}",
    # "{registry}/duckietown/dt-duckiebot-fifos-bridge:{distro}-{arch}",
    # "{registry}/duckietown/challenge-aido_lf-baseline-duckietown:{distro}-{arch}",
    # "{registry}/duckietown/challenge-aido_lf-baseline-duckietown-ml:{distro}-{arch}",
    # "{registry}/duckietown/challenge-aido_lf-template-ros:{distro}-{arch}",
    # "{registry}/duckietown/challenge-aido_lf-simulator-gym:{distro}-{arch}",
    # "{registry}/duckietown/aido-base-python3:{distro}-{arch}",
]

DISK_SPACE_REQUIRED_SOFT = 10 * ((2 ** 10) ** 3)  # prompt
DISK_SPACE_REQUIRED_HARD = 3 * ((2 ** 10) ** 3)  # abort

class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts desktop update"
        parser = argparse.ArgumentParser(prog=prog)

        # parse arguments
        parsed = parser.parse_args(args)

        # check curr disk space. If not enough, abort
        dtslogger.info("Checking disk space now...")
        res = check_enough_disk(DISK_SPACE_REQUIRED_SOFT)

        if res is None:  # could not check disk space
            msg = (
                "Unable to determine whether disk space is sufficient. "
                "Please open an issue on Github.\n"
                "Please make sure you have enough disk space before continue."
            )
            # prompt whether to proceed
            res = ask_confirmation(
                message=msg,
                question="Would you like to continue?",
            )
            if not res:
                return
        elif res is False: # below soft limit
            res = check_enough_disk(DISK_SPACE_REQUIRED_HARD)
            if not res:  # below hard limit, abort
                tmp = num_bytes_to_simple_friendly_str(DISK_SPACE_REQUIRED_HARD)
                dtslogger.error(f"Not enough disk space! Minimum {tmp} needed.")
                return

            # between soft and hard limit. prompt whether to proceed
            tmp = num_bytes_to_simple_friendly_str(DISK_SPACE_REQUIRED_SOFT)
            res = ask_confirmation(
                message=f"Your free disk space is below the recommended {tmp}.",
                question="Would you like to continue anyways?",
            )
            if not res:
                return

        registry_to_use = get_registry_to_use()

        # compile image names
        arch = get_endpoint_architecture(DEFAULT_MACHINE)
        distro = get_distro_version(shell)
        images = [
            img.format(registry=registry_to_use, distro=distro, arch=arch) for img in OTHER_IMAGES_TO_UPDATE
        ]
        client = get_client()
        login_client_OLD(client, shell.shell_config, registry_to_use, raise_on_error=False)
        # do update
        for image in images:
            dtslogger.info(f"Pulling image `{image}`...")
            pull_image(image, client)
