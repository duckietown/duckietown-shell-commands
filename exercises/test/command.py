import argparse

# from git import Repo # pip install gitpython
import os

import docker
import nbformat  # install before?
from nbconvert.exporters import PythonExporter
import yaml

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.docker_utils import build_if_not_exist, \
    default_env, remove_if_running, get_remote_client, \
    pull_if_not_exist
from utils.networking_utils import get_duckiebot_ip

usage = """

## Basic usage
    This is an helper for the exercises. 
    You must run this command inside an exercise folder. 

    To know more on the `exercise` commands, use `dts duckiebot exercise -h`.

        $ dts exercise test --duckiebot_name [DUCKIEBOT_NAME]

"""



BRANCH="daffy"
ARCH="amd64"
AIDO_REGISTRY="registry-stage.duckietown.org"
ROSCORE_IMAGE="ros:noetic-ros-core"
SIMULATOR_IMAGE="duckietown/challenge-aido_lf-simulator-gym:" + BRANCH
ROS_TEMPLATE_IMAGE="duckietown/challenge-aido_lf-template-ros:" + BRANCH + "-" + ARCH
VNC_IMAGE="duckietown/dt-gui-tools:" + BRANCH + "-amd64"
MIDDLEWARE_IMAGE="duckietown/mooc-fifos-connector:" + BRANCH
CAR_INTERFACE_IMAGE="duckietown/dt-car-interface:" + BRANCH + "-" + ARCH



class InvalidUserInput(Exception):
    pass


