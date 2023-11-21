import argparse
import os

from dt_shell import DTCommandAbs, DTShell, dtslogger

from dtproject import DTProject
from utils.docker_utils import (
    copy_docker_env_into_configuration,
    DEFAULT_MACHINE,
    get_client_OLD,
    get_endpoint_architecture,
    get_registry_to_use,
    login_client_OLD,
    push_image,
)
from cli.command import _run_cmd
from utils.dtproject_utils import _run_hooks

class DTCommand(DTCommandAbs):
    help = "Push the images relative to the current project"

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
            default=DEFAULT_MACHINE,
            help="Docker socket or hostname from where to push the image",
        )
        parser.add_argument(
            "--ci",
            default=False,
            action="store_true",
            help="Overwrites configuration for CI (Continuous Integration) push",
        )
        parser.add_argument(
            "-f",
            "--force",
            default=False,
            action="store_true",
            help="Whether to force the push when the git index is not clean",
        )
        parser.add_argument(
            "-u",
            "--username",
            default="duckietown",
            help="the docker registry username to tag the image with",
        )
        parser.add_argument(
            "--tag", default=None, help="Overrides 'version' (usually taken to be branch name)"
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

        # Execute pre-push hook
        _run_hooks('pre-push', project)

        registry_to_use = get_registry_to_use()

        # check if the index is clean
        if project.is_dirty():
            dtslogger.warning("Your index is not clean (some files are not committed).")
            dtslogger.warning(
                "If you know what you are doing, use --force to force the " "execution of the command."
            )
            if not parsed.force:
                exit(1)
            dtslogger.warning("Forced!")
        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f"Target architecture automatically set to {parsed.arch}.")
        # login (CI only)
        # spin up docker client
        docker = get_client_OLD(parsed.machine)

        copy_docker_env_into_configuration(shell.shell_config)
        login_client_OLD(docker, shell.shell_config, registry_to_use, raise_on_error=True)

        # tag
        version: str = project.distro
        if parsed.tag:
            dtslogger.info(f"Overriding version {version!r} with {parsed.tag!r}")
            version = parsed.tag

        # compile image name
        image: str = project.image(
            arch=parsed.arch, registry=registry_to_use, owner=parsed.username, version=version
        )

        dtslogger.info(f"Pushing image {image}...")
        if push_image(image, docker) is None:
            dtslogger.error("Pushing image failed!")
            # Execute post-push-failed hook
            _run_hooks('post-push-failed', project)
            exit(1)
        dtslogger.info("Image successfully pushed!")
        # push release version
        if project.is_release():
            image = project.image_release(
                arch=parsed.arch,
                owner=parsed.username,
                registry=registry_to_use,
            )
            dtslogger.info(f"Pushing release image {image}...")
            push_image(image, docker)
            dtslogger.info("Image successfully pushed!")
        # Execute post-push hook
        _run_hooks('post-push', project)

    @staticmethod
    def complete(shell, word, line):
        return []
