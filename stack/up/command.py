import argparse
import os
import pathlib
from typing import Set

import yaml
from docker.errors import NotFound

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.avahi_utils import wait_for_service
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import (
    DEFAULT_DOCKER_TCP_PORT,
    get_client_OLD,
    get_endpoint_architecture,
    get_registry_to_use,
    pull_image_OLD,
)
from utils.multi_command_utils import MultiCommand
from utils.networking_utils import best_host_for_robot

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
            required=True,
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
        parser.add_argument(
            "-p",
            "--project",
            required=False,
            default=None,
            help="Name of the project to use for the stack",
        )

        parser.add_argument("stack", nargs="+", default=None)
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        # try to interpret it as a multi-command
        multi = MultiCommand(DTCommand, shell, [("-H", "--machine")], args)
        if multi.is_multicommand:
            multi.execute()
            return True
        # ---
        stacks = parsed.stack
        robot: str = parsed.machine.replace(".local", "")
        hostname: str = best_host_for_robot(parsed.machine)
        # info about registry
        registry_to_use = get_registry_to_use()
        # get info about docker endpoint
        dtslogger.info("Retrieving info about Docker endpoint...")
        endpoint_arch = get_endpoint_architecture(hostname)
        dtslogger.info(f'Detected device architecture is "{endpoint_arch}".')
        # get copy of environment
        env = {}
        env.update(os.environ)
        # add ARCH
        env["ARCH"] = endpoint_arch
        env["REGISTRY"] = registry_to_use
        # -d/--detach
        docker_arguments = []
        if parsed.detach:
            docker_arguments.append("--detach")
        # process each stack
        for stack in stacks:
            # TODO: When processing multiple stacks with a single project name, 
            # all stacks will use the same project name, which could cause conflicts in Docker Compose.
            # The project name should be unique per stack or derived from each individual stack name.
            project_name = parsed.project or stack.replace("/", "_")
            # sanitize stack
            stack_name = stack if "/" in stack else f"{stack}/{DEFAULT_STACK}"
            # check stack
            stack_cmd_dir = pathlib.Path(__file__).parent.parent.absolute()
            stack_file = os.path.join(stack_cmd_dir, "stacks", stack_name) + ".yaml"
            if not os.path.isfile(stack_file):
                dtslogger.error(f"Stack [{project_name}]({stack_name}) not found.")
                continue
            # parse stack file once for both pre-flight steps below
            with open(stack_file, "r") as fin:
                stack_content = yaml.safe_load(fin)
            # pull images
            processed: Set[str] = set()
            if parsed.pull:
                for service in stack_content["services"].values():
                    image_name = service["image"].replace("${ARCH}", endpoint_arch)
                    image_name = image_name.replace("${REGISTRY}", registry_to_use)
                    if image_name in processed:
                        continue
                    dtslogger.info(f"Pulling image `{image_name}`...")
                    processed.add(image_name)
                    try:
                        pull_image_OLD(image_name, hostname)
                    except NotFound:
                        msg = f"Image '{image_name}' not found on registry '{registry_to_use}'. Aborting."
                        dtslogger.error(msg)
                        continue
            # Reconcile compose project labels. Containers declared with
            # `container_name:` are global by name; if one exists under a
            # different compose project (or no project at all, e.g. a stale
            # `docker run` leftover), docker compose refuses to (re)create it
            # ("container name already in use"). Happens on fresh Raspberry Pi
            # flashes where `dt-run-basics-stacks` brings up robot/basics with
            # project `basics` while stack/up falls back to the compose-file
            # parent dir, and on robots carrying orphan containers from prior
            # ad-hoc runs.
            target_project = stack_content.get("name") or os.path.basename(
                os.path.dirname(stack_file)
            )
            declared_container_names = {
                svc["container_name"]
                for svc in stack_content.get("services", {}).values()
                if "container_name" in svc
            }
            if declared_container_names:
                try:
                    robot_client = get_client_OLD(hostname)
                    for cname in declared_container_names:
                        try:
                            ctr = robot_client.containers.get(cname)
                        except NotFound:
                            continue
                        existing_project = ctr.labels.get(
                            "com.docker.compose.project", ""
                        )
                        if existing_project == target_project:
                            continue
                        reason = (
                            f"compose project '{existing_project}' != '{target_project}'"
                            if existing_project
                            else f"orphan (no compose project label) blocking '{target_project}'"
                        )
                        dtslogger.info(
                            f"Removing legacy container '{cname}' ({reason}) "
                            f"to let stack [{target_project}]({stack_name}) recreate it."
                        )
                        try:
                            if ctr.status == "running":
                                ctr.stop(timeout=10)
                            ctr.remove(force=True)
                        except Exception as e:
                            dtslogger.warning(
                                f"Could not remove conflicting container '{cname}': {e}"
                            )
                except Exception as e:
                    dtslogger.warning(
                        f"Could not check for conflicting containers on '{robot}': {e}"
                    )
            # print info
            dtslogger.info(f"Running stack [{project_name}]({stack_name})...")
            print("------>")
            # run docker compose stack
            H = f"{hostname}:{DEFAULT_DOCKER_TCP_PORT}"
            start_command_in_subprocess(
                ["docker", f"--host={H}", "compose", "--file", stack_file, "up"]
                + docker_arguments,
                env=env,
            )
            print("<------")
        return True
