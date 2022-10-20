import argparse
import json
import logging
import os
import signal
import time
import uuid
from typing import Optional

import pydock
from dt_shell import DTCommandAbs, DTShell, dtslogger

from pydock import DockerClient
from utils.buildx_utils import DOCKER_INFO
from utils.docker_utils import (
    DEFAULT_REGISTRY,
    get_endpoint_architecture,
    sanitize_docker_baseurl
)
from utils.duckietown_utils import get_distro_version
from utils.misc_utils import human_size, sanitize_hostname

VSCODE_PORT = 8088


class DTCommand(DTCommandAbs):
    help = "Builds the current project"

    requested_stop: bool = False

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-H",
            "--machine",
            default=None,
            help="Docker socket or hostname where to run the image"
        )
        parser.add_argument(
            "-d", "--detach",
            default=False,
            action="store_true",
            help="Detach from container and let it run in the background",
        )
        parser.add_argument(
            "--pull",
            default=False,
            action="store_true",
            help="Whether to pull the latest version of the VSCode image available",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            default=False,
            action="store_true",
            help="Be verbose"
        )
        parser.add_argument(
            "-a",
            "--arch",
            default=None,
            help="Target architecture(s) for the image to run",
        )
        parser.add_argument(
            "--tag",
            default=None,
            help="Overrides 'tag' of the VSCode image to run (by default the shell distro is used)"
        )
        parser.add_argument(
            "--image",
            default=None,
            help="VSCode image to run"
        )
        parser.add_argument(
            "workdir",
            default=os.getcwd(),
            help="Directory containing the workspace to open",
            nargs=1
        )

        # get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed, remaining = parser.parse_known_args(args=args)
            if remaining:
                dtslogger.info(f"I do not know about these arguments: {remaining}")
        # ---

        # variables
        debug = dtslogger.level <= logging.DEBUG

        # conflicting arguments
        if parsed.image and parsed.arch:
            msg = "Forbidden: You cannot use --image and --arch at the same time."
            dtslogger.warn(msg)
            exit(1)
        if parsed.image and parsed.tag:
            msg = "Forbidden: You cannot use --image and --tag at the same time."
            dtslogger.warn(msg)
            exit(2)

        # sanitize workdir
        parsed.workdir = parsed.workdir[0]
        if os.path.isfile(parsed.workdir):
            dtslogger.warning("You pointed VSCode to a file, opening its parent directory instead")
            parsed.workdir = os.path.dirname(parsed.workdir)
        parsed.workdir = os.path.abspath(parsed.workdir)

        # sanitize hostname
        if parsed.machine is not None:
            parsed.machine = sanitize_hostname(parsed.machine)

        # create docker client
        host: Optional[str] = sanitize_docker_baseurl(parsed.machine)
        docker = DockerClient(host=host, debug=debug)

        # get info about docker endpoint
        dtslogger.info("Retrieving info about Docker endpoint...")
        epoint = docker.info().dict()
        epoint["mem_total"] = human_size(epoint["mem_total"])
        print(DOCKER_INFO.format(**epoint))

        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f"Target architecture automatically set to {parsed.arch}.")

        # create defaults
        version = parsed.tag or get_distro_version(shell)
        image = parsed.image or f"{DEFAULT_REGISTRY}/duckietown/dt-vscode:{version}-{parsed.arch}"

        # pull image (if needed)
        if parsed.pull:
            dtslogger.info(f"Pulling image '{image}'...")
            docker.image.pull(image, quiet=False)

        # launch container
        workspace_name: str = os.path.basename(parsed.workdir)
        container_id: str = str(uuid.uuid4())[:4]
        container_name: str = f"vscode-{workspace_name}-{container_id}"
        workdir = f"/code/user_ws/{workspace_name}"
        dtslogger.info(f"Running image '{image}'...")
        args = {
            "image": image,
            "detach": True,
            "volumes": [
                ("/etc/group", "/host/etc/group", "ro"),
                (parsed.workdir, workdir, "rw"),
            ],
            "name": container_name,
            "workdir": workdir
        }
        dtslogger.debug(f"Calling docker.run with arguments:\n"
                        f"{json.dumps(args, indent=4, sort_keys=True)}\n")
        container = docker.run(**args)

        # print URL to VSCode
        container_ip: str = container.network_settings.ip_address
        dtslogger.info("\nYou can open VSCode in your browser by visiting the URL:\n"
                       "\n"
                       f"\t> http://{container_ip}:{VSCODE_PORT}\n"
                       f"\n"
                       f"--------------------------------------------------------")

        # attach
        if parsed.detach:
            dtslogger.info(f"VSCode will run in the background. "
                           f"The container name is {container_name}.")
        else:
            dtslogger.info("Use Ctrl-C in this terminal to stop VSCode.")

            # register signal
            def _stop_container(*_):
                dtslogger.info("Stopping VSCode...")
                DTCommand.requested_stop = True
                container.kill()
                dtslogger.info("Done")

            signal.signal(signal.SIGINT, _stop_container)

            # wait for the container to stop
            try:
                docker.wait(container)
            except pydock.exceptions.DockerException as e:
                if not DTCommand.requested_stop:
                    raise e


    @staticmethod
    def complete(shell, word, line):
        return []
