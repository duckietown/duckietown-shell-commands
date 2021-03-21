import argparse
# from git import Repo # pip install gitpython
import os

import nbformat  # install before?
import yaml
from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from nbconvert.exporters import PythonExporter

from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import pull_if_not_exist, remove_if_running

usage = """

## Basic usage
    This is a helper for the exercises. 
    You must run this command inside an exercise folder. 

    To know more on the `exercise` commands, use `dts duckiebot exercise -h`.

        $ dts exercise build 

"""

BRANCH = "daffy"
ARCH = "amd64"
AIDO_REGISTRY = "registry-stage.duckietown.org"
ROS_TEMPLATE_IMAGE = "duckietown/challenge-aido_lf-template-ros:" + BRANCH + "-" + ARCH


class InvalidUserInput(Exception):
    pass


from dt_shell import DTShell


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
        if not os.path.exists(working_dir + "/config.yaml"):
            msg = "You must run this command inside the exercise directory"
            raise InvalidUserInput(msg)

        config = load_yaml(working_dir + "/config.yaml")
        ws_dir = config['ws_dir']

        exercise_ws_src = working_dir + "/" + ws_dir+ "/src/"

        # Convert all the notebooks listed in the config file to python scripts and
        # move them in the specified package in the exercise ws.
        for notebook in config["notebooks"]:
            print(notebook['notebook'])
            package_dir = exercise_ws_src + notebook['notebook']["package_name"]
            notebook_name = notebook['notebook']["name"]
            convertNotebook(working_dir+f"/notebooks/{notebook_name}.ipynb", notebook_name, package_dir)


        client = check_docker_environment()

        if parsed.staging:
            ros_template_image = AIDO_REGISTRY + "/" + ROS_TEMPLATE_IMAGE
        else:
            ros_template_image = ROS_TEMPLATE_IMAGE

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
        attach_cmd = "docker attach %s" % container_name
        start_command_in_subprocess(attach_cmd)

        dtslogger.info("Build complete")


def convertNotebook(filepath, export_path) -> bool:
    if not os.path.exists(filepath):
        return False
    nb = nbformat.read(filepath, as_version=4)
    exporter = PythonExporter()

    # source is a tuple of python source code
    # meta contains metadata
    source, _ = exporter.from_notebook_node(nb)
    try:
        with open(export_path, "w+") as fh:
            fh.writelines(source)
    except Exception:
        return False

    return True


def load_yaml(file_name):
    with open(file_name) as f:
        try:
            env = yaml.load(f, Loader=yaml.FullLoader)
        except Exception as e:
            dtslogger.warn("error reading simulation environment config: %s" % e)
        return env
