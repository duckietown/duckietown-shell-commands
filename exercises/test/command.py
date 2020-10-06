import argparse

# from git import Repo # pip install gitpython
import os
import platform
import subprocess
import nbformat  # install before?
from nbconvert.exporters import PythonExporter
import yaml
import requests
from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.docker_utils import build_if_not_exist, \
    default_env, remove_if_running, get_remote_client, \
    pull_if_not_exist
from utils.networking_utils import get_duckiebot_ip
from utils.cli_utils import check_program_dependency

usage = """

## Basic usage
    This is an helper for the exercises. 
    You must run this command inside an exercise folder. 

    To know more on the `exercise` commands, use `dts duckiebot exercise -h`.

        $ dts exercise test --duckiebot_name [DUCKIEBOT_NAME]

"""



BRANCH="daffy"
DEFAULT_ARCH="amd64"
REMOTE_ARCH="arm32v7"
AIDO_REGISTRY="registry-stage.duckietown.org"
ROSCORE_IMAGE="ros:noetic-ros-core" # arch is prefix
SIMULATOR_IMAGE="duckietown/challenge-aido_lf-simulator-gym:" + BRANCH # no arch
ROS_TEMPLATE_IMAGE="duckietown/challenge-aido_lf-template-ros:" + BRANCH
VNC_IMAGE="duckietown/dt-gui-tools:" + BRANCH + "-amd64" # always on amd64
MIDDLEWARE_IMAGE="duckietown/mooc-fifos-connector:" + BRANCH # no arch
CAR_INTERFACE_IMAGE="duckietown/dt-car-interface:" + BRANCH
BRIDGE_IMAGE="duckietown/dt-duckiebot-fifos-bridge:" + BRANCH

DEFAULT_REMOTE_USER = "duckie"

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
            + "this is not expected to work on MacOSX",
        )

        parser.add_argument(
            "--debug",
            dest="debug",
            action="store_true",
            default=False,
            help="See extra debugging output",
        )


        parsed = parser.parse_args(args)

        # get the local docker client
        local_client = check_docker_environment()



        # let's do all the input checks

        duckiebot_name = parsed.duckiebot_name
        if duckiebot_name is None and not parsed.sim:
            msg = "You must specify a duckiebot_name or run in the simulator"
            raise InvalidUserInput(msg)

        if not parsed.local and parsed.sim:
            dtslogger.info("Note: Running locally since we are using simulator")
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

        # done input checks



        #
        #   get current working directory to check if it is an exercise directory
        #
        working_dir = os.getcwd()
        if not os.path.exists(working_dir + "/config.yaml"):
            msg = "You must run this command inside the exercise directory"
            raise InvalidUserInput(msg)
        env_dir = working_dir + "/assets/setup/"

        if parsed.local:
            agent_client = local_client
            arch = DEFAULT_ARCH
        else:
            # let's set some things up to run on the Duckiebot
            check_program_dependency('rsync')
            remote_base_path = f"{DEFAULT_REMOTE_USER}@{parsed.duckiebot_name}.local:/code/"
            dtslogger.info(f"Syncing your code with {parsed.duckiebot_name}")
            exercise_ws_dir = working_dir + "/exercise_ws"
            exercise_cmd = f"rsync --archive {exercise_ws_dir} {remote_base_path}"
            _run_cmd(exercise_cmd, shell=True)
            launcher_dir = working_dir + "/launchers"
            launcher_cmd = f"rsync --archive {launcher_dir} {remote_base_path}"
            _run_cmd(launcher_cmd, shell=True)

            # arch
            arch = REMOTE_ARCH
            agent_client = duckiebot_client


        # let's update the images based on arch
        if not parsed.local:
            ros_image = f"{arch}/{ROSCORE_IMAGE}"
        else:
            ros_image = ROSCORE_IMAGE

        ros_template_image = f"{ros_template_image}-{arch}"
        car_interface_image = f"{CAR_INTERFACE_IMAGE}-{arch}"
        bridge_image = f"{BRIDGE_IMAGE}-{arch}"


            # let's clean up any mess from last time
        sim_container_name = "challenge-aido_lf-simulator-gym"
        remove_if_running(agent_client, sim_container_name)
        ros_container_name = "ros_core"
        remove_if_running(agent_client, ros_container_name)
        vnc_container_name = "dt-gui-tools"
        remove_if_running(local_client, vnc_container_name)  # vnc always local
        middleware_container_name = "mooc-fifos-connector"
        remove_if_running(agent_client, middleware_container_name)
        car_interface_container_name = "dt-car-interface"
        remove_if_running(agent_client, car_interface_container_name)
        ros_template_container_name = "challenge-aido_lf-template-ros"
        remove_if_running(agent_client, ros_template_container_name)
        bridge_container_name = "dt-duckiebot-fifos-bridge"
        remove_if_running(agent_client, bridge_container_name)

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

        # are we running on a mac?
        if "darwin" in platform.system().lower():
            running_on_mac = True
        else:
            running_on_mac = False # if we aren't running on mac we're on Linux

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

        default_env = load_yaml(env_dir + "default_env.yaml")

        # Launch things one by one

        if parsed.sim:

            # let's launch the simulator

            sim_env = load_yaml(env_dir + "sim_env.yaml")
            sim_env = {**sim_env, **default_env}

            dtslogger.info("Running %s" % sim_container_name )
            sim_params = {
                "image": sim_image,
                "name": sim_container_name,
                "network": agent_network.name,
                "environment": sim_env,
                "volumes": fifos_bind,
                "tty": True,
                "detach": True,
            }
            if parsed.debug:
                dtslogger.info(sim_params)

            pull_if_not_exist(agent_client, sim_params["image"])
