import argparse
import io
import os
import subprocess

from dt_shell import DTCommandAbs, dtslogger, DTShell

from utils.docker_utils import DEFAULT_MACHINE
from utils.docker_utils import get_endpoint_architecture


class DTCommand(DTCommandAbs):
    help = "Removes the Docker images relative to the current project"

    @staticmethod
    def _parse_args(args):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory containing the project to clean",
        )
        parser.add_argument(
            "-a",
            "--arch",
            default=None,
            help="Target architecture for the image to clean",
        )
        parser.add_argument(
            "-H",
            "--machine",
            default=DEFAULT_MACHINE,
            help="Docker socket or hostname where to clean the image",
        )
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._parse_args(args)
        if 'parsed' in kwargs:
            parsed.__dict__.update(kwargs['parsed'].__dict__)
        # ---
        dtslogger.info("Project workspace: {}".format(parsed.workdir))
        # show info about project
        shell.include.devel.info.command(shell, args)
        # get info about current repo
        repo_info = shell.include.devel.info.get_repo_info(parsed.workdir)
        repo = repo_info["REPOSITORY"]
        branch = repo_info["BRANCH"]
        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f'Target architecture automatically set to {parsed.arch}.')
        # create defaults
        default_tag = "duckietown/%s:%s" % (repo, branch)
        tag = "%s-%s" % (default_tag, parsed.arch)
        # remove image
        img = _run_cmd(
            ["docker", "-H=%s" % parsed.machine, "images", "-q", tag], get_output=True
        )
        if img:
            dtslogger.info("Removing image {}...".format(tag))
            try:
                _run_cmd(["docker", "-H=%s" % parsed.machine, "rmi", tag])
            except RuntimeError:
                dtslogger.warn(
                    "We had some issues removing the image '{:s}' on '{:s}'".format(
                        tag, parsed.machine
                    ) + ". Just a heads up!"
                )

    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(cmd, get_output=False, print_output=False):
    dtslogger.debug("$ %s" % cmd)
    if get_output:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        lines = []
        for line in io.TextIOWrapper(proc.stdout, encoding="utf-8"):
            line = line.rstrip()
            if print_output:
                print(line)
            if line:
                lines.append(line)
        proc.wait()
        if proc.returncode != 0:
            msg = "The command {} returned exit code {}".format(cmd, proc.returncode)
            dtslogger.error(msg)
            raise RuntimeError(msg)
        return lines
    else:
        subprocess.check_call(cmd)
