import os
import argparse

from termcolor import colored

from utils.dtproject_utils import DTProject

from dt_shell import DTShell, DTCommandAbs

PROJECT_INFO = """
{project}
{space}Name: {name}
{space}Distro: {distro}
{space}Branch: {branch}
{space}Index: {index}
{space}Version: {version}
{space}Path: {path}
{space}Type: {type}
{space}Template Version: {type_version}
{end}
"""


class DTCommand(DTCommandAbs):

    help = "Shows information about the current project"

    @staticmethod
    def command(shell: DTShell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=None,
            help="Directory containing the project to show",
        )
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        code_dir = parsed.workdir if parsed.workdir else os.getcwd()
        project = DTProject(code_dir)
        info = {
            "name": project.name,
            "branch": project.repository.branch,
            "distro": project.distro,
            "index": colored("Clean", "green") if project.is_clean() else colored("Dirty",
                                                                                  "yellow"),
            "path": project.path,
            "type": project.type,
            "type_version": project.type_version,
            "version": project.version,
            "project": colored("Project:", "grey", "on_white"),
            "space": colored("  ", "grey", "on_white"),
            "end": colored("________", "grey", "on_white"),
        }
        print(PROJECT_INFO.format(**info))

    @staticmethod
    def complete(shell, word, line):
        return []
