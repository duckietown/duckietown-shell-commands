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
    pull_if_not_exist, pull_image
from utils.networking_utils import get_duckiebot_ip
from utils.cli_utils import check_program_dependency, start_command_in_subprocess

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
ROSCORE_IMAGE="duckietown/dt-commons:" + BRANCH
SIMULATOR_IMAGE="duckietown/challenge-aido_lf-simulator-gym:" + BRANCH # no arch
ROS_TEMPLATE_IMAGE="duckietown/challenge-aido_lf-template-ros:" + BRANCH
VNC_IMAGE="duckietown/dt-gui-tools:" + BRANCH + "-amd64" # always on amd64
MIDDLEWARE_IMAGE="duckietown/mooc-fifos-connector:" + BRANCH # no arch
BRIDGE_IMAGE="duckietown/dt-duckiebot-fifos-bridge:" + BRANCH

DEFAULT_REMOTE_USER = "duckie"
AGENT_ROS_PORT = "11312"

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

        parser.add_argument(
            "--pull",
            dest="pull",
            action="store_true",
            default=False,
            help="Should we pull all of the images"
        )

        parser.add_argument(
            "--restart_agent",
            "-r",
            dest="restart_agent",
            action="store_true",
            default=False,
            help="Flag to only restart the agent container and nothing else. Useful when you are developing your agent"
        )

        parser.add_argument(
            "--interactive",
            "-i",
            dest="interactive",
            action="store_true",
            default=False,
            help="Will run the agent in interactive mode with the code mounted"
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
        exercise_name = os.path.basename(working_dir)
        dtslogger.info(f"Running exercise {exercise_name}")
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
            remote_base_path = f"{DEFAULT_REMOTE_USER}@{duckiebot_name}.local:/code/"
            dtslogger.info(f"Syncing your local folder with {duckiebot_name}")
#            exercise_ws_dir = working_dir + "/exercise_ws"
            exercise_cmd = f"rsync --archive {working_dir} {remote_base_path}"
            _run_cmd(exercise_cmd, shell=True)
#            launcher_dir = working_dir + "/launchers"
#            launcher_cmd = f"rsync --archive {launcher_dir} {remote_base_path}"
#            _run_cmd(launcher_cmd, shell=True)

            # arch
            arch = REMOTE_ARCH
            agent_client = duckiebot_client

        # let's clean up any mess from last time
        sim_container_name = "challenge-aido_lf-simulator-gym"
        ros_container_name = "ros_core"
        vnc_container_name = "dt-gui-tools"
        middleware_container_name = "mooc-fifos-connector"
        ros_template_container_name = "agent"
        bridge_container_name = "dt-duckiebot-fifos-bridge"

        if parsed.restart_agent:
            remove_if_running(agent_client, ros_template_container_name)
            remove_if_running(agent_client, bridge_container_name)
        else:
            remove_if_running(agent_client, sim_container_name)
            remove_if_running(agent_client, ros_container_name)
            remove_if_running(local_client, vnc_container_name)  # vnc always local
            remove_if_running(agent_client, middleware_container_name)
            remove_if_running(agent_client, ros_template_container_name)
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

        if parsed.stop:
            exit(0)

        # done cleaning




        if not parsed.local:
            ros_env = {
                "ROS_MASTER_URI": f"http://{duckiebot_ip}:{AGENT_ROS_PORT}",
                }
        else:
            ros_env = {
                "ROS_MASTER_URI": f"http://{ros_container_name}:{AGENT_ROS_PORT}"
            }
            if parsed.sim:
                ros_env["VEHICLE_NAME"] = "agent"
                ros_env["HOSTNAME"] = "agent"
            else:
                ros_env["VEHICLE_NAME"] = duckiebot_name
                ros_env["HOSTNAME"] = duckiebot_name


        # let's update the images based on arch
        ros_image = f"{ROSCORE_IMAGE}-{arch}"
        ros_template_image = f"{ros_template_image}-{arch}"
        bridge_image = f"{BRIDGE_IMAGE}-{arch}"



        # let's see if we should pull the images
        local_images = [VNC_IMAGE, middle_image, sim_image]
        agent_images = [bridge_image, ros_image, ros_template_image]

        if parsed.pull:
            for image in local_images:
                dtslogger.info(f"Pulling {image}")
                pull_image(image, local_client)
            for image in agent_images:
                dtslogger.info(f"Pulling {image}")
                pull_image(image, agent_client)


        if not parsed.restart_agent:
            try:
                agent_network = agent_client.networks.create(
                    "agent-network", driver="bridge")
            except Exception as e:
                dtslogger.warn("error creating network: %s" % e)

            try:
                fifos_volume = agent_client.volumes.create(name="fifos")
            except Exception as e:
                dtslogger.warn("error creating volume: %s" % e)
                raise
        else:
            try:
                agent_network = agent_client.networks.get("agent-network")
            except Exception as e:
                dtslogger.warn("error getting network: %s" % e)
            try:
                fifos_volume = agent_client.volumes.get("fifos")
            except Exception as e:
                dtslogger.warn("error getting volume: %s" % e)

        fifos_bind = {fifos_volume.name: {"bind": "/fifos", "mode": "rw"}}

        # are we running on a mac?
        if "darwin" in platform.system().lower():
            running_on_mac = True
        else:
            running_on_mac = False # if we aren't running on mac we're on Linux


        if parsed.restart_agent:
            launch_bridge(bridge_container_name, duckiebot_name, fifos_bind, bridge_image, parsed,
                  running_on_mac, agent_client)
            launch_agent(ros_template_container_name, env_dir, ros_env, fifos_bind,
                 parsed, working_dir, exercise_name, ros_template_image, agent_network,
                 agent_client, duckiebot_name)
            exit(0)



        # Launch things one by one

        if parsed.sim:
            # let's launch the simulator

            sim_env = load_yaml(env_dir + "sim_env.yaml")

            dtslogger.info("Running %s" % sim_container_name )
            sim_params = {
                "image": sim_image,
                "name": sim_container_name,
                "network": agent_network.name, # always local
                "environment": sim_env,
                "volumes": fifos_bind,
                "tty": True,
                "detach": True,
            }


            if parsed.debug:
                dtslogger.info(sim_params)

            pull_if_not_exist(agent_client, sim_params["image"])
            sim_container = agent_client.containers.run(**sim_params)

            # let's launch the middleware_manager
            dtslogger.info("Running %s" % middleware_container_name)
            middleware_env = load_yaml(env_dir + "middleware_env.yaml")
            middleware_port = {"8090/tcp": ("0.0.0.0", 8090)}
            mw_params = {
                "image": middle_image,
                "name": middleware_container_name,
                "environment": middleware_env,
                "ports": middleware_port,
                "network": agent_network.name, # always local
                "volumes": fifos_bind,
                "detach": True,
                "tty": True,
            }

            if parsed.debug:
                dtslogger.info(mw_params)

            pull_if_not_exist(agent_client, mw_params["image"])
            mw_container = agent_client.containers.run(**mw_params)

        else: # we are running on a duckiebot
            launch_bridge(bridge_container_name, duckiebot_name, fifos_bind, bridge_image, parsed,
                  running_on_mac, agent_client)

        # done with sim/duckiebot specific stuff.

        # let's launch the ros-core

        dtslogger.info("Running %s" % ros_container_name)

        ros_port = {f"{AGENT_ROS_PORT}/tcp": ("0.0.0.0", AGENT_ROS_PORT)}
        ros_params = {
            "image": ros_image,
            "name": ros_container_name,
            "environment": ros_env,
            "ports": ros_port,
            "detach": True,
            "tty": True,
            "command": f"roscore -p {AGENT_ROS_PORT}",
        }

        if parsed.local:
            ros_params["network"] = agent_network.name
        else:
            ros_params["network_mode"] = "host"


        if parsed.debug:
            dtslogger.info(ros_params)
        pull_if_not_exist(agent_client, ros_params["image"])
        ros_container = agent_client.containers.run(**ros_params)

        # let's launch vnc
        dtslogger.info("Running %s" % vnc_container_name)
        vnc_port = {"8087/tcp": ("0.0.0.0", 8087)}
        vnc_env = ros_env
        if not parsed.local:
            vnc_env["VEHICLE_NAME"] = duckiebot_name
            vnc_env["ROS_MASTER"] = duckiebot_name
            vnc_env["HOSTNAME"] = duckiebot_name
        vnc_params = {
            "image": VNC_IMAGE,
            "name": vnc_container_name,
            "command": "dt-launcher-vnc",
            "environment": vnc_env,
            "stream": True,
            "ports": vnc_port,
            "detach": True,
            "tty": True,
        }

        if parsed.local:
            vnc_params["network"] = agent_network.name
        else:
            if not running_on_mac:
                vnc_params["network_mode"] = "host"

        if parsed.debug:
            dtslogger.info(vnc_params)

        # vnc always runs on local client
        pull_if_not_exist(local_client, vnc_params["image"])
        vnc_container = local_client.containers.run(**vnc_params)

        launch_agent(ros_template_container_name, env_dir, ros_env, fifos_bind,
                     parsed, working_dir, exercise_name, ros_template_image, agent_network,
                     agent_client, duckiebot_name)


        dtslogger.info("All done")


def launch_agent(ros_template_container_name, env_dir, ros_env, fifos_bind,
                 parsed, working_dir, exercise_name, ros_template_image, agent_network,
                 agent_client, duckiebot_name):
    # Let's launch the ros template
    # TODO read from the config.yaml file which template we should launch
    dtslogger.info("Running the %s" % ros_template_container_name)

    ros_template_env = load_yaml(env_dir + "ros_template_env.yaml")
    ros_template_env = {**ros_env, **ros_template_env}
    ros_template_volumes = fifos_bind

    if parsed.sim or parsed.local:
        ros_template_volumes[working_dir + "/assets"] = {"bind": "/data/config", "mode": "rw"}
        ros_template_volumes[working_dir + "/launchers"] = {"bind": "/code/launchers", "mode": "rw"}
        ros_template_volumes[working_dir + "/exercise_ws"] = {"bind": "/code/exercise_ws", "mode": "rw"}
    else:
        ros_template_volumes[f"/data/config"] = {"bind": "/data/config", "mode": "rw"}
        ros_template_volumes[f"/code/{exercise_name}/launchers"] = {"bind": "/code/launchers", "mode": "rw"}
        ros_template_volumes[f"/code/{exercise_name}/exercise_ws"] = {"bind": "/code/exercise_ws", "mode": "rw"}

    if parsed.local and not parsed.sim:
        # get the calibrations from the robot with the REST API
        get_calibration_files(working_dir + "/assets", parsed.duckiebot_name)

    ros_template_params = {
        "image": ros_template_image,
        "name": ros_template_container_name,
        "volumes": ros_template_volumes,
        "environment": ros_template_env,
        "detach": True,
        "tty": True,
        "command": ["/code/launchers/run_all.sh"]
    }

    if parsed.local:
        ros_template_params["network"] = agent_network.name
    else:
        ros_template_params["network_mode"] = "host"

    if parsed.interactive:
        ros_template_params["command"] = "/bin/bash"
        ros_template_params["stdin_open"] = True

    if parsed.debug:
        dtslogger.info(ros_template_params)

    pull_if_not_exist(agent_client, ros_template_params["image"])
    ros_template_container = agent_client.containers.run(**ros_template_params)

    attach_cmd = "docker %s attach %s" % (
        "" if parsed.local else f"-H {duckiebot_name}.local", ros_template_container_name)
    start_command_in_subprocess(attach_cmd)



def launch_bridge(bridge_container_name, duckiebot_name, fifos_bind, bridge_image, parsed,
                  running_on_mac, agent_client):
    # let's launch the duckiebot fifos bridge, note that this one runs in a different
    # ROS environment, the one on the robot
    dtslogger.info("Running %s" % bridge_container_name)
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
        "network_mode": "host",  # bridge always on host
        "volumes": fifos_bind,
        "detach": True,
        "tty": True,
    }

    # if we are local - we need to have a network so that the hostname
    # matches the ROS_MASTER_URI or else ROS complains. If we are running on the
    # Duckiebot we set the hostname to be the duckiebot name so we can use host mode
    if parsed.local and running_on_mac:
        dtslogger.warn(
            "WARNING: Running agent locally not in simulator is not expected to work. Suggest to remove the --local flag")

    if parsed.debug:
        dtslogger.info(bridge_params)

    pull_if_not_exist(agent_client, bridge_params["image"])
    bridge_container = agent_client.containers.run(**bridge_params)


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

