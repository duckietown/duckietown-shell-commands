import os
import pathlib
import argparse

import yaml

from utils.avahi_utils import wait_for_service

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.docker_utils import get_endpoint_architecture, pull_image
from utils.misc_utils import sanitize_hostname
from utils.docker_utils import DEFAULT_MACHINE
from utils.multi_command_utils import MultiCommand

DEFAULT_STACK = "default"
DUCKIETOWN_STACK = "duckietown"


class DTCommand(DTCommandAbs):

    help = "Easy way to pull code on Duckietown robots"

    @staticmethod
    def command(shell: DTShell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-H",
            "--machine",
            default=None,
            help="Docker socket or hostname where to run the image",
        )
        parser.add_argument("stack", nargs=1, default=None)
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        # try to interpret it as a multi-command
        multi = MultiCommand(DTCommand, shell, [("-H", "--machine")], args)
        if multi.is_multicommand:
            multi.execute()
            return
        # ---
        parsed.stack = parsed.stack[0]
        # special stack is `duckietown`
        if parsed.stack == DUCKIETOWN_STACK:
            # retrieve robot type from device
            dtslogger.info(f'Waiting for device "{parsed.machine}"...')
            hostname = parsed.machine.replace(".local", "")
            _, _, data = wait_for_service("DT::ROBOT_TYPE", hostname)
            rtype = data["type"]
            dtslogger.info(f'Detected device type is "{rtype}".')
            parsed.stack = f"{DUCKIETOWN_STACK}/{rtype}"
        # sanitize stack
        stack = parsed.stack if "/" in parsed.stack else f"{parsed.stack}/{DEFAULT_STACK}"
        # check stack
        stack_file = os.path.join(pathlib.Path(__file__).parent.parent.absolute(), "stacks", stack) + ".yaml"
        if not os.path.isfile(stack_file):
            dtslogger.error(f"Stack `{stack}` not found.")
            return
        # sanitize hostname
        if parsed.machine is not None:
            parsed.machine = sanitize_hostname(parsed.machine)
        else:
            parsed.machine = DEFAULT_MACHINE
        # get info about docker endpoint
        dtslogger.info("Retrieving info about Docker endpoint...")
        endpoint_arch = get_endpoint_architecture(parsed.machine)
        dtslogger.info(f'Detected device architecture is "{endpoint_arch}".')
        # print info
        dtslogger.info(f"Pulling stack [{stack}]...")
        print("------>")
        # pull images
        with open(stack_file, "r") as fin:
            stack_content = yaml.safe_load(fin)
        for service in stack_content["services"].values():
            image_name = service["image"].replace("${ARCH}", endpoint_arch)
            dtslogger.info(f"Pulling image `{image_name}`...")
            pull_image(image_name, parsed.machine)
        # ---
        print("<------")
