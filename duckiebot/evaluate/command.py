import argparse
import getpass
import os
import subprocess
import threading
import time
import requests

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import (
    continuously_monitor,
    get_remote_client,
    record_bag,
    remove_if_running,
    stop_container,
    pull_if_not_exist
)
from utils.networking_utils import get_duckiebot_ip
from dt_shell import DTShell

usage = """

## Basic usage

    Evaluates the current submission on the Duckiebot:

        $ dts duckiebot evaluate --duckiebot_name ![DUCKIEBOT_HOSTNAME]

"""

FILES_API_PORT = 8082



class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot evaluate"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        group = parser.add_argument_group("Basic")
        group.add_argument(
            "--duckiebot_name",
            default=None,
            help="Name of the Duckiebot on which to perform evaluation",
        )
        group.add_argument(
            "--image",
            dest="image_name",
            help="Image to evaluate, if none specified then we will build your current context",
            default=None,
        )
        group.add_argument(
            "--glue_node_image",
            default="duckietown/challenge-aido_lf-duckiebot:daffy",
            help="The node that glues your submission with ROS on the duckiebot. Probably don't change",
        )
        group.add_argument(
            "--duration", help="Number of seconds to run evaluation", default=15
        )
        group.add_argument(
            "--remotely",
            action="store_true",
            default=True,
            help="If true run the image over network without pushing to Duckiebot",
        )
        group.add_argument(
            "--record_bag",
            action="store_true",
            default=False,
            help="If true record a rosbag",
        )
        group.add_argument(
            "--debug",
            action="store_true",
            default=False,
            help="If true you will get a shell instead of executing",
        )
        group.add_argument(
            "--native",
            action="store_true",
            default=False,
            help="If you would like your submission to be run on the RasPI (natively)",
        )
        group.add_argument(
            "--max_vel", help="the max velocity for the duckiebot", default=0.7
        )
        group.add_argument("--challenge", help="Specific challenge to evaluate")
        # Advanced arguments
        group = parser.add_argument_group("Advanced")
        group.add_argument(
            "--docker-runtime",
            dest="docker_runtime",
            default=None,
            help="Specify the runtime to use in Docker",
        )
        # ---
        parsed = parser.parse_args(args)
        tmpdir = "/tmp"
        USERNAME = getpass.getuser()
        dir_home_guest = os.path.expanduser("~")
        dir_fake_home = os.path.join(tmpdir, "fake-%s-home" % USERNAME)
        if not os.path.exists(dir_fake_home):
            os.makedirs(dir_fake_home)

        if not parsed.native:
            # if we are running remotely then we need to copy over the calibration
            # files from the robot and setup some tmp directories to mount
            get_calibration_files(dir_fake_home, parsed.duckiebot_name)

        duckiebot_ip = get_duckiebot_ip(parsed.duckiebot_name)
        if (parsed.native):
            dtslogger.info("Attempting to run natively on the robot")
            client = get_remote_client(duckiebot_ip)
        else:
            dtslogger.info("Attempting to run remotely on this machine")
            client = check_docker_environment()

        agent_container_name = "agent"
        glue_container_name = "aido_glue"

        # remove the containers if they are already running
        remove_if_running(client, agent_container_name)
        remove_if_running(client, glue_container_name)

        # setup the fifos2 volume (requires pruning it if it's still hanging around from last time)
        try:
            client.volumes.prune()
            fifo2_volume = client.volumes.create(name="fifos2")
        except Exception as e:
            dtslogger.warn("error creating volume: %s" % e)
            raise

        duckiebot_client = get_remote_client(duckiebot_ip)
        try:
            duckiebot_containers = duckiebot_client.containers.list()
            interface_container_found = False
            for c in duckiebot_containers:
                if "duckiebot-interface" in c.name:
                    interface_container_found = True
            if not interface_container_found:
                dtslogger.error(
                    "The  duckiebot-interface is not running on the duckiebot"
                )
        except Exception as e:
            dtslogger.warn(
                "Not sure if the duckiebot-interface is running because we got and exception when trying: %s"
                % e
            )

        # let's start building stuff for the "glue" node
        glue_volumes = {fifo2_volume.name: {"bind": "/fifos", "mode": "rw"}}
        glue_env = {
            "HOSTNAME": parsed.duckiebot_name,
            "DUCKIEBOT_NAME": parsed.duckiebot_name,
            "ROS_MASTER_URI": "http://%s:11311" % duckiebot_ip,
        }

        if parsed.native:
            arch = 'arm32v7'
            machine = "%s.local" % parsed.duckiebot_name
        else:
            arch = 'amd64'
            machine = "unix:///var/run/docker.sock"

        glue_image = "%s-%s" %(parsed.glue_node_image, arch)

        dtslogger.info(
            "Running %s on %s with environment vars: %s"
            % (glue_image, machine, glue_env)
        )
        params = {
            "image": glue_image,
            "name": glue_container_name,
            "network_mode": "host",
            "privileged": True,
            "environment": glue_env,
            "detach": True,
            "tty": True,
            "volumes": glue_volumes,
        }
        if parsed.docker_runtime:
            params["runtime"] = parsed.docker_runtime

        # run the glue container
        pull_if_not_exist(client, params['image'])
        glue_container = client.containers.run(**params)

        if not parsed.debug:
            monitor_thread = threading.Thread(
                target=continuously_monitor, args=(client, glue_container.name)
            )
            monitor_thread.start()

        if parsed.image_name is None:
            # if we didn't get an `image_name` we try need to build the local container
            path = "."
            dockerfile = os.path.join(path, "Dockerfile")
            if not os.path.exists(dockerfile):
                msg = "No Dockerfile"
                raise Exception(msg)
            tag = "myimage"

            dtslogger.info("Building image for %s" % arch)
            cmd = ["docker",
                   "-H %s" % machine,
                   "build",
                   "-t", tag,
                   "--build-arg",
                   "ARCH=%s"% arch,
                   "-f", dockerfile]
            dtslogger.info("Running command: %s" % cmd)
            cmd.append(path)
            subprocess.check_call(cmd)
            image_name = tag
        else:
            image_name = parsed.image_name

        # start to build the agent stuff
        agent_env = {
            "AIDONODE_DATA_IN": "/fifos/agent-in",
            "AIDONODE_DATA_OUT": "fifo:/fifos/agent-out",
        }

        agent_volumes = {
            fifo2_volume.name: {"bind": "/fifos", "mode": "rw"},
            dir_fake_home: {"bind": "/data", "mode": "rw"},
        }

        params = {
            "image": image_name,
            "remove": True,
            "name": agent_container_name,
            "environment": agent_env,
            "detach": True,
            "tty": True,
            "volumes": agent_volumes,
        }

        if parsed.debug:
            params["command"] = "/bin/bash"
            params["stdin_open"] = True

        dtslogger.info(
            "Running %s on localhost with environment vars: %s"
            % (image_name, agent_env)
        )
        pull_if_not_exist(client, params['image'])
        agent_container = client.containers.run(**params)

        if parsed.debug:
            attach_cmd = "docker attach %s" % agent_container_name
            start_command_in_subprocess(attach_cmd)

        else:
            monitor_thread = threading.Thread(
                target=continuously_monitor, args=(client, agent_container_name)
            )
            monitor_thread.start()

        duration = int(parsed.duration)
        # should we record a bag?
        if parsed.record_bag:
            bag_container = record_bag(parsed.hostname, duration)
        else:
            bag_container = None
        dtslogger.info("Running for %d s" % duration)
        time.sleep(duration)
        stop_container(glue_container)
        stop_container(agent_container)

        if bag_container is not None:
            stop_container(bag_container)


