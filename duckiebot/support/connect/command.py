import argparse
import logging
import os
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import List, Tuple

from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError
from dt_shell.utils import run_cmd
from utils.cli_utils import start_command_in_subprocess

# NOTE: this is to avoid breaking the user workspace
try:
    import dockertown
except ImportError:
    raise ShellNeedsUpdate("5.4.0+")
# NOTE: this is to avoid breaking the user workspace


BASE_IMAGE = "linuxserver/openssh-server"
VERSION = "latest"
SSH_USERNAME = "duckie"


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

        dtslogger.info(f"Opening a connection to {SSH_HOSTNAME} ...")
        support_cmd: str = f'ssh -o "ProxyCommand=cloudflared access ssh --hostname %h" \
                                -o "StrictHostKeyChecking=no" \
                                -o "UserKnownHostsFile=/dev/null" \
                                {SSH_USERNAME}@{SSH_HOSTNAME}'

        # SSH into the support tunnel with an interactive session
        try:
            start_command_in_subprocess(support_cmd)
        except Exception as e:
            dtslogger.error(str(e))
        # ---
        dtslogger.info("Exited the tunnel connection.")
