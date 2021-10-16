import argparse
import os

from dt_shell import DTCommandAbs, dtslogger
from duckietown_docker_utils import ENV_REGISTRY

from utils.docker_utils import (
    DEFAULT_REGISTRY,
    get_endpoint_architecture,
    get_client,
    pull_image,
    STAGING_REGISTRY,
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
        parser.add_argument(
            "--stage",
            "--staging",
            dest="staging",
            action="store_true",
            default=False,
            help="Use staging environment",
        )
        parser.add_argument(
            "--registry",
            type=str,
            default=DEFAULT_REGISTRY,
            help="Use this Docker registry",
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

        # staging
        if parsed.staging:
            parsed.registry = STAGING_REGISTRY
        else:
            # custom Docker registry
            docker_registry = os.environ.get(ENV_REGISTRY, DEFAULT_REGISTRY)
            if docker_registry != DEFAULT_REGISTRY:
                dtslogger.warning(f"Using custom {ENV_REGISTRY}='{docker_registry}'.")
                parsed.registry = docker_registry

        # registry
        if parsed.registry != DEFAULT_REGISTRY:
            dtslogger.info(f"Using custom registry: {parsed.registry}")

        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f"Target architecture automatically set to {parsed.arch}.")

        # spin up docker client
        docker = get_client(parsed.machine)

        # create defaults
        image = project.image(parsed.arch, registry=parsed.registry, staging=parsed.staging)

        # custom Docker registry
        # TODO: add parsed.registry here
        docker_registry = os.environ.get(ENV_REGISTRY, DEFAULT_REGISTRY)

        image = f"{docker_registry}/{image}"
        dtslogger.info(f"Pulling image {image}...")
        pull_image(image, docker)
        dtslogger.info("Image successfully pulled!")

    @staticmethod
    def complete(shell, word, line):
        return []
