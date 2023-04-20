import argparse
import io
import os
import subprocess

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.docker_utils import DEFAULT_MACHINE, get_endpoint_architecture, get_registry_to_use
from dtproject import DTProject
from utils.duckietown_utils import DEFAULT_OWNER


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
        parser.add_argument(
            "--tag", default=None, help="Overrides 'version' (usually taken to be branch name)"
        )

        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._parse_args(args)
        if "parsed" in kwargs:
            parsed.__dict__.update(kwargs["parsed"].__dict__)
        # ---
        dtslogger.info("Project workspace: {}".format(parsed.workdir))

        # show info about project
        shell.include.devel.info.command(shell, args)
        project = DTProject(parsed.workdir)

        registry_to_use = get_registry_to_use()

        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f"Target architecture automatically set to {parsed.arch}.")

        # tag
        version = project.version_name
        if parsed.tag:
            dtslogger.info(f"Overriding version {version!r} with {parsed.tag!r}")
            version = parsed.tag

        # create defaults
        images = [
            project.image(arch=parsed.arch, registry=registry_to_use, owner=DEFAULT_OWNER, version=version)
        ]
        # clean release version
        if project.is_release():
            images.append(
                project.image_release(arch=parsed.arch, registry=registry_to_use, owner=DEFAULT_OWNER)
            )
        # remove images
        for image in images:
            img = _run_cmd(["docker", "-H=%s" % parsed.machine, "images", "-q", image], get_output=True)
            if img:
                dtslogger.info("Removing image {}...".format(image))
                try:
                    _run_cmd(["docker", "-H=%s" % parsed.machine, "rmi", image])
                except RuntimeError:
                    dtslogger.warn(
                        "We had some issues removing the image '{:s}' on '{:s}'".format(image, parsed.machine)
                        + ". Just a heads up!"
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
