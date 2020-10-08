import argparse
import os

from dt_shell import DTCommandAbs, dtslogger

from utils.cli_utils import start_command_in_subprocess
from utils.dtproject_utils import DTProject


class DTCommand(DTCommandAbs):

    help = "Bumps the current project's version"

    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory containing the project to build"
        )
        parser.add_argument(
            "-n",
            "--dry-run",
            default=False,
            action="store_true",
            help="Don't write any files, just pretend."
        )
        parser.add_argument(
            "part",
            nargs="?",
            choices=["major", "minor", "patch"],
            default="patch",
            help="Part of the version to bump",
        )
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        parsed.workdir = os.path.abspath(parsed.workdir)
        # make sure that bumpversion is available
        try:
            import bumpversion
        except ImportError:
            dtslogger.error(
                "The command `dts devel bump` requires the Python3 package "
                "`bumpversion`. Please install it using `pip3`."
            )
            return
        # show info about project
        dtslogger.info("Project workspace: {}".format(parsed.workdir))
        shell.include.devel.info.command(shell, args)
        project = DTProject(parsed.workdir)
        # check if the index is clean
        if project.is_dirty():
            dtslogger.warning("Your index is not clean (some files are not committed).")
            dtslogger.warning("You cannot bump the version while the index is not clean.")
            dtslogger.warning("Please, commit your changes and try again.")
            exit(1)
        # check if the project is already released
        if project.is_release():
            dtslogger.info("The project is already on a release commit. Nothing to do.")
            return
        # prepare call
        options = ["--verbose"]
        if parsed.dry_run:
            options += ["--dry-run"]
        cmd = ["cd", '"{}"'.format(parsed.workdir), ";", "bumpversion"] + options + [parsed.part]
        print(cmd)
        start_command_in_subprocess(cmd, shell=True)
