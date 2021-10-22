import argparse
import getpass
import json
import os
import platform
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import grp
from docker.errors import APIError

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.env_checks import check_docker_environment
from duckietown_docker_utils import ENV_REGISTRY
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import get_client, pull_if_not_exist, remove_if_running
from utils.exceptions import InvalidUserInput
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
            dtslogger.info(
                "The exercise configuration file 'config.yaml' does not have a "
                "'lab_dir' key to indicate where notebooks are stored. We will not build the labs"
            )
        else:
            labdir = os.path.join(working_dir, labdir_name)
            if not os.path.exists(labdir) or not os.path.isdir(labdir):
                msg = (
                    f"The lab dir f{labdir_name} that is specified in your config file  "
                    f"doesn't seem to exist."
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
                    path=labdir, tag=lab_image_name, dockerfile="Dockerfile.lab", decode=True
                )
                dtslogger.info("Building environment...")
                try:
                    for log in logs:
                        if "stream" in log:
                            sys.stdout.write(log["stream"])
                    sys.stdout.flush()
                except APIError as e:
                    dtslogger.error(str(e))
                    exit(1)
                dtslogger.info("Environment built!")

        # make sure this exercise has a ws_dir key in its config file and that it points to
        # an existing directory
        wsdir_name = config.get("ws_dir", None)
        if wsdir_name is None:
            raise ValueError(
                "The exercise configuration file 'config.yaml' does not have a "
                "'ws_dir' key to indicate where the solution is stored"
            )

        wsdir = os.path.join(working_dir, wsdir_name)
        if not os.path.exists(wsdir) or not os.path.isdir(wsdir):
            msg = (
                f"You must run this command inside an exercise directory "
                f"containing a `{wsdir_name}` directory."
            )
            raise InvalidUserInput(msg)

        use_ros = config.get("ros", False)

        # Convert all the notebooks listed in the config file to python scripts and
        # move them in the specified package in the exercise ws.
        # Copy fiels listed in the config.yaml into the target_dir
        if "files" in config:
            convert_notebooks(config["files"])

        REGISTRY = os.getenv(ENV_REGISTRY, "docker.io")

        def add_registry(x):
            if REGISTRY in x:
                raise
            return REGISTRY + "/" + x

        if use_ros:

            ws_dir = config["ws_dir"]
            client = check_docker_environment()
            ros_template_image = add_registry(ROS_TEMPLATE_IMAGE)

            if parsed.debug:
                cmd = ["bash"]
            elif parsed.clean:
                cmd = ["catkin", "clean", "--workspace", f"{ws_dir}"]
            else:
                cmd = ["catkin", "build", "--workspace", f"{ws_dir}"]

            container_name = "ros_template_catkin_build"
            remove_if_running(client, container_name)
            ros_template_volumes = {working_dir + f"/{ws_dir}": {"bind": f"/code/{ws_dir}", "mode": "rw"}}
            on_mac = "Darwin" in platform.system()
            if on_mac:
                group_add = []
            else:
                group_add = [g.gr_gid for g in grp.getgrall() if getpass.getuser() in g.gr_mem]

            FAKE_HOME_GUEST = "/fake-home"
            with TemporaryDirectory() as tmpdir:
                fake_home_host = os.path.join(tmpdir, "fake-home")
                os.makedirs(fake_home_host)

                ros_template_volumes[fake_home_host] = {"bind": FAKE_HOME_GUEST, "mode": "rw"}

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
                    "environment": {
                        "USER": getpass.getuser(),
                        "USERID": os.getuid(),
                        "HOME": FAKE_HOME_GUEST,
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                    "user": os.getuid(),
                    "group_add": group_add,
                }

                dtslogger.debug(
                    f"Running with configuration:\n\n"
                    f"{json.dumps(ros_template_params, indent=4, sort_keys=True)}"
                )
                pull_if_not_exist(client, ros_template_params["image"])
                client.containers.run(**ros_template_params)
                attach_cmd = f"docker attach {container_name}"
                start_command_in_subprocess(attach_cmd)

        # The problem with the below is that it presumes that we are in a repo called `mooc-exercises`
        # which is not a good assumption
        # up = check_up_to_date(shell, "mooc-exercises")
        # dtslogger.debug(up.commit.sha)
        # if not up.uptodate:
        #     n = datetime.now(tz=pytz.utc)
        #     delta = n - up.commit.date
        #     hours = delta.total_seconds() / (60 * 60)
        #     dtslogger.warn(f"The repo has been updated {hours:.1f} hours ago. "
        #                    f"Please merge from upstream.")
        #     dtslogger.warn(f"Commit {up.commit.url}")
        # else:
        #     dtslogger.debug("OK, up to date ")

        dtslogger.info("Build complete")
