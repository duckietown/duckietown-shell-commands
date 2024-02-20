import argparse
import logging
import os
from types import SimpleNamespace
from typing import Optional, List

from dt_shell.config import read_shell_config, ShellConfig

from utils.challenges_utils import get_registry_from_challenges_server, get_challenges_server_to_use
from utils.exceptions import ShellNeedsUpdate
from utils.misc_utils import sanitize_hostname
from utils.yaml_utils import load_yaml

# NOTE: this is to avoid breaking the user workspace
try:
    import dockertown
except ImportError:
    raise ShellNeedsUpdate("5.4.0+")
# NOTE: this is to avoid breaking the user workspace

from dockertown import DockerClient
from dt_shell import DTCommandAbs, dtslogger, DTShell, UserError
from utils.docker_utils import sanitize_docker_baseurl, get_endpoint_architecture, get_registry_to_use
from utils.dtproject_utils import DTProject

AGENT_SUBMISSION_REPOSITORY = "aido-submissions"


class DTCommand(DTCommandAbs):
    help = "Evaluates a project against a Duckietown challenge"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # Configure args
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the project to submit"
        )
        parser.add_argument(
            "-H", "--machine", default=None, help="Docker socket or hostname where to build the image"
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
            default=None,
            help="The docker registry username to use",
        )
        parser.add_argument(
            "--recipe",
            default=None,
            help="Path to use if specifying a custom local recipe path",
        )
        parser.add_argument(
            "--recipe-version",
            default=None,
            help="Branch to use if specifying a test branch of the recipes repository",
        )
        parser.add_argument(
            "--no-pull",
            default=False,
            action="store_true",
            help="Skip pulling the base image from the registry (useful when you have a local BASE image)",
        )
        parser.add_argument("--no-cache", default=False, action="store_true", help="Ignore the Docker cache")
        parser.add_argument(
            "--impersonate",
            default=None,
            type=str,
            help="Duckietown UID of the user to impersonate",
        )
        parser.add_argument("-c", "--challenge", type=str, default=None, help="Challenge to evaluate against")
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
            parsed = parser.parse_args(args=args)
        else:
            # combine given args with default values
            default_parsed = parser.parse_args(args=[])
            for k, v in parsed.__dict__.items():
                setattr(default_parsed, k, v)
            parsed = default_parsed

        # variables
        registry_to_use: str = get_registry_to_use()
        server_to_use: str = get_challenges_server_to_use()
        registry_to_push: str = get_registry_from_challenges_server(server_to_use)
        debug = dtslogger.level <= logging.DEBUG

        # show dtproject info
        parsed.workdir = os.path.abspath(parsed.workdir)
        dtslogger.info("Project workspace: {}".format(parsed.workdir))
        shell.include.devel.info.command(shell, args)
        project = DTProject(parsed.workdir)

        # make sure the project recipe is present
        if parsed.recipe is not None:
            if project.needs_recipe:
                recipe_dir: str = os.path.abspath(parsed.recipe)
                dtslogger.info(f"Using custom recipe from '{recipe_dir}'")
                project.set_recipe_dir(recipe_dir)
            else:
                raise UserError("This project does not support recipes")
        else:
            if parsed.recipe_version:
                project.set_recipe_version(parsed.recipe_version)
                dtslogger.info(f"Using recipe version on branch '{parsed.recipe_version}'")
            project.ensure_recipe_exists()
            project.ensure_recipe_updated()

        # get challenge to evaluate against
        submission_yaml = os.path.join(project.path, "submission.yaml")
        if not os.path.isfile(submission_yaml):
            if not project.needs_recipe:
                dtslogger.error(f"File '{submission_yaml}' not found.")
                exit(1)
            # look for submission.yaml inside the recipe
            submission_yaml = os.path.join(project.recipe.path, "submission.yaml")
            if not os.path.isfile(submission_yaml):
                dtslogger.error(
                    f"File 'submission.yaml' not found. We searched both this project " f"and its recipe."
                )
                exit(1)
        submission: dict = load_yaml(submission_yaml)
        challenges: List[str] = submission.get("challenge", [])

        # make sure there is at least one challenge we can evaluate against
        if not challenges:
            dtslogger.error(f"The list of challenges in '{submission_yaml}' is empty.")
            exit(1)

        # we must know which challenge to evaluate against
        if parsed.challenge is not None:
            # make sure the chosen challenge is in the list of supported challenges
            if parsed.challenge not in challenges:
                dtslogger.error(
                    f"Challenge '{parsed.challenge}' not supported by this submission. "
                    f"Supported challenges are: \n\n\t" + "\n\t".join(challenges) + "\n"
                )
                exit(1)
            dtslogger.info(f"User chose to evaluate against challenge '{parsed.challenge}'...")
        else:
            # complain if an explicit choice is needed
            if len(challenges) > 1:
                dtslogger.error(
                    "This submission is supported by the following challenges, indicate "
                    "which one to evaluate against with '--challenge <CHALLENGE_NAME>':"
                    + "\n\n\t"
                    + "\n\t".join(challenges)
                    + "\n"
                )
                exit(1)
            # auto-pick if only one is available
            parsed.challenge = challenges[0]
        dtslogger.info(f"Evaluating against challenge '{parsed.challenge}'...")

        # make sure a token was set
        try:
            shell.get_dt1_token()
        except Exception as e:
            dtslogger.error(str(e))
            exit(1)

        # make sure we have the credentials to push to this registry
        try:
            shell_cfg: ShellConfig = read_shell_config()
        except TypeError:
            shell_cfg: ShellConfig = read_shell_config(shell)

        if registry_to_push not in shell_cfg.docker_credentials:
            dtslogger.error(
                f"You have no credentials set for registry '{registry_to_push}', "
                f"please use the command 'dts challenges config' fisrt"
            )
            exit(1)
        registry_creds: dict = shell_cfg.docker_credentials[registry_to_push]
        del registry_creds["secret"]

        # reuse username from credentials if none is given
        if parsed.username is None:
            parsed.username = registry_creds["username"]

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
            recipe=parsed.recipe,
            recipe_version=parsed.recipe_version,
            launcher=parsed.launcher,
            verbose=parsed.verbose,
            no_cache=parsed.no_cache,
            no_pull=parsed.no_pull,
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
        image: dockertown.Image = docker.image.inspect(src_name)

        # evaluate
        submission_config_fpath = project.recipe.path if project.needs_recipe else project.path
        submission_yaml_fpath = os.path.join(submission_config_fpath, "submission.yaml")
        if not os.path.isfile(submission_yaml_fpath):
            dtslogger.error(f"File '{submission_yaml_fpath}' not found! Aborting.")
            exit(1)
        evaluate_args: List[str] = [
            "--workdir",
            submission_config_fpath,
            "evaluate",
            "--config",
            "./submission.yaml",
            "--image",
            image.repo_tags[0],
            "--challenge",
            parsed.challenge,
            "--no-pull",
        ]
        # impersonate
        if parsed.impersonate:
            evaluate_args += ["--impersonate", parsed.impersonate]
        # ---
        dtslogger.info("Evaluating...")
        dtslogger.debug(f"Callind 'challenges/evaluate' using args: {evaluate_args}")
        shell.include.challenges.command(shell, evaluate_args)

    @staticmethod
    def complete(shell, word, line):
        return []
