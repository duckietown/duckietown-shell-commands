import argparse
import os
import random
import re
import time
from typing import Optional

import docker
from dt_shell import DTCommandAbs, DTShell, dtslogger

from disk_image.create.constants import \
    AUTOBOOT_STACKS_DIR, \
    MODULES_TO_LOAD, \
    DOCKER_IMAGE_TEMPLATE
from disk_image.create.utils import \
    list_files,\
    run_cmd,\
    replace_in_file,\
    pull_docker_image
from utils.docker_utils import get_registry_to_use
from utils.duckietown_utils import get_robot_types, get_robot_configurations, USER_DATA_DIR
from utils.misc_utils import pretty_json, pretty_exc

from ..destroy.command import DTCommand as DestroyVirtualDuckiebotCommand

DEVICE_ARCH = "amd64"
DISK_NAME = "root"
DEFAULT_STACK = "duckietown"
DIND_IMAGE_NAME = "docker:24.0-dind"
VIRTUAL_FLEET_DIR = os.path.join(USER_DATA_DIR, "virtual_robots")
COMMAND_DIR = os.path.dirname(os.path.abspath(__file__))
COMMANDS_DIR = os.path.join(COMMAND_DIR, "..", "..", "..")
STACKS_DIR = os.path.join(COMMANDS_DIR, "stack", "stacks", DEFAULT_STACK)
DISK_TEMPLATE_DIR = os.path.join(COMMANDS_DIR, "disk_image", "create", "virtual", "disk_template")


