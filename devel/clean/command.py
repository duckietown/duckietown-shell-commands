import os
import argparse
import subprocess
import io
from dt_shell import DTCommandAbs, dtslogger

DEFAULT_ARCH = "arm32v7"
DEFAULT_MACHINE = "unix:///var/run/docker.sock"


from dt_shell import DTShell


class DTCommand(DTCommandAbs):

    help = "Removes the Docker images relative to the current project"

    @staticmethod
    def command(shell: DTShell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=None,
            help="Directory containing the project to clean",
        )
        parser.add_argument(
            "-a",
            "--arch",
            default=DEFAULT_ARCH,
            help="Target architecture for the image to clean",
        )
        parser.add_argument(
            "-H",
            "--machine",
            default=DEFAULT_MACHINE,
            help="Docker socket or hostname where to clean the image",
        )
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        code_dir = parsed.workdir if parsed.workdir else os.getcwd()
        dtslogger.info("Project workspace: {}".format(code_dir))
        # show info about project
        shell.include.devel.info.command(shell, args)
        # get info about current repo
        repo_info = shell.include.devel.info.get_repo_info(code_dir)
        repo = repo_info["REPOSITORY"]
        branch = repo_info["BRANCH"]
        nmodified = repo_info["INDEX_NUM_MODIFIED"]
        nadded = repo_info["INDEX_NUM_ADDED"]
        # create defaults
        default_tag = "duckietown/%s:%s" % (repo, branch)
        tag = "%s-%s" % (default_tag, parsed.arch)
        tags = [tag] + ([default_tag] if parsed.arch == DEFAULT_ARCH else [])
        # remove images
        for t in tags:
            img = _run_cmd(
                ["docker", "-H=%s" % parsed.machine, "images", "-q", t], get_output=True
            )
            if img:
                dtslogger.info("Removing image {}...".format(t))
                _run_cmd(["docker", "-H=%s" % parsed.machine, "rmi", t])

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
