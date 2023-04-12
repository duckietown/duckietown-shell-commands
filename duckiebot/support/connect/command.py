import argparse
import logging
import os
from tempfile import TemporaryDirectory
from typing import List, Tuple

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.cli_utils import start_command_in_subprocess

# NOTE: this is to avoid breaking the user workspace
try:
    import dockertown
except ImportError:
    raise ShellNeedsUpdate("5.4.0+")
# NOTE: this is to avoid breaking the user workspace


BASE_IMAGE = "cloudflare/cloudflared"
VERSION = "latest"


usage = """

## Basic usage
    This command enables secure remote technical support for Duckiebots.

"""


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # Configure args
        prog = "dts duckiebot support connect"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument(
            "dns",
            nargs=1,
            help="DNS to connect to an open tunnel")

        parser.add_argument(
            "--pull",
            action="store_true",
            default=False,
            help="Update the support image"
        )

        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed, _ = parser.parse_known_args(args=args)
        parsed.dns = parsed.dns[0]

        volumes: List[Tuple[str, str, str]] = []
        with TemporaryDirectory() as tmpdir:
            # TODO: Get the required key

            # Configure docker
            debug = dtslogger.level <= logging.DEBUG
            docker_client = dockertown.DockerClient(debug=debug)

            tunneling_image = f"{BASE_IMAGE}:{VERSION}"
            robot_id = parsed.dns.split('-')[0]
            container_name: str = f"{robot_id}-support"
            args = {
                "image": tunneling_image,
                "auto_remove": True,
                "volumes": volumes,
                "name": container_name,
                "stream": True,
                "command": None  # TODO
            }

            dtslogger.info(f"Opening a connection to {parsed.dns} ...")
            docker_client.run(**args)

            # Attach to the support container with an interactive session
            attach_cmd = "docker attach %s" % container_name
            try:
                start_command_in_subprocess(attach_cmd)
            except Exception as e:
                if not parsed.no_scream:
                    raise e
                else:
                    dtslogger.error(str(e))
            # ---
            dtslogger.info("Exited the tunnel connection.")
