import argparse
from ast import parse
import getpass
import json
import os
import platform
import random
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, cast, Dict, List, Optional
from tempfile import TemporaryDirectory
import grp

import requests
from docker import DockerClient
from docker.errors import APIError, NotFound
from docker.models.containers import Container
from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError
from dt_shell.env_checks import check_docker_environment
from duckietown_docker_utils import continuously_monitor
from requests import ReadTimeout

from utils.cli_utils import check_program_dependency, start_command_in_subprocess
from utils.docker_utils import (
    get_endpoint_architecture,
    get_remote_client,
    pull_if_not_exist,
    pull_image,
    remove_if_running,
)
from utils.exceptions import InvalidUserInput
from utils.misc_utils import sanitize_hostname
from utils.networking_utils import get_duckiebot_ip
from utils.notebook_utils import convert_notebooks
from utils.yaml_utils import load_yaml

usage = """

## Basic usage
    This is an helper for the oakd.
    You must run this command inside an exercise folder.

    To know more on the `oakd` commands, use `dts oakd test -h`.

        $ dts oakd test --duckiebot_name [DUCKIEBOT_NAME]

"""

BRANCH = "daffy"
DEFAULT_ARCH = "amd64"

DEFAULT_REMOTE_USER = "duckie"

PORT_VNC = 8087

OAKD_BASE_IMAGE = "duckietown/oakd-base:daffy"

