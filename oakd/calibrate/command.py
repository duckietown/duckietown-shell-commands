import argparse

from past.builtins import raw_input

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.docker_utils import (
    bind_duckiebot_data_dir,
    default_env,
    check_docker_environment,
    remove_if_running,
    pull_if_not_exist,
    check_if_running,
    get_endpoint_architecture,
)
from utils.duckietown_utils import get_distro_version
from utils.misc_utils import sanitize_hostname
from utils.networking_utils import get_duckiebot_ip

import os
import subprocess

CALIBRATE_IMAGE = "duckvision/oakd-calibration:daffy-amd64"


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):

        prog = "dts oakd calibrate"
        usage = """
Calibrate:

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        # ---

        local_client = check_docker_environment()

        calibration_container_name = "oakd_calibration"
        remove_if_running(local_client, calibration_container_name)

        image = CALIBRATE_IMAGE

        raw_input(
            f"{'*' * 20}\nConnect the OAK-D to your computer and press ENTER.")
        dtslogger.info(
            "\tThis is a wrapper around the luxonis camera calibration libraries.")
        dtslogger.info(
            "\tFollow the instructions, refer to the tutorial on https://docs.luxonis.com/en/latest/pages/calibration")

        pull_if_not_exist(local_client, image)

        volumes = {}
        volumes["/run/udev"] = {"bind": "/run/udev", "mode": "ro"}
        volumes["/dev/bus/usb"] = {"bind": "/dev/bus/usb", "mode": "ro"}
        volumes[f"/data/config"] = {"bind": "/data/config", "mode": "rw"}
        volumes[f"/tmp/.X11-unix"] = {"bind": "/tmp/.X11-unix", "mode": "rw"}

        subprocess.call(["xhost", "+"])

        env = {
            "DISPLAY": os.environ["DISPLAY"]
        }
        local_client.containers.run(
            image=image,
            name=calibration_container_name,
            privileged=True,
            stream=True,
            detach=False,
            tty=True,
            network_mode="host",
            volumes=volumes,
            command="dt-launcher-default",
            environment=env,
            remove=True,
        )
        dtslogger.info("Done!")
