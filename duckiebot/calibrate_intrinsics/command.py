import argparse
import os
import platform
import socket
import subprocess

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import remove_if_running, pull_if_not_exist, pull_image
from utils.networking_utils import get_duckiebot_ip


ARCH = "amd64"
VERSION = "v4.1.1"
DEFAULT_IMAGE = f"duckietown/dt-gui-tools:{VERSION}-{ARCH}"


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
            "--base_image",
            dest="image",
            default=DEFAULT_IMAGE,
        )
        parser.add_argument(
            "--debug",
            action="store_true",
            default=False,
            help="Will enter you into the running container",
        )
        parser.add_argument(
            "--no-pull",
            action="store_true",
            default=False,
            help="Do not pull calibration code image",
        )
        parser.add_argument(
            "--keep",
            action="store_true",
            default=False,
            help="Do not remove the calibration image once done. Useful for debugging",
        )

        parsed = parser.parse_args(args)

        client = check_docker_environment()
        container_name = "dts-calibrate-intrinsics-%s" % parsed.hostname
        remove_if_running(client, container_name)
        env = {
            "VEHICLE_NAME": parsed.hostname,
            "QT_X11_NO_MITSHM": 1,
        }

        subprocess.call(["xhost", "+"])

        if "darwin" in platform.system().lower():
            duckiebot_ip = get_duckiebot_ip(parsed.hostname)
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

        params = {
            "image": parsed.image,
            "name": container_name,
            "network_mode": "host",
            "environment": env,
            "privileged": True,
            "stdin_open": True,
            "tty": True,
            "detach": True,
            "remove": not parsed.keep,
            "command": "dt-launcher-intrinsic-calibration",
            "volumes": volumes,
        }

        if not parsed.no_pull:
            dtslogger.info("Pulling image %s ..." % parsed.image)
            pull_image(parsed.image, client)
        else:
            pull_if_not_exist(client, parsed.image)

        dtslogger.info("Running %s on localhost with environment vars: %s" % (container_name, env))

        dtslogger.info(
            "When the window opens you will be able to perform the calibration.\n "
            "Follow the instructions on the official book at https://docs.duckietown.com/daffy/"
            "opmanual-duckiebot/operations/calibration_camera/index.html#intrinsic-calibration.\n "
            "Press [Q] to close the window."
        )

        client.containers.run(**params)

        if parsed.debug:
            attach_cmd = "docker attach %s" % container_name
            start_command_in_subprocess(attach_cmd)