#            sim_container = agent_client.containers.run(**sim_params)

            # let's launch the middleware_manager
            dtslogger.info("Running the middleware manager")
            middleware_env = load_yaml(env_dir + "middleware_env.yaml")
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
 #           mw_container = agent_client.containers.run(**mw_params)

        else: # we are running on a duckiebot

            # let's launch the duckiebot fifos bridge, note that this one runs in a different
            # ROS environment, the one on the robot
            dtslogger.info("Running the duckiebot/fifos bridge")
            bridge_env = {
                "HOSTNAME": f"{duckiebot_name}",
                "VEHICLE_NAME": f"{duckiebot_name}",
                "ROS_MASTER_URI": f"http://{duckiebot_name}.local:11311"
            }
            bridge_volumes = fifos_bind
            bridge_volumes["/var/run/avahi-daemon/socket"] = {"bind": "/var/run/avahi-daemon/socket", "mode": "rw"}

            bridge_params = {
                "image": bridge_image,
                "name": bridge_container_name,
                "environment": bridge_env,
                "network_mode": "host",
                "volumes": fifos_bind,
                "detach": True,
                "tty": True,
            }
            pull_if_not_exist(agent_client, bridge_params["image"])
 #           bridge_container = agent_client.containers.run(**bridge_params)

        # done with sim/duckiebot stuff.

        # let's launch the ros-core

        dtslogger.info("Running %s" % ros_container_name)
        agent_ros_env = {'ROS_MASTER_URI': "http://ros_core:11311"}

        ros_port = {"11311/tcp": ("0.0.0.0", 11311)}
        ros_params = {
            "image": ros_image,
            "name": ros_container_name,
            "network": agent_network.name,
            "environment": agent_ros_env,
            "ports": ros_port,
            "detach": True,
            "tty": True,
            "command": "roscore",
        }
        if parsed.debug:
            dtslogger.info(ros_params)
        pull_if_not_exist(agent_client, ros_params["image"])
        ros_container = agent_client.containers.run(**ros_params)

        # let's launch vnc
        dtslogger.info("Running %s" % vnc_container_name)
        vnc_port = {"8087/tcp": ("0.0.0.0", 8087)}
        vnc_env = {'ROS_MASTER_URI': "http://ros_core:11311"}
        vnc_params = {
            "image": VNC_IMAGE,
            "name": vnc_container_name,
            "command": "dt-launcher-vnc",
            "network": agent_network.name,
            "environment": vnc_env,
            "ports": vnc_port,
            "detach": True,
            "tty": True,
        }

        if parsed.debug:
            dtslogger.info(vnc_params)

        # vnc always runs on local client
        pull_if_not_exist(local_client, vnc_params["image"])
        vnc_container = local_client.containers.run(**vnc_params)


        # let's launch the car interface
        dtslogger.info("Running the car interface")
        car_params = {
            "image": car_interface_image,
            "name": car_interface_container_name,
            "environment": agent_ros_env,
            "network": agent_network.name,
            "detach": True,
            "tty": True
        }

        pull_if_not_exist(agent_client, car_params["image"])
 #       car_container = agent_client.containers.run(**car_params)

        # Let's launch the ros template
        # TODO read from the config.yaml file which template we should launch
        dtslogger.info("Running the ros template")

        ros_template_env = load_yaml(env_dir + "ros_template_env.yaml")
        ros_template_env = {**agent_ros_env, **ros_template_env}
        ros_template_volumes = fifos_bind

        if parsed.sim or parsed.local:
            ros_template_volumes[working_dir+"/assets"] = {"bind": "/data/config", "mode": "rw"}
            ros_template_volumes[working_dir + "/launchers"] = {"bind": "/code/launchers", "mode": "rw"}
            ros_template_volumes[working_dir + "/exercise_ws"] = {"bind": "/code/exercise_ws", "mode": "rw"}
        else:
            ros_template_volumes["/data/config"] = {"bind": "/data/config", "mode": "rw"}
            ros_template_volumes["/code/launchers"] = {"bind": "/code/launchers", "mode": "rw"}
            ros_template_volumes["/code/exercise_ws"] = {"bind": "/code/exercise_ws", "mode": "rw"}


        if parsed.local and not parsed.sim:
            # get the calibrations from the robot with the REST API
            get_calibration_files(working_dir+"/assets", parsed.duckiebot_name)

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
 #       ros_template_container = agent_client.containers.run(**ros_template_params)






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


