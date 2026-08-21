import os
import argparse
import time

import docker as dockerpy
from dockertown import DockerClient
from dt_shell import DTCommandAbs, DTShell, dtslogger

from ...startup_logs.common import stream_local_virtual_robot_startup_logs
from ..gateway import (
    GATEWAY_PORT_MAPPINGS,
    gateway_leader_election,
    gateway_leader_options,
    refresh_gateway_backends,
    should_start_gateway,
)
from disk_image.create.utils import pull_docker_image
from utils.duckietown_utils import USER_DATA_DIR
from utils.misc_utils import pretty_yaml
from utils.docker_utils import get_endpoint_architecture

DISK_NAME = "root"
VIRTUAL_FLEET_DIR = os.path.join(USER_DATA_DIR, "virtual_robots")
VIRTUAL_ROBOT_RUNTIME_IMAGE = "duckietown/dt-virtual-device:{distro}-{arch}"


class DTCommand(DTCommandAbs):

    help = "Boots up a Virtual Duckiebot"

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot virtual start"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument(
            "--no-pull",
            action='store_true',
            default=False,
            help="Do not update the runtime image"
        )
        parser.add_argument(
            "--pull",
            action='store_true',
            default=False,
            dest="deprecated_pull",
            help=argparse.SUPPRESS
        )
        parser.add_argument(
            "-t",
            "--tag",
            type=str,
            default=shell.profile.distro.name,
            help="Tag of the robot runtime image to use"
        )
        parser.add_argument(
            "--no-logs",
            action="store_true",
            default=False,
            help="Do not stream startup logs",
        )
        parser.add_argument("robot", nargs=1, help="Name of the Robot to start")
        # parse arguments
        parsed = parser.parse_args(args)
        if parsed.deprecated_pull:
            dtslogger.warning("The '--pull' option is deprecated and no longer needed; "
                              "the runtime image is updated by default. "
                              "Use '--no-pull' to skip the update.")
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        # make sure the virtual robot exists
        vbot_dir = os.path.join(VIRTUAL_FLEET_DIR, parsed.robot)
        if not os.path.isdir(vbot_dir):
            dtslogger.error(f"No virtual robots found with name '{parsed.robot}'")
            return
        vbot_root_dir = os.path.join(vbot_dir, DISK_NAME)
        if not os.path.isdir(vbot_root_dir):
            dtslogger.error(f"No virtual disk found with name '{DISK_NAME}' "
                            f"for robot '{parsed.robot}'")
            return
        # make sure the virtual robot is not running already
        local_docker = dockerpy.from_env()
        docker = DockerClient()
        try:
            local_docker.containers.get(f"dts-virtual-{parsed.robot}")
            dtslogger.error(f"Another instance of the virtual robot '{parsed.robot}' was found, "
                            f"you cannot have two copies of the same robot running.")
            return
        except dockerpy.errors.NotFound:
            # good
            pass
        # launch robot
        runtime_image = VIRTUAL_ROBOT_RUNTIME_IMAGE.format(distro=parsed.tag, arch=get_endpoint_architecture())
        if not parsed.no_pull:
            dtslogger.info("Downloading virtual robot runtime...")
            pull_docker_image(local_docker, runtime_image)
        # create named volumes for each directory
        volumes = []
        volume_names = []
        _, dirs, _ = next(os.walk(vbot_root_dir))
        for dir in dirs:
            # ignore var directory (still use bind mount for Docker daemon data)
            if dir in ['var']:
                continue
            # create named volume for each directory
            volume_name = f"dts-virtual-{parsed.robot}-{dir}"
            container_path = f"/{dir}"
            volumes.append((volume_name, container_path, "rw"))
            volume_names.append(volume_name)

        # ensure Docker volumes exist and are populated
        _ensure_volumes_exist(local_docker, parsed.robot, vbot_root_dir, volume_names, dirs)

        # runtime - using Docker volumes instead of bind mounts for better integration
        # Docker volumes provide auto-copy feature and better isolation
        opts = {
            "image": runtime_image,
            "hostname": parsed.robot,
            "privileged": True,
            "name": f"dts-virtual-{parsed.robot}",
            "detach": True,
            "remove": True,
            "cgroupns": "private",
            "volumes": [
                # Keep var/lib/docker as bind mount for Docker daemon data
                (os.path.join(vbot_root_dir, "var", "lib", "docker"), "/var/lib/docker", "rw"),
                # Use named volumes for other directories
                *volumes
            ]
        }
        dtslogger.debug(f"Booting up virtual robot '{parsed.robot}' with the following options:"
                        f"\n{pretty_yaml(opts, indent=4)}\n")
        startup_started_at = time.time()
        with gateway_leader_election():
            if should_start_gateway(local_docker):
                refresh_gateway_backends(local_docker)
                environment, labels, state_volume = gateway_leader_options()
                opts["envs"] = environment
                opts["labels"] = labels
                opts["publish"] = GATEWAY_PORT_MAPPINGS
                container_volumes = opts["volumes"]
                container_volumes.append(state_volume)
                dtslogger.info(f"Virtual robot '{parsed.robot}' will route fleet browser traffic.")
            container_client = docker.container
            container_client.run(**opts)
            refresh_gateway_backends(local_docker)
        dtslogger.info("Your virtual robot is booting up. "
                       "It should appear on 'dts fleet discover' soon.")
        if not parsed.no_logs:
            dtslogger.info("Streaming startup logs...")
            stream_local_virtual_robot_startup_logs(
                parsed.robot,
                startup_started_at=startup_started_at,
                local_docker=local_docker,
            )


