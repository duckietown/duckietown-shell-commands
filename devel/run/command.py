import argparse
import json
import os
import shutil
import subprocess

from dt_shell import DTCommandAbs, dtslogger
from utils.cli_utils import check_program_dependency
from utils.docker_utils import DOCKER_INFO, get_endpoint_architecture, DEFAULT_MACHINE
from utils.dtproject_utils import CANONICAL_ARCH, BUILD_COMPATIBILITY_MAP, DTProject
from utils.misc_utils import human_size

LAUNCHER_FMT = "dt-launcher-%s"

DEFAULT_MOUNTS = ["/var/run/avahi-daemon/socket", "/data"]

DEFAULT_NETWORK_MODE = "host"

DEFAULT_REMOTE_USER = "duckie"


class DTCommand(DTCommandAbs):

    help = "Runs the current project"

    @staticmethod
    def command(shell, args: list):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "subcommand",
            nargs='?',
            default=None,
            help="(Optional) Subcommand to execute"
        )
        parser.add_argument(
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory containing the project to run"
        )
        parser.add_argument(
            "-a",
            "--arch",
            default=None,
            choices=set(CANONICAL_ARCH.values()),
            help="Target architecture for the image to run",
        )
        parser.add_argument(
            "-H",
            "--machine",
            default=DEFAULT_MACHINE,
            help="Docker socket or hostname where to run the image",
        )
        parser.add_argument(
            "-n",
            "--name",
            default=None,
            help="Name of the container"
        )
        parser.add_argument(
            "--cmd",
            default=None,
            help="Command to run in the Docker container"
        )
        parser.add_argument(
            "--pull",
            default=False,
            action="store_true",
            help="Whether to pull the image of the project"
        )
        parser.add_argument(
            "--force-pull",
            default=False,
            action="store_true",
            help="Whether to force pull the image of the project",
        )
        parser.add_argument(
            "--build",
            default=False,
            action="store_true",
            help="Whether to build the image of the project"
        )
        parser.add_argument(
            "--plain",
            default=False,
            action="store_true",
            help="Whether to run the image without default module configuration",
        )
        parser.add_argument(
            "--no-multiarch",
            default=False,
            action="store_true",
            help="Whether to disable multiarch support (based on bin_fmt)",
        )
        parser.add_argument(
            "-f",
            "--force",
            default=False,
            action="store_true",
            help="Whether to force the run when the git index is not clean",
        )
        parser.add_argument(
            "-M",
            "--mount",
            default=False,
            const=True,
            action="store",
            nargs="?",
            type=str,
            help="Whether to mount the current project into the container. "
            "Pass a comma-separated list of paths to mount multiple projects",
        )
        parser.add_argument(
            "-u",
            "--username",
            default="duckietown",
            help="The docker registry username that owns the Docker image",
        )
        parser.add_argument(
            "--rm",
            default=True,
            action="store_true",
            help="Whether to remove the container once done"
        )
        parser.add_argument(
            "-L",
            "--launcher",
            default=None,
            help="Launcher to invoke inside the container (template v2 or newer)"
        )
        parser.add_argument(
            "--loop",
            default=False,
            action="store_true",
            help="(Experimental) Whether to run the LOOP image"
        )
        parser.add_argument(
            "-A",
            "--argument",
            dest="arguments",
            default=[],
            action="append",
            help="Arguments for the container command",
        )
        parser.add_argument(
            "--runtime",
            default="docker",
            type=str,
            help="Docker runtime to use to run the container"
        )
        parser.add_argument(
            "-X",
            dest="use_x_docker",
            default=False,
            action="store_true",
            help="Use x-docker as runtime (needs to be installed separately)",
        )
        parser.add_argument(
            "-s",
            "--sync",
            default=False,
            action="store_true",
            help="Sync code from local project to remote"
        )
        parser.add_argument("docker_args", nargs="*", default=[])
        # add a fake positional argument to avoid missing the first argument starting with `-`
        try:
            idx = args.index('--')
            args = args[:idx] + ['--', '--fake'] + args[idx+1:]
        except ValueError:
            pass
        # parse arguments
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        parsed.workdir = os.path.abspath(parsed.workdir)
        # x-docker runtime
        if parsed.use_x_docker:
            parsed.runtime = "x-docker"
        # check runtime
        if shutil.which(parsed.runtime) is None:
            raise ValueError('Docker runtime binary "{}" not found!'.format(parsed.runtime))
        # ---
        dtslogger.info("Project workspace: {}".format(parsed.workdir))
        # show info about project
        shell.include.devel.info.command(shell, args)
        # get info about project
        project = DTProject(parsed.workdir)
        # container name
        if not parsed.name:
            parsed.name = 'dts-run-{:s}'.format(project.name)
        # subcommands
        if parsed.subcommand == 'attach':
            dtslogger.info(f'Attempting to attach to container {parsed.name}...')
            # run
            _run_cmd([
                parsed.runtime,
                '-H=%s' % parsed.machine,
                'exec', '-it', parsed.name, '/entrypoint.sh', 'bash']
                , suppress_errors=True
            )
            return
        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f"Target architecture automatically set to {parsed.arch}.")
        # get the module configuration
        module_configuration_args = []
        # apply default module configuration
        module_configuration_args.append(f"--net={DEFAULT_NETWORK_MODE}")
        # parse arguments
        mount_code = parsed.mount is True or isinstance(parsed.mount, str)
        mount_option = []
        # add default mount points
        for mountpoint in DEFAULT_MOUNTS:
            if parsed.machine == DEFAULT_MACHINE:
                # we are running locally, check if the mountpoint exists
                if not os.path.exists(mountpoint):
                    dtslogger.warning(
                        f"The mountpoint '{mountpoint}' does not exist. "
                        f"This can create issues inside the container."
                    )
                    continue
            mount_option += ["-v", "{:s}:{:s}".format(mountpoint, mountpoint)]
        # mount source code (if requested)
        if mount_code:
            projects_to_mount = [parsed.workdir] if parsed.mount is True else []
            # (always) mount current project
            # mount secondary projects
            if isinstance(parsed.mount, str):
                projects_to_mount.extend(
                    [os.path.join(os.getcwd(), p.strip()) for p in parsed.mount.split(",")]
                )
            # create mount points definitions
            for project_path in projects_to_mount:
                # make sure that the project exists
                if not os.path.isdir(project_path):
                    dtslogger.error('The path "{:s}" is not a Duckietown project'.format(project_path))
                # get project info
                proj = DTProject(project_path)
                # get local and remote paths to code and launchfile
                local_src, destination_src = proj.code_paths()
                local_launch, destination_launch = proj.launch_paths()
                # (experimental): when we run remotely, use /code/<project> as base
                if parsed.machine != DEFAULT_MACHINE:
                    project_path = "/code/%s" % proj.name
                # compile mounpoints
                mount_option += [
                    "-v",
                    "{:s}:{:s}".format(os.path.join(project_path, local_src), destination_src),
                    "-v",
                    "{:s}:{:s}".format(os.path.join(project_path, local_launch), destination_launch),
                ]
        # check if the index is clean
        if parsed.mount and project.is_dirty():
            dtslogger.warning("Your index is not clean (some files are not committed).")
            dtslogger.warning(
                "If you know what you are doing, use --force (-f) to force " "the execution of the command."
            )
            if not parsed.force:
                exit(1)
            dtslogger.warning("Forced!")
        # create image name
        image = project.image(parsed.arch, loop=parsed.loop, owner=parsed.username)
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
        epoint["MemTotal"] = human_size(epoint["MemTotal"])
        print(DOCKER_INFO.format(**epoint))
        # print info about multiarch
        msg = "Running an image for {} on {}.".format(parsed.arch, epoint["Architecture"])
        dtslogger.info(msg)
        # register bin_fmt in the target machine (if needed)
        if not parsed.no_multiarch:
            compatible_archs = BUILD_COMPATIBILITY_MAP[CANONICAL_ARCH[epoint["Architecture"]]]
            if parsed.arch not in compatible_archs:
                dtslogger.info("Configuring machine for multiarch...")
                try:
                    _run_cmd(
                        [
                            "docker",
                            "-H=%s" % parsed.machine,
                            "run",
                            "--rm",
                            "--privileged",
                            "multiarch/qemu-user-static:register",
                            "--reset",
                        ],
                        True,
                    )
                    dtslogger.info("Multiarch Enabled!")
                except:
                    msg = "Multiarch cannot be enabled on the target machine. This might create issues."
                    dtslogger.warning(msg)
            else:
                msg = "Running an image for {} on {}. Multiarch not needed!".format(
                    parsed.arch, epoint["Architecture"]
                )
                dtslogger.info(msg)
        # pulling image (if requested)
        if parsed.pull or parsed.force_pull:
            # check if the endpoint contains an image with the same name
            is_present = False
            try:
                out = _run_cmd(
                    ["docker", "-H=%s" % parsed.machine, "images", "--format", "{{.Repository}}:{{.Tag}}"],
                    get_output=True,
                    print_output=False,
                    suppress_errors=True,
                )
                is_present = image in out
            except:
                pass
            if not is_present or parsed.force_pull:
                # try to pull the image
                dtslogger.info('Pulling image "%s"...' % image)
                try:
                    _run_cmd(
                        ["docker", "-H=%s" % parsed.machine, "pull", image],
                        get_output=True,
                        print_output=True,
                        suppress_errors=True,
                    )
                except:
                    dtslogger.warning(
                        'An error occurred while pulling the image "%s", maybe the image does not exist'
                        % image
                    )
            else:
                dtslogger.info(
                    "Found an image with the same name. Using it. User --force-pull to force a new pull."
                )
        # cmd option
        if parsed.cmd and parsed.launcher:
            raise ValueError("You cannot use the option --launcher together with --cmd.")
        if parsed.launcher:
            parsed.cmd = LAUNCHER_FMT % parsed.launcher
        cmd_option = [] if not parsed.cmd else [parsed.cmd]
        cmd_arguments = (
            [] if not parsed.arguments else ["--"] + list(map(lambda s: "--%s" % s, parsed.arguments))
        )
        # docker arguments
        if not parsed.docker_args:
            parsed.docker_args = []
        if parsed.rm:
            parsed.docker_args += ["--rm"]
        # add container name to docker args
        parsed.docker_args += ["--name", parsed.name]
        # escape spaces in arguments
        parsed.docker_args = [a.replace(" ", "\\ ") for a in parsed.docker_args]
        # sync
        if parsed.sync:
            # only allowed when mounting remotely
            if parsed.machine == DEFAULT_MACHINE:
                dtslogger.error("The option -s/--sync can only be used together with -H/--machine")
                exit(2)
            # make sure rsync is installed
            check_program_dependency('rsync')
            # get project locations
            local_path = project.path
            remote_path = f"{DEFAULT_REMOTE_USER}@{parsed.machine}:/code/"
            # run rsync
            dtslogger.info(f"Syncing code with {parsed.machine.replace('.local', '')}...")
            cmd = f'rsync --archive {local_path} {remote_path}'
            _run_cmd(cmd, shell=True)
            dtslogger.info(f"Code synced!")
        # run
        _run_cmd(
            [parsed.runtime, "-H=%s" % parsed.machine, "run", "-it"]
            + module_configuration_args
            + parsed.docker_args
            + mount_option
            + [image]
            + cmd_option
            + cmd_arguments,
            suppress_errors=True,
        )

    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(cmd, get_output=False, print_output=False, suppress_errors=False, shell=False):
    if shell and isinstance(cmd, (list, tuple)):
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
