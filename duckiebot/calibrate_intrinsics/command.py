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


ARCH = "amd64"
BRANCH = "daffy"
DEFAULT_IMAGE = "duckietown/dt-gui-tools:" + BRANCH + "-" + ARCH


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):

        prog = "dts duckiebot calibrate_intrinsics DUCKIEBOT_NAME"
        usage = """
Calibrate:

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument("hostname", default=None, help="Name of the Duckiebot to calibrate")
        parser.add_argument(
            "--base_image", dest="image", default=DEFAULT_IMAGE,
        )
        parser.add_argument(
            "--debug", action="store_true", default=False, help="Will enter you into the running container",
        )

        parsed = parser.parse_args(args)
        duckiebot_ip = get_duckiebot_ip(parsed.hostname)
        duckiebot_client = get_remote_client(duckiebot_ip)

        # is the interface running?
        try:
            duckiebot_containers = duckiebot_client.containers.list()
            interface_container_found = False
            for c in duckiebot_containers:
                if "duckiebot-interface" in c.name:
                    interface_container_found = True
            if not interface_container_found:
                dtslogger.error("The  duckiebot-interface is not running on the Duckiebot")
                exit()
        except Exception as e:
            dtslogger.warn(
                "We could not verify that the duckiebot-interface module is running. "
                "The exception reads: %s" % e
            )

        client = check_docker_environment()
        container_name = "dts-calibrate-intrinsics-%s" % parsed.hostname
        remove_if_running(client, container_name)
        env = {
            "VEHICLE_NAME": parsed.hostname,
            "QT_X11_NO_MITSHM": 1,
        }

        subprocess.call(["xhost", "+"])

        if "darwin" in platform.system().lower():
            env.update(
                {
                    "DISPLAY": "%s:0" % socket.gethostbyname(socket.gethostname()),
                    "ROS_MASTER": parsed.hostname,
                    "ROS_MASTER_URI": "http://%s:11311" % duckiebot_ip,
                }
            )
            volumes = {"/tmp/.X11-unix": {"bind": "/tmp/.X11-unix", "mode": "rw"}}
        else:
            env["DISPLAY"] = os.environ["DISPLAY"]
            volumes = {"/var/run/avahi-daemon/socket": {"bind": "/var/run/avahi-daemon/socket", "mode": "rw"}}

        dtslogger.info("Running %s on localhost with environment vars: %s" % (container_name, env))

        dtslogger.info(
            "When the window opens you will need to move the checkerboard around "
            "in front of the Duckiebot camera.\nPress [Q] to close the window."
        )

        params = {
            "image": parsed.image,
            "name": container_name,
            "network_mode": "host",
            "environment": env,
            "privileged": True,
            "stdin_open": True,
            "tty": True,
            "detach": True,
            "remove": True,
            "auto_remove": True,
            "command": "dt-launcher-intrinsic-calibration",
            "volumes": volumes,
        }

        pull_if_not_exist(client, parsed.image)

        client.containers.run(**params)

        if parsed.debug:
            attach_cmd = "docker attach %s" % container_name
            start_command_in_subprocess(attach_cmd)