class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts oakd test"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument(
            "--duckiebot_name",
            "-b",
            dest="duckiebot_name",
            default=None,
            help="Name of the Duckiebot on which to run the exercise",
        )

        parser.add_argument(
            "--interactive",
            "-i",
            dest="interactive",
            action="store_true",
            default=False,
            help="Will run the agent in interactive mode with the code mounted",
        )

        parser.add_argument(
            "-L",
            "--launcher",
            type=str,
            default="default",
            help="(Optional) Launcher to run inside the container",
        )
        
        parsed = parser.parse_args(args)

        #
        #   get current working directory to check if it is an exercise directory
        #
        working_dir = os.getcwd()
        exercise_name = os.path.basename(working_dir)
        dtslogger.info(f"Running exercise {exercise_name}")

        config_file = os.path.join(working_dir, "config.yaml")

        if not os.path.exists(config_file):
            msg = "You must run this command inside the exercise directory"
            raise InvalidUserInput(msg)

        config = load_yaml(config_file)

        if parsed.launcher is not None:
            config["agent_run_cmd"] = f"{parsed.launcher}.sh"

        use_ros = bool(config.get("ros", True))
        dtslogger.debug(f"config : {config}")
        dtslogger.debug(f"use_ros: {use_ros}")

        # get the local docker client
        local_client = check_docker_environment()

        # Keep track of the container to monitor
        # (only detached containers)
        # we will stop if one crashes
        containers_to_monitor = []

        # let's do all the input checks
        duckiebot_name = parsed.duckiebot_name
        if duckiebot_name is None:
            msg = "You must specify a duckiebot_name"
            raise InvalidUserInput(msg)

        duckiebot_ip = get_duckiebot_ip(duckiebot_name)
        duckiebot_client = get_remote_client(duckiebot_ip)
        duckiebot_hostname = sanitize_hostname(duckiebot_name)

        # done input checks

        # Convert all the notebooks listed in the config file to python scripts and
        # move them in the specified package in the exercise ws.
        # Copy fiels listed in the config.yaml into the target_dir
        if "files" in config:
            convert_notebooks(config["files"])

        # let's set some things up to run on the Duckiebot
        check_program_dependency("rsync")
        remote_base_path = f"{DEFAULT_REMOTE_USER}@{duckiebot_hostname}:/code/"
        dtslogger.info(f"Syncing your local folder with {duckiebot_name}")
        rsync_cmd = "rsync -a "
        if "rsync_exclude" in config:
            for dir in config["rsync_exclude"]:
                rsync_cmd += f"--exclude {working_dir}/{dir} "
        rsync_cmd += f"{working_dir} {remote_base_path}"
        dtslogger.info(f"rsync command: {rsync_cmd}")
        _run_cmd(rsync_cmd, shell=True)

        # arch
        arch = get_endpoint_architecture(duckiebot_hostname)
        agent_client = duckiebot_client

        agent_base_image = f"{OAKD_BASE_IMAGE}-{arch}"
        pull_if_not_exist(duckiebot_client, agent_base_image)

        # let's clean up any mess from last time
        # this is probably not needed anymore since we clean up everything on exit.
        prefix = f"ex-{exercise_name}-"
        vnc_container_name = f"{prefix}dt-gui-tools"
        agent_container_name = f"{prefix}agent"

        remove_if_running(local_client, vnc_container_name)  # vnc always local
        remove_if_running(agent_client, agent_container_name)
        try:
            d = agent_client.networks.prune()
            dtslogger.debug(f"Successfully removed network {d}")
        except Exception as e:
            dtslogger.warn(f"error removing network: {e}")

        try:
            d = agent_client.volumes.prune()
            dtslogger.debug(f"Successfully removed volume {d}")
        except Exception as e:
            dtslogger.warn(f"error removing volume: {e}")

        # done cleaning
        agent_env = {
            "VEHICLE_NAME": duckiebot_hostname.split(".")[0],
            "ROS_MASTER": duckiebot_hostname,
            "DUCKIEBOT_NAME": duckiebot_hostname,
            "ROS_MASTER_URI": "http://%s:11311" % duckiebot_ip,
            "HOSTNAME": duckiebot_hostname,
        }
        agent_env["PYTHONDONTWRITEBYTECODE"] = "1"
        ws_dir = "/" + config["ws_dir"]
        agent_volumes = {}
        agent_volumes["/run/udev"]= {"bind": "/run/udev", "mode": "ro"}
        agent_volumes["/dev/bus/usb"]= {"bind": "/dev/bus/usb", "mode": "ro"}
        agent_volumes[f"/data/config"] = {"bind": "/data/config", "mode": "rw"}
        agent_volumes[f"/code/{exercise_name}/launchers"] = {"bind": "/code/launchers", "mode": "rw"}
        dtslogger.info(f"/code/{exercise_name}{ws_dir}")
        dtslogger.info(f"/code{ws_dir}")
        agent_volumes[f"/code/{exercise_name}{ws_dir}"] = {
            "bind": f"/code{ws_dir}",
            "mode": "rw",
        }

        agent_params = {
            "image": agent_base_image,
            "name": agent_container_name,
            "volumes": agent_volumes,
            "environment": agent_env,
            "auto_remove": True,
            "detach": True,
            "tty": True,
            "command": [f"/code/launchers/{config['agent_run_cmd']}"],
            "privileged": True,
            "stream": True,
            "network_mode": "host",
            "ports": {}
        }

        if parsed.interactive:
            agent_params["command"] = "/bin/bash"
            agent_params["stdin_open"] = True

        dtslogger.debug(agent_params)

        pull_if_not_exist(agent_client, agent_params["image"])
        agent_container = agent_client.containers.run(**agent_params)

        attach_cmd = f"docker -H {duckiebot_name}.local attach {agent_container_name}"
        start_command_in_subprocess(attach_cmd)

        # Launch things one by one

        # we are running on a duckiebot

        # done with sim/duckiebot specific stuff.

        # let's launch vnc
        vnc_image = f"{getpass.getuser()}/exercise-{exercise_name}-lab"
        dtslogger.info(f"Running VNC {vnc_container_name} from {vnc_image}")
        vnc_env = {"ROS_MASTER_URI": "http://%s:11311" % duckiebot_ip}

        vnc_env["VEHICLE_NAME"] = duckiebot_name
        vnc_env["ROS_MASTER"] = duckiebot_name
        vnc_env["HOSTNAME"] = duckiebot_name

        vnc_params = {
            "image": vnc_image,
            "name": vnc_container_name,
            "command": "dt-launcher-vnc",
            "environment": vnc_env,
            "volumes": {
                os.path.join(working_dir, "launchers"): {
                        "bind": "/code/launchers",
                        "mode": "ro",
                    }
            },
            "auto_remove": True,
            "stream": True,
            "detach": True,
            "tty": True,
        }

        vnc_params["network_mode"] = "host"

        # vnc_params["ports"] = {"8087/tcp": ("0.0.0.0", PORT_VNC)}

        dtslogger.debug(f"vnc_params: {vnc_params}")

        # vnc always runs on local client
        vnc_container = local_client.containers.run(**vnc_params)
        containers_to_monitor.append(vnc_container)

        dtslogger.info(f"\n\tVNC running at http://localhost:{PORT_VNC}/\n")

        # Setup functions for monitor and cleanup

        def stop_attached_container():
            container = agent_client.containers.get(agent_container_name)
            container.reload()
            if container.status == "running":
                container.kill(signal.SIGINT)

        containers_monitor = launch_container_monitor(
            containers_to_monitor, stop_attached_container)

        # We will catch CTRL+C and cleanup containers
        signal.signal(
            signal.SIGINT,
            lambda signum, frame: clean_shutdown(
                containers_monitor, containers_to_monitor, stop_attached_container
            ),
        )

        dtslogger.info("Starting attached container")

        dtslogger.info(f"All done.")