class DTCommand(DTCommandAbs):

    help = "Creates a new Virtual Duckiebot"

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot virtual create"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument(
            "-t", "--type",
            type=str,
            required=True,
            choices=get_robot_types(),
            help="Type of Duckiebot to create"
        )
        parser.add_argument(
            "-c",
            "--configuration",
            type=str,
            help="Configuration of Duckiebot to create"
        )
        parser.add_argument("robot", nargs=1, help="Name of the Robot to create")
        # get version
        distro: str = shell.profile.distro.name
        # parse arguments
        parsed = parser.parse_args(args)
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        if not re.match("[a-z][a-z0-9]", parsed.robot):
            dtslogger.error(
                "Robot name can only contain letters and numbers and cannot start with a number.")
            return
        # get registry
        registry_to_use: str = get_registry_to_use()
        # get the robot configuration
        allowed_configs = get_robot_configurations(parsed.type)
        if parsed.configuration is None:
            dtslogger.info(
                f"You did not specify a robot configuration.\n"
                f"Given that your robot is a {parsed.type}, possible "
                f"configurations are: {', '.join(allowed_configs)}"
            )
            # ---
            while True:
                r = input("Insert your robot's configuration: ")
                if r.strip() in allowed_configs:
                    parsed.configuration = r.strip()
                    break
                dtslogger.warning(f"Configuration '{r}' not recognized. Please, retry.")
        # validate robot configuration
        if parsed.configuration not in allowed_configs:
            dtslogger.error(
                f"Robot configuration {parsed.configuration} not recognized "
                f"for robot type {parsed.type}. Possible configurations "
                f"are: {', '.join(allowed_configs)}"
            )
            exit(2)
        dtslogger.info(f"Robot configuration: {parsed.configuration}")
        # make dirs
        os.makedirs(VIRTUAL_FLEET_DIR, exist_ok=True)
        vbot_dir = os.path.join(VIRTUAL_FLEET_DIR, parsed.robot)
        # make sure another virtual duckiebot with the same name does not exist
        if os.path.exists(vbot_dir):
            dtslogger.error("Another virtual robot already exists with the same name.")
            return
        # create virtual bot directory
        dtslogger.info(f"Create root directory for your virtual robot at {vbot_dir}.")
        os.makedirs(vbot_dir)
        # from this point on, if anything weird happens, stop and remove partial virtual bot
        remote_docker_engine_container = None
        try:
            # copy root
            vbot_root_dir = os.path.join(vbot_dir, DISK_NAME)
            origin = os.path.join(DISK_TEMPLATE_DIR, DISK_NAME)
            dtslogger.info("Copying skeleton root disk to the root of your virtual robot.")
            run_cmd(["cp", "-r", origin, vbot_root_dir])
            # copy stacks
            for stack in list_files(STACKS_DIR, "yaml"):
                origin = os.path.join(STACKS_DIR, stack)
                destination = os.path.join(vbot_root_dir, AUTOBOOT_STACKS_DIR.lstrip("/"), stack)
                # copy new file
                run_cmd(["cp", origin, destination])
                # add architecture as default value in the stack file
                dtslogger.debug(
                    "- Replacing '{ARCH}' with '{ARCH:-%s}' in %s" % (DEVICE_ARCH, destination)
                )
                replace_in_file("{ARCH}", "{ARCH:-%s}" % DEVICE_ARCH, destination, open)
                # add registry as default value in the stack file
                dtslogger.debug(
                    "- Replacing '{REGISTRY}' with '{REGISTRY:-%s}' in %s" % (registry_to_use, destination)
                )
                replace_in_file("{REGISTRY}", "{REGISTRY:-%s}" % registry_to_use, destination, open)
            # download docker images
            dtslogger.info("Transferring Docker images to your virtual robot.")
            local_docker = docker.from_env()
            # pull dind image
            pull_docker_image(local_docker, DIND_IMAGE_NAME)
            # run auxiliary Docker engine
            remote_docker_dir = os.path.join(vbot_root_dir, "var", "lib", "docker")
            creator_container_name = f"dts-duckiebot-virtual-create-env-{parsed.robot}"
            creator_container_args = {
                "image": DIND_IMAGE_NAME,
                "detach": True,
                "remove": True,
                "auto_remove": True,
                "publish_all_ports": False,
                "privileged": True,
                "name": creator_container_name,
                "volumes": {remote_docker_dir: {"bind": "/var/lib/docker", "mode": "rw"}},
                "entrypoint": ["dockerd", "--host=tcp://0.0.0.0:2375", "--bridge=none"],
            }
            dtslogger.debug(f"Creating virtual robot DIND container with configuration:\n"
                            f"{pretty_json(creator_container_args, indent=4)}")
            remote_docker_engine_container = local_docker.containers.run(**creator_container_args)
            time.sleep(1)
            # get IP address of the container
            container_info = local_docker.api.inspect_container(creator_container_name)
            container_ip = container_info["NetworkSettings"]["IPAddress"]
            # create remote docker client
            endpoint_url = f"tcp://{container_ip}:2375"
            dtslogger.debug(f"DIND endpoint: {endpoint_url}")
            # wait for the engine to come up
            dtslogger.info("Waiting up to 30 seconds for your new robot to start...")
            t0: float = time.time()
            remote_docker: Optional[docker.DockerClient] = None
            while time.time() - t0 < 30:
                time.sleep(2)
                try:
                    remote_docker = docker.DockerClient(base_url=endpoint_url)
                    dtslogger.debug(f"docker.version(): {remote_docker.version()}")
                except Exception:
                    continue
                break
            if remote_docker is None:
                dtslogger.fatal("Failed to bring up a virtual Docker engine for your virtual robot. "
                                "Add the flag 'dts --debug duckiebot virtual ...' to get more information.")
                exit(1)
            # ---
            dtslogger.info("Testing virtual Docker environment...")
            dtslogger.info(f" - Detected version: {remote_docker.version()['Version']}")
            dtslogger.info(f"The robot is now up, transferring images...")
            # from this point on, if anything weird happens, stop container and unmount disk
            try:
                # pull images inside the disk image
                for module in MODULES_TO_LOAD:
                    image = DOCKER_IMAGE_TEMPLATE(
                        owner=module["owner"],
                        module=module["module"],
                        version=distro,
                        tag=module["tag"] if "tag" in module else None,
                        arch=DEVICE_ARCH,
                        registry=module.get("registry", registry_to_use)
                    )
                    pull_docker_image(remote_docker, image)
                # ---
                dtslogger.info("Docker images successfully transferred!")
            except Exception as e:
                # warn user
                dtslogger.warn(f"Docker images failed to be transferred! "
                               f"You will need to run 'dts duckiebot update {parsed.robot}' to "
                               f"complete the setup.")
                raise e
            finally:
                # stop container
                remote_docker_engine_container.stop()
                remote_docker_engine_container = None
            # perform surgery
            # - data/config/robot_type
            with open(os.path.join(vbot_root_dir, "data", "config", "robot_type"), "wt") as fout:
                fout.write(parsed.type)
            # - data/config/robot_configuration
            with open(os.path.join(vbot_root_dir, "data", "config", "robot_configuration"), "wt") as fout:
                fout.write(parsed.configuration)
            # - data/config/robot_distro
            with open(os.path.join(vbot_root_dir, "data", "config", "robot_distro"), "wt") as fout:
                fout.write(shell.profile.distro.name)
            # - data/stats/MAC/eth0
            with open(os.path.join(vbot_root_dir, "data", "stats", "MAC", "eth0"), "wt") as fout:
                fout.write(random_virtual_mac_address())
        except Exception as e:
            # warn user
            dtslogger.error(f"An error occurred while creating the virtual robot. Error:\n{pretty_exc(e, 4)}")
            # attempt to stop container
            if remote_docker_engine_container:
                remote_docker_engine_container.stop()
            # remove partial virtual bot
            DestroyVirtualDuckiebotCommand.command(shell, ["--yes", parsed.robot])
            # ---
            raise e
        finally:
            pass
        # ---
        print()
        print()
        dtslogger.info("Your virtual robot was created successfully.")
        dtslogger.info(f"You can now run it using the command "
                       f"'dts duckiebot virtual start {parsed.robot}'.")


def random_virtual_mac_address() -> str:
    """
    Generates a random MAC address of the form:     vv:**:**:**:**:**
    And while this is not a valid MAC address (because it is not base16-decodable), it allows us
    to distinguish between virtual robot IDs and physical robot IDs (using vv:) while giving us
    the peace of mind that no physical robot can have a MAC address overlapping with a virtual
    MAC address. Moreover, as we use the full alphabet 0-9a-z, it allows for 36^10 possible virtual
    MAC addresses.

    :return: a fake virtual MAC address
    """
    c = lambda: random.choice('1234567890abcdefghijklmnopqrstuvwxyz')
    return "vv:%s%s:%s%s:%s%s:%s%s:%s%s" % (c(), c(), c(), c(), c(), c(), c(), c(), c(), c())
