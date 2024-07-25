import argparse
import os
import pathlib

import yaml

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.avahi_utils import wait_for_service
from utils.docker_utils import get_endpoint_architecture, get_registry_to_use, pull_image_OLD
from utils.multi_command_utils import MultiCommand
from utils.networking_utils import best_host_for_robot

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
            required=True,
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
        robot: str = parsed.machine.replace(".local", "")
        hostname: str = best_host_for_robot(parsed.machine)
        # special stack is `duckietown`
        if parsed.stack == DUCKIETOWN_STACK:
            # retrieve robot type from device
            dtslogger.info(f'Waiting for robot "{robot}"...')
            _, _, data = wait_for_service("DT::ROBOT_TYPE", hostname)
            rtype = data["type"]
            dtslogger.info(f'Detected device type is "{rtype}".')
            parsed.stack = f"{DUCKIETOWN_STACK}/{rtype}"
        # sanitize stack
        stack = parsed.stack if "/" in parsed.stack else f"{parsed.stack}/{DEFAULT_STACK}"
        # check stack
        stack_cmd_dir = pathlib.Path(__file__).parent.parent.absolute()
        stack_file = os.path.join(stack_cmd_dir, "stacks", stack) + ".yaml"
        if not os.path.isfile(stack_file):
            dtslogger.error(f"Stack `{stack}` not found.")
            return
        # info about registry
        registry_to_use = get_registry_to_use()

        # get info about docker endpoint
        dtslogger.info("Retrieving info about Docker endpoint...")
        endpoint_arch = get_endpoint_architecture(hostname)
        dtslogger.info(f'Detected device architecture is "{endpoint_arch}".')
        # print info
        dtslogger.info(f"Pulling stack [{stack}]...")
        print("------>")
        # pull images
        with open(stack_file, "r") as fin:
            stack_content = yaml.safe_load(fin)
        for service in stack_content["services"].values():
            image_name = service["image"].replace("${ARCH}", endpoint_arch)
            image_name = image_name.replace("${REGISTRY}", registry_to_use)
            dtslogger.info(f"Pulling image `{image_name}`...")
            pull_image_OLD(image_name, hostname)
        # ---
        print("<------")
