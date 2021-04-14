import argparse
import getpass
import os
import sys
from pathlib import Path

import docker
from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import pull_if_not_exist, remove_if_running, get_client
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
        exercise_name = Path(working_dir).stem
        dtslogger.info(f"Exercise name: {exercise_name}")

        # make sure we are in an exercise directory
        cfile_name = "config.yaml"
        cfile = os.path.join(working_dir, cfile_name)
        if not os.path.exists(cfile):
            msg = (
                f"You must run this command inside an exercise directory "
                f"containing a `{cfile_name}` file."
            )
            raise InvalidUserInput(msg)
        config = load_yaml(cfile)

        # make sure this exercise has a lab_dir key in its config file and that it points to
        # an existing directory
        labdir_name = config.get("lab_dir", None)
        if labdir_name is None:
            raise ValueError("The exercise configuration file 'config.yaml' does not have a "
                             "'lab_dir' key to indicate where notebooks are stored")
        labdir = os.path.join(working_dir, labdir_name)
        if not os.path.exists(labdir) or not os.path.isdir(labdir):
            msg = (
                f"You must run this command inside an exercise directory "
                f"containing a `{labdir_name}` directory."
            )
            raise InvalidUserInput(msg)

        # make sure this exercise has a ws_dir key in its config file and that it points to
        # an existing directory
        wsdir_name = config.get("ws_dir", None)
        if wsdir_name is None:
            raise ValueError("The exercise configuration file 'config.yaml' does not have a "
                             "'ws_dir' key to indicate where code is stored")
        wsdir = os.path.join(working_dir, wsdir_name)
        if not os.path.exists(wsdir) or not os.path.isdir(wsdir):
            msg = (
                f"You must run this command inside an exercise directory "
                f"containing a `{wsdir_name}` directory."
            )
            raise InvalidUserInput(msg)

        # make sure this exercise has a Dockerfile.lab file
        dockerfile_lab_name = "Dockerfile.lab"
        dockerfile_lab = os.path.join(working_dir, dockerfile_lab_name)

        if os.path.exists(dockerfile_lab) and os.path.isfile(dockerfile_lab):
            # build notebook image
            lab_image_name = f"{getpass.getuser()}/exercise-{exercise_name}-lab"
            client = get_client()
            logs = client.api.build(
                path=labdir,
                tag=lab_image_name,
                dockerfile="Dockerfile.lab",
                decode=True
            )
            dtslogger.info("Building environment...")
            try:
                for log in logs:
                    if 'stream' in log:
                        sys.stdout.write(log['stream'])
                sys.stdout.flush()
            except docker.errors.APIError as e:
                dtslogger.error(str(e))
                exit(1)
            dtslogger.info("Environment built!")

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
