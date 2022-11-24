import argparse
import datetime
import logging
import os
from types import SimpleNamespace
from typing import Optional, List

from pydock import DockerClient

from utils.exceptions import ShellNeedsUpdate
from utils.misc_utils import sanitize_hostname

# NOTE: this is to avoid breaking the user workspace
try:
    import pydock
except ImportError:
    raise ShellNeedsUpdate("5.2.21")
# NOTE: this is to avoid breaking the user workspace

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.docker_utils import get_registry_to_use, sanitize_docker_baseurl, get_endpoint_architecture
from utils.dtproject_utils import DTProject

AGENT_SUBMISSION_REPOSITORY = "aido-submissions"


class DTCommand(DTCommandAbs):
    help = "Submits a project to a Duckietown challenge"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # Configure args
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the project to submit"
        )
        parser.add_argument(
            "-a",
            "--arch",
            default=None,
            help="Target architecture for the image to build",
        )
        parser.add_argument(
            "-u",
            "--username",
            default=os.getlogin(),
            help="The docker registry username to use",
        )
        parser.add_argument(
            "-H", "--machine", default=None, help="Docker socket or hostname where to build the image"
        )
        parser.add_argument(
            "--pull",
            default=False,
            action="store_true",
            help="Whether to pull the latest base image used by the Dockerfile",
        )
        parser.add_argument(
            "--recipe",
            default=None,
            help="Path to use if specifying a custom recipe",
        )
        parser.add_argument(
            "-L",
            "--launcher",
            default="submission",
            help="The launcher to use as entrypoint to the submission container",
        )
        parser.add_argument("-v", "--verbose", default=False, action="store_true", help="Be verbose")

        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed, remaining = parser.parse_known_args(args=args)
            if remaining:
                dtslogger.warning(f"I do not know about these arguments: {remaining}")
        else:
            # combine given args with default values
            default_parsed = parser.parse_args(args=[])
            for k, v in parsed.__dict__.items():
                setattr(default_parsed, k, v)
            parsed = default_parsed

        # variables
        registry_to_use = get_registry_to_use()
        debug = dtslogger.level <= logging.DEBUG

        # Show dtproject info
        parsed.workdir = os.path.abspath(parsed.workdir)
        dtslogger.info("Project workspace: {}".format(parsed.workdir))
        shell.include.devel.info.command(shell, args)
        project = DTProject(parsed.workdir)

        # sanitize hostname
        if parsed.machine is not None:
            parsed.machine = sanitize_hostname(parsed.machine)

        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f"Target architecture automatically set to {parsed.arch}.")

        # Build the project using 'code build' functionality
        build_namespace: SimpleNamespace = SimpleNamespace(
            workdir=parsed.workdir,
            username=parsed.username,
            pull=parsed.pull,
            recipe=parsed.recipe,
            launcher=parsed.launcher,
            verbose=parsed.verbose,
            quiet=True,
        )
        dtslogger.debug(f"Building with 'code/build' using args: {build_namespace}")
        success: bool = shell.include.code.build.command(shell, [], parsed=build_namespace)
        if not success:
            dtslogger.error("Failed to build the agent image for submission. Aborting.")
            exit(1)

        # create docker client
        host: Optional[str] = sanitize_docker_baseurl(parsed.machine)
        docker = DockerClient(host=host, debug=debug)

        # get built image
        src_name = project.image(arch=parsed.arch, owner=parsed.username, registry=registry_to_use)
        image: pydock.Image = docker.image.inspect(src_name)

        # tag the image for aido_submission
        repository: str = AGENT_SUBMISSION_REPOSITORY
        dtime: str = tag_from_date(datetime.datetime.now())
        agent_image_name: str = f"{registry_to_use}/{parsed.username}/{repository}"
        agent_image_full: str = f"{agent_image_name}:{dtime}"
        dtslogger.info(f"Tagging submission image as '{agent_image_full}'")
        image.tag(agent_image_full)

        # push image
        dtslogger.info(f"Pushing submission image '{agent_image_full}'...")
        docker.image.push(agent_image_full)
        image.reload()
        assert len(image.repo_digests) > 0
        dtslogger.info(f"Image pushed successfully!")

        # tag the image for aido_submission
        digest_sha = sha_from_digest(image, agent_image_name)
        submission_image_name = f"{agent_image_full}@{digest_sha}"
        dtslogger.debug(f"Submission image name is: {submission_image_name}")

        # submit
        submission_config_fpath = project.recipe.path if project.needs_recipe else project.path
        submission_yaml_fpath = os.path.join(submission_config_fpath, "submission.yaml")
        if not os.path.isfile(submission_yaml_fpath):
            dtslogger.error(f"File '{submission_yaml_fpath}' not found! Aborting.")
            exit(1)
        submit_args: List[str] = [
            "--workdir",
            submission_config_fpath,
            "submit",
            "--config",
            "./submission.yaml",
            "--image",
            submission_image_name,
        ]
        dtslogger.info("Submitting...")
        dtslogger.debug(f"Callind 'challenges/submit' using args: {submit_args}")
        shell.include.challenges.command(shell, submit_args)

    @staticmethod
    def complete(shell, word, line):
        return []


def tag_from_date(d: Optional[datetime.datetime] = None) -> str:
    if d is None:
        d = datetime.datetime.now()
    # YYYY-MM-DDTHH:MM:SS[.mmmmmm][+HH:MM].
    s = d.isoformat()
    s = s.replace(":", "_")
    s = s.replace("T", "_")
    s = s.replace("-", "_")
    s = s[: s.index(".")]
    return s


def sha_from_digest(image: pydock.Image, image_name: str) -> str:
    image.reload()
    digest: Optional[str] = None
    for d in image.repo_digests:
        if d.startswith(image_name):
            digest = d
    return digest[digest.index("@") + 1 :]
