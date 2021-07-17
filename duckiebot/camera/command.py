import argparse
import os
import platform
import socket
import subprocess

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.networking_utils import get_duckiebot_ip
from utils.docker_utils import (
    bind_duckiebot_data_dir,
    default_env,
    get_remote_client,
    remove_if_running,
    pull_if_not_exist,
    check_if_running,
    get_endpoint_architecture,
)
from utils.duckietown_utils import get_distro_version
from utils.misc_utils import sanitize_hostname

DT_INTERFACE_IMAGE = "duckietown/dt-duckiebot-interface:daffy-{arch}"


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):

        prog = "dts duckiebot camera DUCKIEBOT_NAME --stop/--start"
        usage = """
This command can prevent the camera node to start in the dt-duckiebot-interface. 

Setup:

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument("hostname", default=None,
                            help="Name of the Duckiebot")

        parser.add_argument(
            "--stop", dest="stop", default=None, action="store_true", help="Stop the camera node"
        )

        parser.add_argument(
            "--start", dest="start", default=None, action="store_true", help="Start the camera node"
        )

        parsed = parser.parse_args(args)

        if parsed.stop and parsed.start:
            raise Exception(
                "You must choose between starting or stopping the camera.")
        if not (parsed.stop or parsed.start):
            raise Exception(
                "You must choose between starting (--start) or stopping (--stop) the camera.")

        duckiebot_ip = get_duckiebot_ip(parsed.hostname)
        hostname = sanitize_hostname(parsed.hostname)
        duckiebot_client = get_remote_client(duckiebot_ip)

        interface_container = "duckiebot-interface"
        remove_if_running(duckiebot_client, interface_container)

        arch = get_endpoint_architecture(hostname)
        image = DT_INTERFACE_IMAGE.format(arch=arch)
        dtslogger.info(f"Target architecture automatically set to {arch}.")

        env = default_env(parsed.hostname, duckiebot_ip)

        if parsed.stop:
            env['DISABLE_CAMERA'] = 'on'

        pull_if_not_exist(duckiebot_client, image)

        duckiebot_client.containers.run(
            image=image,
            name=interface_container,
            privileged=True,
            network_mode="host",
            volumes={"/data": {"bind": "/data"},
                     "/var/run/avahi-daemon/socket": {"bind": "/var/run/avahi-daemon/socket"},
                     "/tmp/argus_socket": {"bind": "/tmp/argus_socket"}},
            environment=env,
            remove=False,
            restart_policy={"Name": "always"},
            detach=True
        )
        dtslogger.info("Done!")