def _run_cmd(cmd, get_output=False, print_output=False, suppress_errors=False, shell=False):
    if shell and isinstance(cmd, (list, tuple)):
        cmd = " ".join([str(s) for s in cmd])
    dtslogger.debug("$ %s" % cmd)
    if get_output:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=shell)
        proc.wait()
        if proc.returncode != 0:
            if not suppress_errors:
                msg = "The command {} returned exit code {}".format(cmd, proc.returncode)
                dtslogger.error(msg)
                raise RuntimeError(msg)
        out = proc.stdout.read().decode("utf-8").rstrip()
        if print_output:
            print(out)
        return out
    else:
        try:
            subprocess.check_call(cmd, shell=shell)
        except subprocess.CalledProcessError as e:
            if not suppress_errors:
                raise e


# get the calibration files off the robot
def get_calibration_files(destination_dir, duckiebot_name):
    dtslogger.info("Getting all calibration files")

    calib_files = [
        "config/calibrations/camera_intrinsic/{duckiebot:s}.yaml",
        "config/calibrations/camera_extrinsic/{duckiebot:s}.yaml",
        "config/calibrations/kinematics/{duckiebot:s}.yaml",
    ]

    for calib_file in calib_files:
        calib_file = calib_file.format(duckiebot=duckiebot_name)
        url = "http://{:s}.local/files/{:s}".format(duckiebot_name, calib_file)
        # get calibration using the files API
        dtslogger.debug('Fetching file "{:s}"'.format(url))
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            dtslogger.warn(
                "Could not get the calibration file {:s} from the robot {:s}. Is your Duckiebot calibrated? ".format(
                    calib_file, duckiebot_name
                )
            )
            continue
        # make destination directory
        dirname = os.path.join(destination_dir, os.path.dirname(calib_file))
        if not os.path.isdir(dirname):
            dtslogger.debug('Creating directory "{:s}"'.format(dirname))
            os.makedirs(dirname)
        # save calibration file to disk
        # NOTE: all agent names in evaluations are "agent" so need to copy
        #       the robot specific calibration to default
        destination_file = os.path.join(dirname, "agent.yaml")
        dtslogger.debug(
            'Writing calibration file "{:s}:{:s}" to "{:s}"'.format(
                duckiebot_name, calib_file, destination_file
            )
        )
        with open(destination_file, "wb") as fd:
            for chunk in res.iter_content(chunk_size=128):
                fd.write(chunk)