def _ensure_volumes_exist(local_docker, robot_name, vbot_root_dir, volume_names, dirs):
    """
    Ensure Docker volumes exist for the virtual robot and populate them with initial data.
    
    Args:
        local_docker: Docker client instance
        robot_name: Name of the virtual robot
        vbot_root_dir: Path to the virtual robot's root directory on host
        volume_names: List of volume names to create
        dirs: List of directory names that correspond to the volumes
    """
    for volume_name, dir_name in zip(volume_names, [d for d in dirs if d != 'var']):
        # Check if volume exists
        try:
            volume = local_docker.volumes.get(volume_name)
            dtslogger.debug(f"Volume {volume_name} already exists")
            # Volume exists, check if it's empty and needs to be populated
            # We'll use a temporary container to check and populate if needed
            host_dir_path = os.path.join(vbot_root_dir, dir_name)
            _populate_volume_if_needed(local_docker, volume_name, host_dir_path, dir_name)
        except dockerpy.errors.NotFound:
            # Volume doesn't exist, create it
            dtslogger.debug(f"Creating volume {volume_name}")
            volume = local_docker.volumes.create(name=volume_name)
            # Populate the new volume with data from host directory
            host_dir_path = os.path.join(vbot_root_dir, dir_name)
            _populate_volume_from_host(local_docker, volume_name, host_dir_path, dir_name)


def _populate_volume_if_needed(local_docker, volume_name, host_dir_path, container_path):
    """
    Check if a volume is empty and populate it if needed.
    """
    # Use a temporary container to check if volume is empty
    try:
        result = local_docker.containers.run(
            image="alpine:latest",
            command=["sh", "-c", f"ls -la /{container_path} | wc -l"],
            volumes={volume_name: {"bind": f"/{container_path}", "mode": "rw"}},
            remove=True,
            detach=False
        )
        # If result is "3" or less, the directory is effectively empty (only . and .. entries)
        line_count = int(result.decode().strip())
        if line_count <= 3:
            dtslogger.debug(f"Volume {volume_name} is empty, populating from host")
            _populate_volume_from_host(local_docker, volume_name, host_dir_path, container_path)
        else:
            dtslogger.debug(f"Volume {volume_name} already contains data")
    except Exception as e:
        dtslogger.debug(f"Could not check volume {volume_name}, assuming it needs population: {e}")
        _populate_volume_from_host(local_docker, volume_name, host_dir_path, container_path)


def _populate_volume_from_host(local_docker, volume_name, host_dir_path, container_path):
    """
    Populate a Docker volume with data from a host directory.
    """
    if not os.path.exists(host_dir_path):
        dtslogger.debug(f"Host directory {host_dir_path} does not exist, skipping population")
        return
        
    dtslogger.debug(f"Populating volume {volume_name} from {host_dir_path}")
    
    # Use a temporary container to copy data from host to volume
    local_docker.containers.run(
        image="alpine:latest",
        command=["sh", "-c", f"cp -r /source/* /{container_path}/ 2>/dev/null || true"],
        volumes={
            host_dir_path: {"bind": "/source", "mode": "ro"},
            volume_name: {"bind": f"/{container_path}", "mode": "rw"}
        },
        remove=True,
        detach=False
    )
