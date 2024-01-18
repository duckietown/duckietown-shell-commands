import argparse
import os
import socket
from subprocess import run, CalledProcessError

import docker
from dt_shell import DTCommandAbs, DTShell, dtslogger

from utils.git_utils import clone_repository
from utils.networking_utils import get_duckiebot_ip
class DTCommand(DTCommandAbs):

    help = "Connects a terminal to a Virtual Duckiebot"

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot virtual gazebo-connect-duckiedrone"
        parser = argparse.ArgumentParser(prog=prog)
        default_listen_addr = "172.17.0.1"

        # define arguments
        parser.add_argument("robot", nargs=1, help="Name of the Robot to connect to")
        parser.add_argument("--listen-addr", default=default_listen_addr, help=f"Address of the host machine (default: {default_listen_addr})")
        parser.add_argument("--fdm-address", help="Address of the FDM (Flight Dynamics Model) to connect to (default: <robot>.local)")
        # parse arguments
        parsed = parser.parse_args(args)
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        # make sure the virtual robot exists
        local_docker = docker.from_env()
        try:
            local_docker.containers.get(f"dts-virtual-{parsed.robot}")
        except docker.errors.NotFound:
            dtslogger.error(f"No running virtual robot found with name '{parsed.robot}'")
            return
        repo_name = "duckietown/vehicle_gateway"
        destination_dir = "/tmp"

        # Clone the GitHub repository `duckietown/vehicle_gateway` to a temporary folder
        dtslogger.info(f"Cloning the GitHub repository {repo_name} to {destination_dir}")

        # If the repo is already cloned, delete it
        full_repo_path = os.path.join(destination_dir + "/vehicle_gateway")
        if os.path.exists(full_repo_path):
            run(["rm", "-rf", full_repo_path])

        repo_dir = clone_repository(repo_name, "ente", destination_dir)

        # Run the command `docker compose up` in the `repo_dir` folder, with environment variables VEH set to parsed.robot and ROS_IP set to the hostname of the local machine + .local
        hostname = socket.gethostname()

        _ENV = {
            "VEH": parsed.robot,
            "ROS_IP": hostname + ".local",
            "DISPLAY": os.environ["DISPLAY"],
            "LISTEN_ADDR": parsed.listen_addr,
            "FDM_ADDR": parsed.fdm_address if parsed.fdm_address else get_duckiebot_ip(parsed.robot),
        }

        dtslogger.info(f"Running the command `docker compose up` in the {repo_dir} folder, with environment variables {_ENV}")
        # Enable the X server connection by running `xhost +local:root`
        run(["xhost", "+local:root"])
        try:
            run(["docker", "compose", "up"], cwd=repo_dir, env=_ENV, check=True)
        except CalledProcessError as e:
            dtslogger.error("Something went wrong while connecting to the virtual robot")
            print(e.stderr)
        # Disable the X server connection by running `xhost -local:root`
        run(["xhost", "-local:root"])
