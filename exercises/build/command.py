import argparse
import os

from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import pull_if_not_exist, remove_if_running
from utils.notebook_utils import convert_notebooks
from utils.yaml_utils import load_yaml

usage = """

## Basic usage
    This is a helper for the exercises. 
    You must run this command inside an exercise folder. 

    To know more on the `exercise` commands, use `dts duckiebot exercise -h`.

        $ dts exercise build 

"""

BRANCH = "daffy"
ARCH = "amd64"
ROS_TEMPLATE_IMAGE = f"duckietown/challenge-aido_lf-template-ros:{BRANCH}-{ARCH}"
CF = "config.yaml"


class InvalidUserInput(UserError):
    pass


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts exercise build"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument(
            "--staging",
            "-t",
            dest="staging",
            action="store_true",
            default=False,
            help="Should we use the staging AIDO registry?",
        )

        parser.add_argument(
            "--debug",
            "-d",
            dest="debug",
            action="store_true",
            default=False,
            help="Will give you a terminal inside the container",
        )

        parser.add_argument(
            "--clean",
            "-c",
            dest="clean",
            action="store_true",
            default=False,
            help="Will clean the build",
        )

        parsed = parser.parse_args(args)

        working_dir = os.getcwd()

        if not os.path.exists(os.path.join(working_dir, "config.yaml")):
            msg = "You must run this command inside the exercise directory"
            raise InvalidUserInput(msg)
        fn = os.path.join(working_dir, CF)
        config = load_yaml(fn)
        use_ros = config.get("ros", False)

        # Convert all the notebooks listed in the config file to python scripts and
        # move them in the specified package in the exercise ws.
        # Copy fiels listed in the config.yaml into the target_dir
        if "files" in config:
            convert_notebooks(config["files"])

        REGISTRY = os.getenv("AIDO_REGISTRY", "docker.io")

        def add_registry(x):
            if REGISTRY in x:
                raise
            return REGISTRY + "/" + x

        if use_ros:

            ws_dir = config["ws_dir"]

            exercise_ws_src = working_dir + "/" + ws_dir + "/src/"

            client = check_docker_environment()

            ros_template_image = add_registry(ROS_TEMPLATE_IMAGE)

            if parsed.debug:
                cmd = "bash"
            elif parsed.clean:
                cmd = ["catkin", "clean", "--workspace", f"{ws_dir}"]
            else:
                cmd = ["catkin", "build", "--workspace", f"{ws_dir}"]

            container_name = "ros_template_catkin_build"
            remove_if_running(client, container_name)
            ros_template_volumes = {}
            ros_template_volumes[working_dir + f"/{ws_dir}"] = {"bind": f"/code/{ws_dir}", "mode": "rw"}

            ros_template_params = {
                "image": ros_template_image,
                "name": container_name,
                "volumes": ros_template_volumes,
                "command": cmd,
                "stdin_open": True,
                "tty": True,
                "detach": True,
                "remove": True,
                "stream": True,
            }

            pull_if_not_exist(client, ros_template_params["image"])
            ros_template_container = client.containers.run(**ros_template_params)
            attach_cmd = f"docker attach {container_name}"
            start_command_in_subprocess(attach_cmd)

        dtslogger.info("Build complete")
