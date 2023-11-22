import argparse
import json
import os
import subprocess

import yaml

from dt_shell import DTCommandAbs, dtslogger

from dtproject import DTProject
from dtproject.types import ContainerConfiguration, DevContainerConfiguration
from cli.command import _run_cmd
from utils.docker_utils import (
    DEFAULT_MACHINE,
    get_endpoint_architecture,
    get_registry_to_use,
)

DEFAULT_MOUNTS = ["/var/run/avahi-daemon/socket", "/data"]
DEFAULT_NETWORK_MODE = "host"
DEFAULT_REMOTE_USER = "duckie"
DEFAULT_REMOTE_SYNC_LOCATION = "/code"

DEFAULT_TRUE = object()

COMPOSE_FILE_TEMPLATE = {'version': '3.8', 'services': {}}
class DTCommand(DTCommandAbs):
    help = "Runs the current project"
    
    @staticmethod
    def command(shell, args: list):
        # configure arguments
        parser = argparse.ArgumentParser()

        parser.add_argument(
            "-R",
            "--ros",
            default=None,
            help="Hostname of the machine hosting the ROS Master node",
        )
        parser.add_argument("-n", "--name", default=None, help="Name of the container")

        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the project to run"
        )

        parser.add_argument(
            "-u",
            "--username",
            default="duckietown",
            help="The docker registry username that owns the Docker image",
        )

        parser.add_argument(
            "--net",
            "--network_mode",
            dest="network_mode",
            default=DEFAULT_NETWORK_MODE,
            type=str,
            help="Docker network mode",
        )

        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            default=False,
            action="store_true",
            help="Generate the docker-compose and devcontainer.json files without building nor running the devcontainer",
        )

        parser.add_argument("docker_args", nargs="*", default=[])



        # add a fake positional argument to avoid missing the first argument starting with `-`
        try:
            idx = args.index("--")
            args = args[:idx] + ["--", "--fake"] + args[idx + 1:]
        except ValueError:
            pass
        # parse arguments
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        parsed.workdir = os.path.abspath(parsed.workdir)

        dtslogger.info("Project workspace: {}".format(parsed.workdir))
        # show info about project
        shell.include.devel.info.command(shell, args)

        # get info about project
        project = DTProject(parsed.workdir)
        devcontainer_configuration : DevContainerConfiguration = project.devcontainers['default']           # TODO: make choice of devcontainer configurable
        container_configuration : ContainerConfiguration = project.containers[devcontainer_configuration.container]
        
        # If the '__extend__' key is present, the container configuration is extended from the one specified in the '__extend__' key
        extend_from : List = container_configuration.__dict__.get('__extends__', None)
        dtslogger.debug(f"Container configurations to extend from: {extend_from}")

        if extend_from is not None:
            for container_name in extend_from:
                if container_name not in project.containers:
                    dtslogger.error(f"The container configuration '{container_name}' you want to extend from does not exist in 'containers.yaml'")
                    return

                dtslogger.debug(f"Extending container configuration from '{container_name}'")
                container_configuration.__dict__.update(project.containers[container_name].__dict__)
            container_configuration.__dict__.pop('__extends__', None)

        container_configuration.__dict__.pop('__plain__', None)

        dtslogger.debug(f"Loaded container configurations: {project.containers.__dict__.items()}")
        dtslogger.debug(f"Using the '{devcontainer_configuration.container}' container configuration: {container_configuration.__dict__.items()}")

        # registry
        registry_to_use = get_registry_to_use()

        # pick the right architecture
        arch = get_endpoint_architecture(DEFAULT_MACHINE)
        dtslogger.info(f"Target architecture automatically set to {arch}.")

        # get the module configuration
        # noinspection PyListCreation
        module_configuration_args = []
        # apply default module configuration
        module_configuration_args.append(f"--net={parsed.network_mode}")
        
        # Set docker network mode TODO

        if parsed.ros is not None:
            # Add VEHICLE_NAME as an environment variable of the container
            container_configuration.environment = {'VEHICLE_NAME': parsed.ros}

        # add default mount points
        for mountpoint in DEFAULT_MOUNTS:
            # check if the mountpoint exists
            if not os.path.exists(mountpoint):
                dtslogger.warning(
                    f"The mountpoint '{mountpoint}' does not exist. "
                    f"This can create issues inside the container."
                )
                continue

        # mount source code (if requested)
        projects_to_mount = [parsed.workdir]

        # create mount points definitions
        for project_path in projects_to_mount:
            # make sure that the project exists
            if not os.path.isdir(project_path):
                dtslogger.error(f"The path '{project_path}' is not a Duckietown project")
            # get project info
            proj = DTProject(project_path)
            
            root =  proj.path
            # get local and remote paths to code
            local_srcs, destination_srcs = proj.code_paths(root)
            container_configuration.volumes = []
            # compile mountpoints
            for local_src, destination_src in zip(local_srcs, destination_srcs):
                # Append to the list of mount points of the container_configuration
                container_configuration.volumes.append(f"{local_src}:{destination_src}")

            # get local and remote paths to launchers
            local_launchs, destination_launchs = proj.launch_paths(root)
            if isinstance(local_launchs, str):
                local_launchs = [local_launchs]
                destination_launchs = [destination_launchs]
            # compile mountpoints
            for local_launch, destination_launch in zip(local_launchs, destination_launchs):
                # Append to the list of mount points of the container_configuration
                container_configuration.volumes.append(f"{local_launch}:{destination_launch}")
                # make sure the launchers are executable
                try:
                    _run_cmd(["chmod", "a+x", os.path.join(local_launch, "*")], shell=True)
                except Exception:
                    dtslogger.warning("An error occurred while making the launchers executable. "
                                        "Things might not work as expected.")

        # create image name
        image = project.image(
            arch=arch,
            registry=registry_to_use,
            owner=parsed.username,
            version=project.distro,
        )

        container_configuration.image = image

        # docker arguments
        if not parsed.docker_args:
            parsed.docker_args = []

        # escape spaces in arguments
        parsed.docker_args = [a.replace(" ", "\\ ") for a in parsed.docker_args]

        # Add the arguments to the container_configuration
        container_configuration.args = parsed.docker_args

        # Remove the __plain__ and __extends__ keys from the container_configuration
        container_configuration.__dict__.pop('__plain__', None)
        container_configuration.__dict__.pop('__extends__', None)

        # Configure the devcontainer
        devcontainer_configuration.dockerComposeFile = "docker-compose.yml" # path to docker-compose file relative to location of devcontainer.json

        # Create docker-compose and devcontainer.json files in .devcontainer folder
        if not os.path.exists('.devcontainer') and not os.path.isdir('.devcontainer'):
            os.mkdir('.devcontainer')
        compose_file = COMPOSE_FILE_TEMPLATE

        compose_file["services"]={devcontainer_configuration.service : container_configuration.__dict__}

        with open('.devcontainer/docker-compose.yml', 'w') as yaml_file:
            yaml.dump(compose_file, yaml_file, indent=4,)

        output_file_path = ".devcontainer/devcontainer.json"

        with open(output_file_path, 'w') as json_file:
            json.dump(devcontainer_configuration.__dict__, json_file, indent=4,)

        dtslogger.info(f'Devcontainer configuration written to {output_file_path}')
        dtslogger.info("You can now open the devcontainer in your favorite editor")

        # Open the devcontainer in VSCode
        if not parsed.dry_run:
            try:
                # We cannot pass all the arguments we receive to the 'devel build' command
                shell.include.devel.build.command(shell, args=["--workdir", parsed.workdir])
                _run_cmd(["devcontainer", "open"], shell=True)
            except subprocess.CalledProcessError as e:
                # Handle the exception and output a human-friendly message
                print(f"An error occurred while running 'devcontainer open': {e}")
                print(f"Return code: {e.returncode}")
                # You can add more details as needed
                if e.returncode == 127:
                    print("The 'devcontainer' command is not installed. Please install it from VSCode\n\n")
                    print("by opening the Command Palette (Ctrl+Shift+P) and typing 'Dev Container: Install devcontainer CLI'\n\n")

    @staticmethod
    def complete(shell, word, line):
        return []

