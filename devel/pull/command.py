import argparse
import os

from dt_shell import DTCommandAbs, dtslogger

from utils.docker_utils import (
    DEFAULT_REGISTRY,
    get_endpoint_architecture,
    get_client,
    pull_image,
)
from utils.dtproject_utils import DTProject

from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    help = "Pulls the images relative to the current project"

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory containing the project to push",
        )
        parser.add_argument(
            "-a",
            "--arch",
            default=None,
            help="Target architecture for the image to push",
        )
        parser.add_argument(
            "-H",
            "--machine",
            default=None,
            help="Docker socket or hostname from where to push the image",
        )
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._parse_args(args)
        if "parsed" in kwargs:
            parsed.__dict__.update(kwargs["parsed"].__dict__)
        # ---
        parsed.workdir = os.path.abspath(parsed.workdir)
        dtslogger.info("Project workspace: {}".format(parsed.workdir))
        # show info about project
        shell.include.devel.info.command(shell, [], parsed=parsed)
        project = DTProject(parsed.workdir)
        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f"Target architecture automatically set to {parsed.arch}.")
        # spin up docker client
        docker = get_client(parsed.machine)
        # create defaults
        image = project.image(parsed.arch)

        # custom Docker registry
        docker_registry = os.environ.get("DOCKER_REGISTRY", DEFAULT_REGISTRY)

        image = f"{docker_registry}/{image}"
        dtslogger.info(f"Pulling image {image}...")
        pull_image(image, docker)
        dtslogger.info("Image successfully pulled!")

    @staticmethod
    def complete(shell, word, line):
        return []
