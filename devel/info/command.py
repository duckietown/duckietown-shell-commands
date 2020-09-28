import os
import argparse
import termcolor as tc

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

nocolor = lambda s, *_: s


class DTCommand(DTCommandAbs):

    help = "Shows information about the current project"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the project to show",
        )
        parser.add_argument(
            "--ci",
            default=False,
            action="store_true",
            help="Overwrites configuration for CI (Continuous Integration)",
        )
        parsed, _ = parser.parse_known_args(args=args)
        if "parsed" in kwargs:
            parsed.__dict__.update(kwargs["parsed"].__dict__)
        # ---
        if parsed.ci:
            # disable coloring
            tc.colored = nocolor
        parsed.workdir = os.path.abspath(parsed.workdir)
        project = DTProject(parsed.workdir)
        info = {
            "name": project.name,
            "branch": project.repository.branch,
            "distro": project.distro,
            "index": tc.colored("Clean", "green") if project.is_clean() else tc.colored("Dirty", "yellow"),
            "path": project.path,
            "type": project.type,
            "type_version": project.type_version,
            "version": project.version,
            "project": tc.colored("Project:", "grey", "on_white"),
            "space": tc.colored("  ", "grey", "on_white"),
            "end": tc.colored("________", "grey", "on_white"),
        }
        print(PROJECT_INFO.format(**info))

    @staticmethod
    def complete(shell, word, line):
        return []
