import os
import argparse

import docker
from dt_shell import DTCommandAbs, DTShell, dtslogger

from disk_image.create.utils import pull_docker_image
from utils.duckietown_utils import get_distro_version, USER_DATA_DIR

DISK_NAME = "root"
VIRTUAL_FLEET_DIR = os.path.join(USER_DATA_DIR, "virtual_robots")
VIRTUAL_ROBOT_RUNTIME_IMAGE = "duckietown/dt-virtual-device:{distro}-amd64"


class DTCommand(DTCommandAbs):

    help = "Boots up a Virtual Duckiebot"

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot virtual start"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument(
            "--pull",
            action='store_true',
            default=False,
            help="Update the runtime image"
        )
        parser.add_argument("robot", nargs=1, help="Name of the Robot to start")
        # parse arguments
        parsed = parser.parse_args(args)
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        # get version
        distro = get_distro_version(shell)
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
        local_docker = docker.from_env()
        try:
            local_docker.containers.get(f"dts-virtual-{parsed.robot}")
            dtslogger.error(f"Another instance of the virtual robot '{parsed.robot}' was found, "
                            f"you cannot have two copies of the same robot running.")
            return
        except docker.errors.NotFound:
            # good
            pass
        # launch robot
        runtime_image = VIRTUAL_ROBOT_RUNTIME_IMAGE.format(distro=distro)
        if parsed.pull:
            dtslogger.info("Downloading virtual robot runtime...")
            # pull dind image
            pull_docker_image(local_docker, runtime_image)
        # runtime
        local_docker.containers.run(
            image=runtime_image,
            detach=True,
            remove=True,
            privileged=True,
            name=f"dts-virtual-{parsed.robot}",
            hostname=parsed.robot,
            volumes={
                "/sys/fs/cgroup": {
                    "bind": "/sys/fs/cgroup",
                    "mode": "ro"
                },
                os.path.join(vbot_root_dir, "data"): {
                    "bind": "/data",
                    "mode": "rw"
                },
                os.path.join(vbot_root_dir, "var", "lib", "docker"): {
                    "bind": "/var/lib/docker",
                    "mode": "rw"
                },
                os.path.join(vbot_root_dir, "boot"): {
                    "bind": "/boot",
                    "mode": "rw"
                },
            }
        )
        # ---
        print()
        dtslogger.info("Your virtual robot is booting up. "
                       "It should appear on 'dts fleet discover' soon.")
