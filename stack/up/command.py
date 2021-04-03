import os
import pathlib
import argparse
from shutil import which

import yaml

from utils.avahi_utils import wait_for_service
from utils.cli_utils import start_command_in_subprocess

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.docker_utils import get_endpoint_architecture, pull_image
from utils.misc_utils import sanitize_hostname
from utils.docker_utils import DEFAULT_MACHINE, DEFAULT_DOCKER_TCP_PORT
from utils.multi_command_utils import MultiCommand

DEFAULT_STACK = "default"
DUCKIETOWN_STACK = "duckietown"


class DTCommand(DTCommandAbs):

    help = "Easy way to run code on Duckietown robots"

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
        parser.add_argument(
            "-d",
            "--detach",
            action="store_true",
            default=False,
            help="Detach from running containers",
        )
        parser.add_argument(
            "--pull",
            action="store_true",
            default=False,
            help="Pull images before running",
        )
        parser.add_argument("stack", nargs=1, default=None)
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        # verify dependencies
        if which("docker-compose") is None:
            dtslogger.error(
                "\nThis command requires the library `docker-compose`.\n"
                "Please, install it using the command:\n\n"
                "\tpip3 install docker-compose\n\n"
            )
            return
        # ---
        # try to interpret it as a multi-command
        multi = MultiCommand(DTCommand, shell, [("-H", "--machine")], args)
        if multi.is_multicommand:
            multi.execute()
            return
        # ---
        parsed.stack = parsed.stack[0]
        project_name = parsed.stack.replace("/", "_")
        # special stack is `duckietown`
        if parsed.stack == DUCKIETOWN_STACK:
            # retrieve robot type from device
            dtslogger.info(f'Waiting for device "{parsed.machine}"...')
            hostname = parsed.machine.replace(".local", "")
            _, _, data = wait_for_service("DT::ROBOT_TYPE", hostname)
            rtype = data["type"]
            dtslogger.info(f'Detected device type is "{rtype}".')
            parsed.stack = f"{DUCKIETOWN_STACK}/{rtype}"
            project_name = DUCKIETOWN_STACK
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
        # pull images
        if parsed.pull:
            with open(stack_file, "r") as fin:
                stack_content = yaml.safe_load(fin)
            for service in stack_content["services"].values():
                image_name = service["image"].replace("${ARCH}", endpoint_arch)
                dtslogger.info(f"Pulling image `{image_name}`...")
                pull_image(image_name, parsed.machine)
        # print info
        dtslogger.info(f"Running stack [{stack}]...")
        print("------>")
        # collect arguments
        docker_arguments = []
        # get copy of environment
        env = {}
        env.update(os.environ)
        # add ARCH
        env["ARCH"] = endpoint_arch
        # -d/--detach
        if parsed.detach:
            docker_arguments.append("--detach")
        # run docker compose stack
        H = f"{parsed.machine}:{DEFAULT_DOCKER_TCP_PORT}"
        start_command_in_subprocess(
            ["docker-compose", f"-H={H}", "--project-name", project_name, "--file", stack_file, "up"]
            + docker_arguments,
            env=env,
        )
        # ---
        print("<------")
