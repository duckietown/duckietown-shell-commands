import argparse
import os
import subprocess

from dt_shell import DTCommandAbs, dtslogger

from utils.docker_utils import DEFAULT_MACHINE, get_endpoint_architecture
from utils.dtproject_utils import ARCH_MAP
from utils.dtproject_utils import DTProject

from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    help = "Push the images relative to the current project"

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=None,
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
            "-f",
            "--force",
            default=False,
            action="store_true",
            help="Whether to force the push when the git index is not clean",
        )
        parser.add_argument(
            '-u',
            '--username',
            default="duckietown",
            help="the docker registry username to tag the image with"
        )
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._parse_args(args)
        if 'parsed' in kwargs:
            parsed.__dict__.update(kwargs['parsed'].__dict__)
        # ---
        code_dir = parsed.workdir if parsed.workdir else os.getcwd()
        dtslogger.info("Project workspace: {}".format(code_dir))
        # show info about project
        shell.include.devel.info.command(shell, args)
        project = DTProject(code_dir)
        # check if the index is clean
        if project.is_dirty():
            dtslogger.warning("Your index is not clean (some files are not committed).")
            dtslogger.warning("If you know what you are doing, use --force to force the "
                              "execution of the command.")
            if not parsed.force:
                exit(1)
            dtslogger.warning("Forced!")
        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f'Target architecture automatically set to {parsed.arch}.')
        # create defaults
        image = project.image(parsed.arch, owner=parsed.username)
        _run_cmd(["docker", "-H=%s" % parsed.machine, "push", image])

    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(cmd, env=None):
    dtslogger.debug("$ %s" % cmd)
    environ = os.environ
    if env:
      environ.update(env)
    subprocess.check_call(cmd, env=environ)
