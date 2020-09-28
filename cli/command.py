import os
import json
import shutil
import argparse
import subprocess
import uuid

from utils.duckietown_utils import get_distro_version

from dt_shell import DTCommandAbs, dtslogger, DTShell


DEFAULT_MACHINE = "unix:///var/run/docker.sock"
DEFAULT_IMAGE = "duckietown/dt-gui-tools:{distro}-{arch}"
DEFAULT_RUNTIME = "docker"
CANONICAL_ARCH = {
    "arm": "arm32v7",
    "arm32v7": "arm32v7",
    "armv7l": "arm32v7",
    "armhf": "arm32v7",
    "x64": "amd64",
    "x86_64": "amd64",
    "amd64": "amd64",
    "Intel 64": "amd64",
    "arm64": "arm64v8",
    "arm64v8": "arm64v8",
    "armv8": "arm64v8",
    "aarch64": "arm64v8",
}
DEFAULT_VOLUMES = ["/var/run/avahi-daemon/socket"]


class DTCommand(DTCommandAbs):

    help = "Easy way to run CLI commands inside a Duckietown ROS environment"

    @staticmethod
    def command(shell: DTShell, args):
        if "--help" in args or "-h" in args:
            print(
                "\nRun the command <command> inside a Duckietown ROS environment as:"
                "\n\n\tdts %s [options] -- [command]\n\n----\n" % DTCommand.name
            )
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-H",
            "--machine",
            default=DEFAULT_MACHINE,
            help="Docker socket or hostname where to run the image",
        )
        parser.add_argument("-i", "--image", default=None, help="Docker image to run the command in")
        parser.add_argument(
            "--runtime", default=DEFAULT_RUNTIME, type=str, help="Docker runtime to use to run the container"
        )
        parser.add_argument(
            "-X",
            dest="use_x_docker",
            default=False,
            action="store_true",
            help="Use x-docker as runtime (needs to be installed separately)",
        )
        parser.add_argument("-M", "--master", default=None, type=str, help="Hostname of the ROS Master node")
        parser.add_argument(
            "-e",
            "--env",
            dest="environ",
            default=[],
            action="append",
            help="Environment variables to set inside the environment container",
        )
        parser.add_argument(
            "-A",
            "--argument",
            dest="arguments",
            default=[],
            action="append",
            help="Additional docker arguments for the environment container",
        )
        parser.add_argument("command", nargs="*", default=[])
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        # docker runtime and use_x_docker are mutually exclusive
        if parsed.use_x_docker and parsed.runtime != DEFAULT_RUNTIME:
            raise ValueError("You cannot use --runtime and -X at the same time.")
        # x-docker runtime
        if parsed.use_x_docker:
            parsed.runtime = "x-docker"
        # check runtime
        if shutil.which(parsed.runtime) is None:
            raise ValueError('Docker runtime binary "{}" not found!'.format(parsed.runtime))
        # environ
        environ = []
        # ROS master
        if parsed.master:
            master = parsed.master if parsed.master.endswith("local") else f"{parsed.master}.local"
            environ += ["--env", f"ROS_MASTER_URI=http://{master}:11311"]
        # environment variables
        environ += list(map(lambda e: "--env=%s" % e, parsed.environ))
        # docker arguments
        docker_arguments = [] if not parsed.arguments else list(map(lambda s: "--%s" % s, parsed.arguments))
        # check command
        if not parsed.command:
            parsed.command = ["/bin/bash"]
        # get info about docker endpoint
        dtslogger.info("Retrieving info about Docker endpoint...")
        epoint = _run_cmd(
            ["docker", "-H=%s" % parsed.machine, "info", "--format", "{{json .}}"],
            get_output=True,
            print_output=False,
        )
        epoint = json.loads(epoint)
        if "ServerErrors" in epoint:
            dtslogger.error("\n".join(epoint["ServerErrors"]))
            return
        if epoint["Architecture"] not in CANONICAL_ARCH:
            raise ValueError("The architecture %s is not supported" % epoint["Architecture"])
        endpoint_arch = CANONICAL_ARCH[epoint["Architecture"]]
        # volumes
        volumes = ["--volume=%s:%s" % (v, v) for v in DEFAULT_VOLUMES if os.path.exists(v)]
        # compile image name
        image = (
            parsed.image
            if parsed.image
            else DEFAULT_IMAGE.format(distro=get_distro_version(shell), arch=endpoint_arch)
        )
        # print info
        dtslogger.info("Running command [%s]..." % " ".join(parsed.command))
        print("------>")
        # run container with command inside
        _run_cmd(
            [
                parsed.runtime,
                "-H=%s" % parsed.machine,
                "run",
                "-it",
                "--rm",
                "--net=host",
                "--name",
                str(uuid.uuid4())[:8],
            ]
            + environ
            + volumes
            + docker_arguments
            + [image]
            + parsed.command,
            suppress_errors=True,
        )
        # ---
        print("<------")

    @staticmethod
    def complete(shell, word, line):
        return [
            # non-exhaustive list of common ROS commands
            # - ros* cli
            "rosrun",
            "rosmsg",
            "rostopic",
            "rosnode",
            "rosservice",
            "rossrv",
            "rosparam",
            # - rqt* cli
            "rqt",
            "rqt_image_view",
            "rqt_graph",
            # - others
            "rviz",
        ]


def _run_cmd(cmd, get_output=False, print_output=False, suppress_errors=False, shell=False):
    if shell:
        cmd = " ".join([str(s) for s in cmd])
    dtslogger.debug("$ %s" % cmd)
    if get_output:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=shell)
        proc.wait()
        if proc.returncode != 0:
            if not suppress_errors:
                msg = "The command {} returned exit code {}".format(cmd, proc.returncode)
                dtslogger.error(msg)
                raise RuntimeError(msg)
        out = proc.stdout.read().decode("utf-8").rstrip()
        if print_output:
            print(out)
        return out
    else:
        try:
            subprocess.check_call(cmd, shell=shell)
        except subprocess.CalledProcessError as e:
            if not suppress_errors:
                raise e
