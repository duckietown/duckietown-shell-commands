import argparse
import os
import re
import time

import docker
from dt_shell import DTCommandAbs, DTShell, dtslogger

from disk_image.create.constants import \
    AUTOBOOT_STACKS_DIR, \
    MODULES_TO_LOAD_MINIMAL, \
    DOCKER_IMAGE_TEMPLATE, \
    DEFAULT_DOCKER_REGISTRY
from disk_image.create.utils import \
    list_files,\
    run_cmd,\
    replace_in_file,\
    pull_docker_image
from utils.duckietown_utils import \
    get_distro_version,\
    get_robot_types,\
    get_robot_configurations, \
    USER_DATA_DIR

DEVICE_ARCH = "amd64"
DISK_NAME = "root"
DEFAULT_STACK = "duckietown"
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
        distro = get_distro_version(shell)
        # parse arguments
        parsed = parser.parse_args(args)
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        if not re.match("[a-z][a-z0-9]", parsed.robot):
            dtslogger.error(
                "Robot name can only contain letters and numbers and cannot start with a number.")
            return
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
        # from this point on, if anything weird happens, remove partial virtual bot
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
                    "- Replacing '{ARCH}' with '{ARCH:-%s}' in %s"
                    % (DEVICE_ARCH, destination)
                )
                replace_in_file("{ARCH}", "{ARCH:-%s}" % DEVICE_ARCH, destination, open)
                # add registry as default value in the stack file
                dtslogger.debug(
                    "- Replacing '{REGISTRY}' with '{REGISTRY:-%s}' in %s"
                    % (DEFAULT_DOCKER_REGISTRY, destination)
                )
                replace_in_file("{REGISTRY}", "{REGISTRY:-%s}" %
                                DEFAULT_DOCKER_REGISTRY, destination, open)
            # download docker images
            dtslogger.info("Transferring Docker images to your virtual robot.")
            local_docker = docker.from_env()
            # pull dind image
            pull_docker_image(local_docker, "docker:dind")
            # run auxiliary Docker engine
            remote_docker_dir = os.path.join(vbot_root_dir, "var", "lib", "docker")
            creator_container_name = f"dts-duckiebot-virtual-create-env-{parsed.robot}"
            remote_docker_engine_container = local_docker.containers.run(
                image="docker:dind",
                detach=True,
                remove=True,
                auto_remove=True,
                publish_all_ports=True,
                privileged=True,
                name=creator_container_name,
                volumes={remote_docker_dir: {"bind": "/var/lib/docker", "mode": "rw"}},
                entrypoint=["dockerd", "--host=tcp://0.0.0.0:2375", "--bridge=none"],
            )
            dtslogger.info("Waiting 20 seconds for your new robot to start...")
            time.sleep(20)
            # get IP address of the container
            container_info = local_docker.api.inspect_container(creator_container_name)
            container_ip = container_info["NetworkSettings"]["IPAddress"]
            # create remote docker client
            endpoint_url = f"tcp://{container_ip}:2375"
            dtslogger.info(f"The robot should now be up, transferring images...")
            # from this point on, if anything weird happens, stop container and unmount disk
            try:
                remote_docker = docker.DockerClient(base_url=endpoint_url)
                dtslogger.info("Transferring Docker images...")
                # pull images inside the disk image
                for module in MODULES_TO_LOAD_MINIMAL:
                    image = DOCKER_IMAGE_TEMPLATE(
                        owner=module["owner"],
                        module=module["module"],
                        version=distro,
                        tag=module["tag"] if "tag" in module else None,
                        arch=DEVICE_ARCH,
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
            # perform surgery
            # - data/config/robot_type
            with open(os.path.join(vbot_root_dir, "data", "config", "robot_type"), "wt") as fout:
                fout.write(parsed.type)
            # - data/config/robot_configuration
            with open(os.path.join(vbot_root_dir, "data", "config", "robot_configuration"),
                      "wt") as fout:
                fout.write(parsed.configuration)
        except Exception as e:
            # warn user
            dtslogger.error(f"An error occurred while creating the virtual robot.")
            # remove partial virtual bot
            run_cmd(["sudo", "rm", "-rf", vbot_dir])
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
