import argparse
import logging
import os
from tempfile import TemporaryDirectory
from types import SimpleNamespace
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

DCSS_RSA_SECRET_LOCATION = "secrets/rsa/cloudflared/duckietown.io/cert.pem"
DCSS_RSA_SECRET_SPACE = "private"
SSH_USERNAME = "duckie"
CONTAINER_RSA_KEY_LOCATION = "/ssh/cert.pem"


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

        SSH_HOSTNAME = parsed.dns
        volumes: List[Tuple[str, str, str]] = []

        with TemporaryDirectory() as tmpdir:
            # Download RSA key and mount to container
            dtslogger.info(f"Downloading RSA key for tunnel '{SSH_HOSTNAME}'...")
            local_rsa = os.path.join(tmpdir, "id_rsa")
            shell.include.data.get.command(
                shell,
                [],
                parsed=SimpleNamespace(
                    file=[local_rsa],
                    object=[DCSS_RSA_SECRET_LOCATION.format(dns=SSH_HOSTNAME)],
                    space=DCSS_RSA_SECRET_SPACE,
                    token=os.environ.get("DUCKIETOWN_CI_DT_TOKEN", None)
                ),
            )
            os.chmod(local_rsa, 0o600)
            volumes.append((local_rsa, CONTAINER_RSA_KEY_LOCATION, "ro"))

            # Configure docker
            debug = dtslogger.level <= logging.DEBUG
            docker_client = dockertown.DockerClient(debug=debug)

            tunneling_image = f"{BASE_IMAGE}:{VERSION}"
            robot_id = parsed.dns.split('-')[0]
            container_name: str = f"device-support-{robot_id}"

            cmd: str = (f'ssh -o "ProxyCommand=cloudflared access ssh --hostname %h" \
                                    -o "StrictHostKeyChecking=no" \
                                    -o "UserKnownHostsFile=/dev/null" \
                                    ${SSH_USERNAME}@${SSH_HOSTNAME}')

            args = {
                "image": tunneling_image,
                "remove": True,
                "volumes": volumes,
                "name": container_name,
                "command": cmd
            }

            dtslogger.info(f"Opening a connection to {SSH_HOSTNAME} ...")
            logs = docker_client.run(**args)
            with open("logs.txt", "wb") as binary_file:
                binary_file.write(logs)

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
