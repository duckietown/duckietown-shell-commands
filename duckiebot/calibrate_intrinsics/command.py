import argparse
import os
import platform
import socket
import subprocess

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import get_remote_client, remove_if_running, pull_if_not_exist
from utils.networking_utils import get_duckiebot_ip


ARCH='amd64'
BRANCH='daffy'
DEFAULT_IMAGE = 'duckietown/dt-gui-tools:'+BRANCH+'-'+ARCH


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):

        prog = "dts duckiebot calibrate_intrinsics DUCKIEBOT_NAME"
        usage = """
Calibrate:

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument(
            "hostname", default=None, help="Name of the Duckiebot to calibrate"
        )
        parser.add_argument(
            "--base_image",
            dest="image",
            default=DEFAULT_IMAGE,
        )
        parser.add_argument(
            "--debug",
            action="store_true",
            default=False,
            help="will enter you into the running container",
        )

        parsed_args = parser.parse_args(args)
        hostname = parsed_args.hostname
        duckiebot_ip = get_duckiebot_ip(hostname)
        duckiebot_client = get_remote_client(duckiebot_ip)

        # is the interface running?
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
                exit()
        except Exception as e:
            dtslogger.warn(
                "Not sure if the duckiebot-interface is running because we got and exception when trying: %s"
                % e
            )

        # is the raw imagery being published?
        try:
            duckiebot_containers = duckiebot_client.containers.list()
            raw_imagery_found = False
            for c in duckiebot_containers:
                if "demo_intrinsic_calibration" in c.name:
                    raw_imagery_found = True
            if not raw_imagery_found:
                dtslogger.warn(
                    "The demo_intrinsic_calibration is not running on the duckiebot running `dts duckiebot demo "
                    "--demo_name image_decoding --package_name image_processing --duckiebot_name %s`" % hostname
                )
                start_command_in_subprocess(" dts duckiebot demo 
                --demo_name intrinsic_calibration --package_name image_processing --duckiebot_name %s`" % hostname

        except Exception as e:
            dtslogger.warn("%s" % e)

        image = parsed_args.image

        client = check_docker_environment()
        container_name = "intrinsic_calibration_%s" % hostname
        remove_if_running(client, container_name)
        env = {
            "HOSTNAME": hostname,
            "ROS_MASTER": hostname,
            "DUCKIEBOT_NAME": hostname,
            "ROS_MASTER_URI": "http://%s:11311" % duckiebot_ip,
            "QT_X11_NO_MITSHM": 1,
        }

        volumes = {}
        subprocess.call(["xhost", "+"])

        p = platform.system().lower()
        if "darwin" in p:
            env["DISPLAY"] = "%s:0" % socket.gethostbyname(socket.gethostname())
            volumes = {"/tmp/.X11-unix": {"bind": "/tmp/.X11-unix", "mode": "rw"}}
        else:
            env["DISPLAY"] = os.environ["DISPLAY"]

        dtslogger.info(
            "Running %s on localhost with environment vars: %s" % (container_name, env)
        )

        dtslogger.info(
            "When the window opens you will need to move the checkerboard around in front of the Duckiebot camera"
        )
        cmd = "roslaunch intrinsic_calibration intrinsic_calibration.launch veh:=%s" % hostname

        params = {
            "image": image,
            "name": container_name,
            "network_mode": "host",
            "environment": env,
            "privileged": True,
            "stdin_open": True,
            "tty": True,
            "detach": True,
            "command": cmd,
            "volumes": volumes,
        }

        pull_if_not_exist(client, image)

        container = client.containers.run(**params)

        if parsed_args.debug:
            attach_cmd = "docker attach %s" % (container_name)
            start_command_in_subprocess(attach_cmd)
