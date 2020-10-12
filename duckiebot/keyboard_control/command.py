import argparse
import os
import platform
import socket
import subprocess

import docker
from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import remove_if_running, pull_if_not_exist
from utils.networking_utils import get_duckiebot_ip


JOYSTICK_COMMAND = "roslaunch virtual_joystick virtual_joystick_{mode}.launch veh:={veh}"
BRANCH = "daffy"
GUI_ARCH = "amd64"
ARCH = "arm32v7"
GUI_DEFAULT_IMAGE = "duckietown/dt-gui-tools:" + BRANCH + "-" + GUI_ARCH
CLI_DEFAULT_IMAGE = "duckietown/dt-gui-tools:" + BRANCH + "-" + ARCH
AVAHI_SOCKET = "/var/run/avahi-daemon/socket"


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot keyboard_control DUCKIEBOT_NAME"
        usage = """
Keyboard control:

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument(
            "--cli",
            dest="cli",
            default=False,
            action="store_true",
            help="A flag, if set will run with CLI instead of with GUI",
        )
        parser.add_argument("--network", default="host", help="Name of the network to connect to")
        parser.add_argument("--sim", action="store_true", default=False, help="are we running in simulator?")
        parser.add_argument(
            "--gui_image",
            default=GUI_DEFAULT_IMAGE,
            help="The base image for running the GUI, probably don't change the default",
        )
        parser.add_argument(
            "--cli_image",
            default=CLI_DEFAULT_IMAGE,
            help="The base image for running the GUI, probably don't change the default",
        )

        parser.add_argument("hostname", default=None, help="Name of the Duckiebot to control")

        parsed_args = parser.parse_args(args)

        if parsed_args.sim:
            duckiebot_ip = "sim"
        else:
            duckiebot_ip = get_duckiebot_ip(duckiebot_name=parsed_args.hostname)

        network_mode = parsed_args.network

        if not parsed_args.cli:
            run_gui_controller(parsed_args.hostname, parsed_args.gui_image, duckiebot_ip, network_mode)
        else:
            run_cli_controller(
                parsed_args.hostname, parsed_args.cli_image, duckiebot_ip, network_mode, parsed_args.sim
            )


def run_gui_controller(hostname, image, duckiebot_ip, network_mode):
    client = check_docker_environment()
    container_name = "joystick_gui_%s" % hostname
    remove_if_running(client, container_name)

    machine = (f"{hostname}.local" if not hostname.endswith(".local") else hostname)
    
    env = {
        "VEHICLE_NAME": hostname,
        "ROS_MASTER": hostname,
        "DUCKIEBOT_NAME": hostname,
        "ROS_MASTER_URI": "http://%s:11311" % machine,
        "HOSTNAME": hostname
    }
    volumes = {}
    env["QT_X11_NO_MITSHM"] = 1

    volumes["/tmp/.X11-unix"] = {"bind": "/tmp/.X11-unix", "mode": "rw"}

    # 2020-09-28 fix network resolve issue:

    if os.path.exists(AVAHI_SOCKET):
        volumes[AVAHI_SOCKET] = {"bind": AVAHI_SOCKET, "mode": "rw"}
    else:
        dtslogger.warning(
            "Avahi socket not found ({}). The container might not be able "
            "to resolve *.local hostnames.".format(AVAHI_SOCKET)
        )

    subprocess.call(["xhost", "+"])

    p = platform.system().lower()
    if "darwin" in p:
        dtslogger.warn("MacOS X is not officially supported, we don't make any promises here.")
        env["DISPLAY"] = "%s:0" % socket.gethostbyname(socket.gethostname())
    else:
        env["DISPLAY"] = os.environ["DISPLAY"]

    dtslogger.info("Running %s on localhost with environment vars: %s" % (container_name, env))

    params = {
        "image": image,
        "name": container_name,
        "network_mode": network_mode,
        "environment": env,
        "privileged": True,
        "stdin_open": True,
        "tty": True,
        "command": JOYSTICK_COMMAND.format(mode="gui", veh=hostname),
        "detach": True,
        "volumes": volumes,
    }

    pull_if_not_exist(client, params["image"])
    client.containers.run(**params)
    cmd = "docker attach %s" % container_name
    start_command_in_subprocess(cmd)


# if it's the CLI may as well run it on the robot itself.
def run_cli_controller(hostname, image, duckiebot_ip, network_mode, sim):
    if sim:
        duckiebot_client = check_docker_environment()
    else:
        duckiebot_client = docker.DockerClient("tcp://" + duckiebot_ip + ":2375")
    container_name = "joystick_cli_%s" % hostname
    remove_if_running(duckiebot_client, container_name)
    env = set_default_env(hostname, duckiebot_ip)

    dtslogger.info("Running %s on localhost with environment vars: %s" % (container_name, env))

    if not sim:
        image = image.replace("amd64", "arm32v7")

    params = {
        "image": image,
        "name": container_name,
        "network_mode": network_mode,
        "environment": env,
        "privileged": True,
        "stdin_open": True,
        "tty": True,
        "command": JOYSTICK_COMMAND.format(mode="cli", veh=hostname),
        "detach": True,
    }

    pull_if_not_exist(duckiebot_client, params["image"])
    duckiebot_client.containers.run(**params)

    cmd = "docker %s attach %s" % ("-H %s.local" % hostname if not sim else "", container_name)
    dtslogger.info("attach command: %s" % cmd)
    start_command_in_subprocess(cmd)


def set_default_env(hostname, ip):
    env = {
        "HOSTNAME": hostname,
        "ROS_MASTER": hostname,
        "VEHICLE_NAME": hostname,
        "VEHICLE_IP": ip,
        "ROS_MASTER_URI": "http://%s:11311" % ip,
    }
    return env
