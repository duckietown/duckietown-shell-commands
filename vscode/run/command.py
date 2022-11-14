import argparse
import glob
import json
import logging
import os
import signal
import time
import uuid
from typing import Optional

import requests

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.constants import DTShellConstants
from utils.exceptions import ShellNeedsUpdate

# NOTE: this is to avoid breaking the user workspace
try:
    import pydock
except ImportError:
    raise ShellNeedsUpdate("5.2.21")
# NOTE: this is to avoid breaking the user workspace

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
            "-p",
            "--port",
            default=0,
            type=int,
            help="Port to bind to. A random port will be assigned by default"
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
        else:
            # combine given args with default values
            default_parsed = parser.parse_args(args=["workdir"])
            for k, v in parsed.__dict__.items():
                setattr(default_parsed, k, v)
            parsed = default_parsed
        # ---

        # variables
        debug = dtslogger.level <= logging.DEBUG
        # - location for SSL certificate and key
        root: str = os.path.expanduser(DTShellConstants.ROOT)
        ssl_dir: str = os.path.join(root, "secrets", "mkcert", "ssl")

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

        # SSL keys are required
        if len(glob.glob(os.path.join(ssl_dir, "*.pem"))) != 2:
            dtslogger.error("An SSL key pair needs to be generated first. Run the following "
                            "command to create one:\n\n"
                            "\t$ dts setup mkcert\n\n")
            return

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
        workdir = f"/code/{workspace_name}"
        dtslogger.info(f"Running image '{image}'...")
        args = {
            "image": image,
            "detach": True,
            "remove": True,
            "volumes": [
                # needed by the container to figure out the GID of `docker` on the host
                ("/etc/group", "/host/etc/group", "ro"),
                # needed by VSCode to run in a safe context, nothing works in VSCode via HTTP
                (ssl_dir, "/ssl", "ro"),
                # this is the actual workspace
                (parsed.workdir, workdir, "rw"),
            ],
            "publish": [(f"127.0.0.1:{parsed.port}", VSCODE_PORT, "tcp")],
            "name": container_name,
            "workdir": workdir
        }
        dtslogger.debug(f"Calling docker.run with arguments:\n"
                        f"{json.dumps(args, indent=4, sort_keys=True)}\n")
        container = docker.run(**args)

        # register signal
        def _stop_container(*_):
            dtslogger.info("Stopping VSCode...")
            DTCommand.requested_stop = True
            container.kill()
            dtslogger.info("Done")

        signal.signal(signal.SIGINT, _stop_container)

        # find port exposed by the OS
        port: str = container.network_settings.ports[f"{VSCODE_PORT}/tcp"][0]["HostPort"]
        url: str = f"https://localhost:{port}"

        # wait for VSCode to get up
        max_wait: int = 20
        wait: int = 2
        found: bool = False
        dtslogger.info(f"Waiting for VSCode (up to {max_wait} seconds)...")
        for t in range(0, max_wait, wait):
            # noinspection PyBroadException
            try:
                requests.get(url)
            except Exception:
                time.sleep(wait)
                continue
            found = True
        if not found:
            dtslogger.error(f"VSCode failed to come up in {max_wait} seconds. Aborting...")
            # noinspection PyBroadException
            try:
                container.kill()
            except Exception:
                pass

        # print URL to VSCode
        dtslogger.info(
            "\nYou can open VSCode in your browser by visiting the URL:\n"
            "\n"
            f"\t> {url}\n"
            f"\n"
            f"VSCode might take a few seconds to be ready...\n"
            f"--------------------------------------------------------"
        )

        # attach
        if parsed.detach:
            dtslogger.info(f"VSCode will run in the background. "
                           f"The container name is {container_name}.")
        else:
            dtslogger.info("Use Ctrl-C in this terminal to stop VSCode.")

            # wait for the container to stop
            try:
                docker.wait(container)
            except pydock.exceptions.DockerException as e:
                if not DTCommand.requested_stop:
                    raise e

    @staticmethod
    def complete(shell, word, line):
        return []