def clean_shutdown(
    containers_monitor: "ContainersMonitor",
    containers: List[Container],
    stop_attached_container: Callable[[], None],
):
    dtslogger.info("Stopping container monitor...")
    containers_monitor.shutdown()
    while containers_monitor.is_alive():
        time.sleep(1)
    dtslogger.info("Container monitor stopped.")
    # ---
    dtslogger.info("Cleaning containers...")
    for container in containers:
        dtslogger.info(f"Stopping container {container.name}")
        try:
            container.stop()
        except NotFound:
            # all is well
            pass
        except APIError as e:
            dtslogger.info(
                f"Container {container.name} already stopped ({str(e)})")
    for container in containers:
        dtslogger.info(f"Waiting for container {container.name} to stop...")
        try:
            container.wait()
        except (NotFound, APIError, ReadTimeout):
            # all is well
            pass
    # noinspection PyBroadException
    try:
        stop_attached_container()
    except BaseException:
        dtslogger.info(f"attached container already stopped.")


def launch_container_monitor(
    containers_to_monitor: List[Container], stop_attached_container: Callable[[], None]
) -> "ContainersMonitor":
    """
    Start a daemon thread that will exit when the application exits.
    Monitor should stop everything if a containers exits and display logs.
    """
    monitor_thread = ContainersMonitor(
        containers_to_monitor, stop_attached_container)
    dtslogger.info("Starting monitor thread")
    dtslogger.info(
        f"Containers to monitor: {list(map(lambda c: c.name, containers_to_monitor))}")
    monitor_thread.start()
    return monitor_thread


class ContainersMonitor(threading.Thread):
    def __init__(self, containers_to_monitor: List[Container], stop_attached_container: Callable[[], None]):
        super().__init__(daemon=True)
        self._containers_to_monitor = containers_to_monitor
        self._stop_attached_container = stop_attached_container
        self._is_shutdown = False

    def shutdown(self):
        self._is_shutdown = True

    def run(self):
        """
        When an error is found, we display info and kill the attached thread to stop main process.
        """
        counter = -1
        check_every_secs = 5
        while not self._is_shutdown:
            counter += 1
            if counter % check_every_secs != 0:
                time.sleep(1)
                continue
            # ---
            errors = []
            dtslogger.debug(
                f"{len(self._containers_to_monitor)} container to monitor")
            for container in self._containers_to_monitor:
                try:
                    container.reload()
                except (APIError, TimeoutError):
                    continue
                status = container.status
                dtslogger.debug(
                    f"container {container.name} in state {status}")
                if status in ["exited", "dead"]:
                    errors.append(
                        {
                            "name": container.name,
                            "id": container.id,
                            "status": container.status,
                            "image": container.image.attrs["RepoTags"],
                            "logs": container.logs(),
                        }
                    )
                else:
                    dtslogger.debug("Containers monitor check passed.")

            if errors:
                dtslogger.info(
                    f"Monitor found {len(errors)} exited containers")
                for e in errors:
                    dtslogger.error(
                        f"""Monitored container exited:
                    container: {e['name']}
                    id: {e['id']}
                    status: {e['status']}
                    image: {e['image']}
                    logs: {e['logs'].decode()}
                    """
                    )
                dtslogger.info("Sending kill to container attached container")
                self._stop_attached_container()
            # sleep
            time.sleep(1)

def _run_cmd(cmd, get_output=False, print_output=False, suppress_errors=False, shell=False):
    if shell and isinstance(cmd, (list, tuple)):
        cmd = " ".join([str(s) for s in cmd])
    dtslogger.debug("$ %s" % cmd)
    if get_output:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=shell)
        proc.wait()
        if proc.returncode != 0:
            if not suppress_errors:
                msg = "The command {} returned exit code {}".format(
                    cmd, proc.returncode)
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