from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts exercise test"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument(
            "--duckiebot_name",
            "-b",
            dest="duckiebot_name",
            default=None,
            help="Name of the Duckiebot on which to run the exercise",
        )

        parser.add_argument(
            "--sim",
            "-s",
            dest="sim",
            action="store_true",
            default=False,
            help="Should we run it in the simulator instead of the real robot?",
        )

        parser.add_argument(
            "--stop",
            dest="stop",
            action="store_true",
            default=False,
            help="just stop all the containers",
        )

        parser.add_argument(
            "--staging",
            "-t",
            dest="staging",
            action="store_true",
            default=False,
            help="Should we use the staging AIDO registry?",
        )

        parser.add_argument(
            "--local",
            "-l",
            dest="local",
            action="store_true",
            default=False,
            help="Should we run the agent locally (i.e. on this machine)? Important Note: "
            + "this is not expected to work on MacOSX"
        )


        parsed = parser.parse_args(args)

        # get the local docker client
        local_client = check_docker_environment()

        duckiebot_name = parsed.duckiebot_name
        if duckiebot_name is None and not parsed.sim:
            msg = "You must specify a duckiebot_name or run in the simulator"
            raise InvalidUserInput(msg)

        if not parsed.local and parsed.sim:
            dtslogger.info("Note overriding remote flag and running locally since we are using simulator")
            parsed.local = True

        if not parsed.sim:
            duckiebot_ip = get_duckiebot_ip(duckiebot_name)
            duckiebot_client = get_remote_client(duckiebot_ip)

        if parsed.staging:
            sim_image = AIDO_REGISTRY + "/" + SIMULATOR_IMAGE
            middle_image = AIDO_REGISTRY + "/" + MIDDLEWARE_IMAGE
            ros_template_image = AIDO_REGISTRY + "/" + ROS_TEMPLATE_IMAGE
        else:
            sim_image = SIMULATOR_IMAGE
            middle_image = MIDDLEWARE_IMAGE
            ros_template_image = ROS_TEMPLATE_IMAGE



        #
        #   get current working directory to check if it is an exercise directory
        #
        working_dir = os.getcwd()
        if not os.path.exists(working_dir + "/config.yaml"):
            msg = "You must run this command inside the exercise directory"
            raise InvalidUserInput(msg)
        env_dir = "/assets/setup/"

        if parsed.local:
            agent_client = local_client
        else:
            agent_client = duckiebot_client

        # let's clean up any mess from last time

        sim_container_name = "gym_simulator"
        remove_if_running(agent_client, sim_container_name)
        ros_container_name = "ros_core"
        remove_if_running(agent_client, ros_container_name)
        vnc_container_name = "vnc"
        remove_if_running(agent_client, vnc_container_name)
        middleware_container_name = "middleware"
        remove_if_running(agent_client, middleware_container_name)
        car_interface_container_name = "car_interface"
        remove_if_running(agent_client, car_interface_container_name)
        ros_template_container_name = "ros_template"
        remove_if_running(agent_client, ros_template_container_name)

        try:
            dict = agent_client.networks.prune()
            dtslogger.info("Successfully removed network %s" % dict)
        except Exception as e:
            dtslogger.warn("error removing volume: %s" % e)

        try:
            dict = agent_client.volumes.prune()
            dtslogger.info("Successfully removed volume %s" % dict)
        except Exception as e:
            dtslogger.warn("error removing volume: %s" % e)

        # done cleaning

        if parsed.stop:
            exit(0)

        # now let's build the network and volume

        try:
            agent_network = agent_client.networks.create("agent-network", driver="bridge")
        except Exception as e:
            dtslogger.warn("error creating network: %s" % e)

        try:
            fifos_volume = agent_client.volumes.create(name="fifos")
            fifos_bind = {fifos_volume.name: {"bind": "/fifos", "mode": "rw"}}
        except Exception as e:
            dtslogger.warn("error creating volume: %s" % e)
            raise

        # load default env params used by all (or most)

        default_env = load_yaml(working_dir + env_dir + "default_env.yaml")

        # Launch things one by one

        # let's launch the simulator

        sim_env = load_yaml(working_dir + env_dir + "sim_env.yaml")
        sim_env = {**sim_env, **default_env}

        dtslogger.info("Running simulator")

        sim_params = {
            "image": sim_image,
            "name": sim_container_name,
            "network": agent_network.name,
            "environment": sim_env,
            "volumes": fifos_bind,
            "tty": True,
            "detach": True,
        }
        pull_if_not_exist(agent_client, sim_params["image"])
        sim_container = agent_client.containers.run(**sim_params)

        # let's launch the ros-core

        dtslogger.info("Running roscore")
        agent_ros_env = load_yaml(working_dir + env_dir + "ros_env.yaml")
        agent_ros_env = {**default_env, **agent_ros_env}
        agent_ros_env['ROS_MASTER_URI'] = "http://ros_core:11311"
        agent_ros_env['HOSTNAME'] = "agent"
        agent_ros_env['VEHICLE_NAME'] = "agent"

        ros_port = {"11311/tcp": ("0.0.0.0", 11311)}
        ros_params = {
            "image": ROSCORE_IMAGE,
            "name": ros_container_name,
            "network": agent_network.name,
            "environment": agent_ros_env,
            "ports": ros_port,
            "detach": True,
            "tty": True,
            "command": "roscore",
        }
        pull_if_not_exist(agent_client, ros_params["image"])
        ros_container = agent_client.containers.run(**ros_params)

        # let's launch vnc
        dtslogger.info("Running vnc")
        vnc_port = {"8087/tcp": ("0.0.0.0", 8087)}
        vnc_params = {
            "image": VNC_IMAGE,
            "name": vnc_container_name,
            "command": "dt-launcher-vnc",
            "network": agent_network.name,
            "environment": agent_ros_env,
            "ports": vnc_port,
            "detach": True,
            "tty": True,
        }
        pull_if_not_exist(agent_client, vnc_params["image"])
        vnc_container = agent_client.containers.run(**vnc_params)

        # let's launch the middleware_manager
        dtslogger.info("Running the middleware manager")
        middleware_env = load_yaml(working_dir + env_dir + "middleware_env.yaml")
        middleware_env = {**middleware_env, **default_env}
        mw_params = {
            "image": middle_image,
            "name": middleware_container_name,
            "environment": middleware_env,
            "network": agent_network.name,
            "volumes": fifos_bind,
            "detach": True,
            "tty": True,
        }

        pull_if_not_exist(agent_client, mw_params["image"])
        mw_container = agent_client.containers.run(**mw_params)

        # let's launch the car interface
        dtslogger.info("Running the car interface")
        car_params = {
            "image": CAR_INTERFACE_IMAGE,
            "name": car_interface_container_name,
            "environment": agent_ros_env,
            "network": agent_network.name,
            "detach": True,
            "tty": True
        }

        pull_if_not_exist(agent_client, car_params["image"])
        car_container = agent_client.containers.run(**car_params)

        # Let's launch the ros template
        # TODO read from the config.yaml file which template we should launch
        dtslogger.info("Running the ros template")

        ros_template_env = load_yaml(working_dir + env_dir + "ros_template_env.yaml")
        ros_template_env = {**agent_ros_env, **ros_template_env}
        ros_template_volumes = fifos_bind
        ros_template_volumes[working_dir+"/launchers"] = {"bind": "/code/launchers", "mode": "rw"}
        if parsed.sim:
            ros_template_volumes[working_dir+"/assets"] = {"bind": "/data/config", "mode": "rw"}
        ros_template_volumes[working_dir+"/exercise_ws"] = {"bind": "/code/exercise_ws", "mode": "rw"}

        ros_template_params = {
            "image": ros_template_image,
            "name": ros_template_container_name,
            "network": agent_network.name,
            "volumes": ros_template_volumes,
            "environment": ros_template_env,
            "detach": True,
            "tty": True,
            "command": "bash -c /code/launchers/run.sh"
        }

        pull_if_not_exist(agent_client, ros_template_params["image"])
        ros_template_container = agent_client.containers.run(**ros_template_params)






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