import argparse
import os
import subprocess
import tempfile
from typing import List

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.constants import DTShellConstants
from dtproject import DTProject
from utils.cli_utils import start_command_in_subprocess, ask_confirmation


class DTCommand(DTCommandAbs):
    help = "Computes the diff between the current project and its template"

    @staticmethod
    def command(shell: DTShell, args):
        parser: argparse.ArgumentParser = DTCommand.parser
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        code_dir = parsed.workdir if parsed.workdir else os.getcwd()
        dtslogger.info("Project workspace: {}".format(code_dir))
        # show info about project
        shell.include.devel.info.command(shell, args)
        # get info about current project
        project = DTProject(code_dir)
        # check if the index is clean
        if project.is_dirty():
            dtslogger.warning("Your index is not clean.")
            dtslogger.warning("This command compares the template against committed changes.")
            print()
        # get template type
        template = project.type
        if parsed.template is not None:
            template = parsed.template
        if template == "none":
            dtslogger.info("No templates to compare against.")
            return
        # prepend `duckietown/` if a user is not given
        if "/" not in template:
            template = f"duckietown/{template}"
        # get template version
        template_version = "v" + project.type_version
        if parsed.version is not None:
            # verify if `version` is an integer
            try:
                v = int(parsed.version)
                template_version = f"v{v}"
            except ValueError:
                template_version = parsed.version
        # treat projects with a repository differently
        if os.path.isdir(os.path.join(project.path, ".git")):
            dtslogger.info("Detected GIT repository at the root of this project, using 'git diff'...")
            # use git diff to perform the update
            DTCommand._repository_project(project.path, template, template_version, parsed)
        else:
            dtslogger.info("This project does not have a GIT project at its root, using 'rsync'...")
            # use rsync to re-apply the template to the project directory
            DTCommand._non_repository_project(project.path, template, template_version, parsed)

    @staticmethod
    def complete(shell, word, line):
        return []

    @staticmethod
    def _repository_project(path: str, template: str, template_version: str, parsed: argparse.Namespace):
        # script path
        script_path = os.path.join(
            os.path.abspath(os.path.dirname(__file__)), "..", "assets", "template_ops.sh"
        )
        # perform action
        env = {
            "CODE_DIR": path,
            "TEMPLATE_TYPE": template,
            "TEMPLATE_VERSION": template_version,
            "APPLY_DIFF": str(int(parsed.apply)),
            "MODE": "brute" if parsed.brute else "conservative",
        }
        if parsed.apply:
            dtslogger.info("Applying diff...")
        p = subprocess.Popen(script_path, env=env, shell=True)
        p.communicate()

    @staticmethod
    def _non_repository_project(path: str, template: str, template_version: str, parsed: argparse.Namespace):
        # use rsync to re-apply the template to the project directory
        if not parsed.apply:
            dtslogger.warning("The project you are trying to update does not have a git repository at "
                              "its root. These projects cannot be diff-ed against the template, they can "
                              "only be updated directly (with --apply).")
            return False
        if not parsed.brute:
            dtslogger.warning("The project you are trying to update does not have a git repository at "
                              "its root. These projects can only be updated with the flag --brute.")
            return False
        granted = ask_confirmation("WARNING: If your project is not part of a git repository or if you have "
                                   "uncommitted changes, this action will likely result in loss of data in "
                                   "your project.")
        if not granted:
            dtslogger.info("Aborting.")
            return
        # download the template to a temporary directory
        with tempfile.TemporaryDirectory() as tmpdir:
            template_url: str = f"https://github.com/{template}"
            cmd: List[str] = ["git", "clone", "-b", template_version, template_url, tmpdir]
            dtslogger.info("Downloading template...")
            start_command_in_subprocess(cmd)
            dtslogger.info("Template downloaded!")
            # run rsync between the downloaded template and the project
            opts = []
            if DTShellConstants.VERBOSE:
                opts.append("--verbose")
            cmd = ["rsync", "--archive", "--delete-after"] + \
                  opts + ["--exclude", ".git", f"{tmpdir}/.", f"{path}/"]
            dtslogger.info(f"Applying template '{template}@{template_version}' to project in '{path}'...")
            start_command_in_subprocess(cmd)
            dtslogger.info("Template applied!")


def _run_cmd(cmd):
    print(cmd)
    return [line for line in subprocess.check_output(cmd).decode("utf-8").split("\n") if line]
