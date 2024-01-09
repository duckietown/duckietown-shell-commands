import argparse
import os

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.profile import DockerCredentials
from utils.docker_utils import (
    get_client_OLD,
    get_endpoint_architecture,
    get_registry_to_use,
    login_client_OLD,
    pull_image_OLD,
)
from dtproject import DTProject
from utils.duckietown_utils import DEFAULT_OWNER


class DTCommand(DTCommandAbs):
    help = "Pulls the images relative to the current project"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parser: argparse.ArgumentParser = DTCommand.parser
        parsed, _ = parser.parse_known_args(args=args)
        if "parsed" in kwargs:
            parsed.__dict__.update(kwargs["parsed"].__dict__)
        # ---
        parsed.workdir = os.path.abspath(parsed.workdir)
        dtslogger.info("Project workspace: {}".format(parsed.workdir))

        # show info about project
        shell.include.devel.info.command(shell, [], parsed=parsed)
        project = DTProject(parsed.workdir)

        registry_to_use = get_registry_to_use()

        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f"Target architecture automatically set to {parsed.arch}.")

        # tag
        version = project.distro
        if parsed.tag:
            dtslogger.info(f"Overriding version {version!r} with {parsed.tag!r}")
            version = parsed.tag

        # spin up docker client
        docker = get_client_OLD(parsed.machine)
        credentials: DockerCredentials = shell.profile.secrets.docker_credentials
        login_client_OLD(docker, credentials, registry_to_use, raise_on_error=False)

        # create defaults
        image = project.image(
            arch=parsed.arch, registry=registry_to_use, owner=DEFAULT_OWNER, version=version
        )

        dtslogger.info(f"Pulling image {image}...")
        pull_image_OLD(image, docker)
        dtslogger.info("Image successfully pulled!")

    @staticmethod
    def complete(shell, word, line):
        return []
