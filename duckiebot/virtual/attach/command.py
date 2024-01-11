import argparse
import os
from subprocess import PIPE, run, CalledProcessError

import docker
from dt_shell import DTCommandAbs, DTShell, dtslogger

from utils.git_utils import clone_repository

class DTCommand(DTCommandAbs):

    help = "Connects a terminal to a Virtual Duckiebot"

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot virtual attach"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument("robot", nargs=1, help="Name of the Robot to connect to")
        parser.add_argument("--gazebo", action="store_true", help="Connect to the Gazebo simulation instead of the Duckiematrix (available for Duckiedrones only)")
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
        # Clone the GitHub repository `duckietown/vehicle_gateway` to a temporary folder
        dtslogger.info("Cloning the GitHub repository `duckietown/vehicle_gateway` to a temporary folder")
        
        # If the repo is already cloned, delete it
        if os.path.exists("/tmp/vehicle_gateway"):
            run(["rm", "-rf", "/tmp/vehicle_gateway"])
        repo_dir = clone_repository("duckietown/vehicle_gateway", "ente", "/tmp")

        # Run the command `docker compose up` in the `repo_dir` folder, with environment variables VEH set to parsed.robot and ROS_IP set to the hostname of the local machine + .local
        hostname: str = run(["hostname"], stdout=PIPE).stdout.decode("utf-8")
        # Remove the newline character from the hostname
        hostname = hostname.splitlines()[0]

        _ENV = {'VEH': parsed.robot, 'ROS_IP': hostname+'.local', 'DISPLAY': os.environ['DISPLAY']}

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
        