# get the calibration files off the robot
def get_calibration_files(destination_dir, duckiebot_name):
    dtslogger.info("Getting all calibration files")

    calib_files = [
        'config/calibrations/camera_intrinsic/{duckiebot:s}.yaml',
        'config/calibrations/camera_extrinsic/{duckiebot:s}.yaml',
        'config/calibrations/kinematics/{duckiebot:s}.yaml'
    ]

    for calib_file in calib_files:
        calib_file = calib_file.format(duckiebot=duckiebot_name)
        url = 'http://{:s}.local:{:d}/{:s}'.format(
            duckiebot_name, FILES_API_PORT, calib_file
        )
        # get calibration using the files API
        dtslogger.debug('Fetching file "{:s}"'.format(url))
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            dtslogger.error("Could not get the calibration file {:s} from the robot {:s}".format(
                calib_file, duckiebot_name
            ))
            return
        # make destination directory
        dirname = os.path.join(destination_dir, os.path.dirname(calib_file))
        if not os.path.isdir(dirname):
            dtslogger.debug('Creating directory "{:s}"'.format(dirname))
            os.makedirs(dirname)
        # save calibration file to disk
        # NOTE: all agent names in evaluations are "default" so need to copy
        #       the robot specific calibration to default
        destination_file = os.path.join(dirname, 'default.yaml')
        dtslogger.debug('Writing calibration file "{:s}:{:s}" to "{:s}"'.format(
            duckiebot_name, calib_file, destination_file
        ))
        with open(destination_file, 'wb') as fd:
            for chunk in res.iter_content(chunk_size=128):
                fd.write(chunk)
