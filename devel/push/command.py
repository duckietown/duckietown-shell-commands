import argparse
import os

from dt_shell import DTCommandAbs, dtslogger

from utils.docker_utils import DEFAULT_MACHINE, get_endpoint_architecture, get_client, push_image
from utils.dtproject_utils import DTProject

from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    help = "Push the images relative to the current project"

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the project to push",
        )
        parser.add_argument(
            "-a", "--arch", default=None, help="Target architecture for the image to push",
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
        # CI builds
        if parsed.ci:
            # check that the env variables are set
            for key in ["DOCKERHUB_USER", "DOCKERHUB_TOKEN"]:
                if "DUCKIETOWN_CI_" + key not in os.environ:
                    dtslogger.error(
                        "Variable DUCKIETOWN_CI_{:s} required when building with --ci".format(key)
                    )
                    exit(2)
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
        push_args = {}
        if parsed.ci:
            push_args["auth_config"] = {
                "username": os.environ["DUCKIETOWN_CI_DOCKERHUB_USER"],
                "password": os.environ["DUCKIETOWN_CI_DOCKERHUB_TOKEN"],
            }
        # spin up docker client
        docker = get_client(parsed.machine)
        # create defaults
        image = project.image(parsed.arch, owner=parsed.username)
        dtslogger.info(f"Pushing image {image}...")
        push_image(image, docker, progress=not parsed.ci, **push_args)
        dtslogger.info("Image successfully pushed!")
        # push release version
        if project.is_release():
            image = project.image_release(parsed.arch, owner=parsed.username)
            dtslogger.info(f"Pushing image {image}...")
            push_image(image, docker, progress=not parsed.ci, **push_args)
            dtslogger.info("Image successfully pushed!")

    @staticmethod
    def complete(shell, word, line):
        return []
