import argparse
import json
import os
import shutil
import subprocess
from typing import List, Optional

from dt_shell import DTCommandAbs, dtslogger

from dtproject import DTProject
from dtproject.constants import (
    BUILD_COMPATIBILITY_MAP,
    CANONICAL_ARCH
)
from utils.cli_utils import ensure_command_is_installed
from utils.docker_utils import (
    DEFAULT_MACHINE,
    DOCKER_INFO,
    get_endpoint_architecture,
    get_registry_to_use, CLOUD_BUILDERS, get_cloud_builder,
)
from utils.misc_utils import human_size, sanitize_hostname
from utils.multi_command_utils import MultiCommand

from .configuration import DEFAULT_TRUE

LAUNCHER_FMT = "dt-launcher-%s"
DEFAULT_MOUNTS = ["/var/run/avahi-daemon/socket", "/data"]
REMOTE_USER = "duckie"
REMOTE_GROUP = "duckie"


class DTCommand(DTCommandAbs):
    help = "Runs the current project"

    @staticmethod
    def command(shell, args: list):
        parser: argparse.ArgumentParser = DTCommand.parser
        # try to interpret it as a multi-command
        multi = MultiCommand(DTCommand, shell, [("-H", "--machine")], args)
        if multi.is_multicommand:
            multi.execute()
            return
        # everything after "++" is a passthrough for the container's command
        container_cmd_arguments: Optional[List[str]] = None
        if "++" in args:
            idx: int = args.index("++")
            container_cmd_arguments = args[idx+1:]
            args = args[:idx]
        # add a fake positional argument to avoid missing the first argument starting with `-`
        try:
            idx = args.index("--")
            args = args[:idx] + ["--", "--fake"] + args[idx + 1:]
        except ValueError:
            pass
        # parse arguments
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        parsed.workdir = os.path.abspath(parsed.workdir)

        # incompatible args
        if isinstance(parsed.mount, (bool, str)) and parsed.mount and parsed.no_mount:
            dtslogger.error("You cannot both -m/--mount and --no-mount at the same time.")
            exit(1)

        # mount
        if parsed.mount is DEFAULT_TRUE:
            parsed.mount = True

        # no-mount
        if parsed.no_mount:
            parsed.mount = False

        # cloud run
        if parsed.cloud:
            if parsed.arch is None:
                dtslogger.error(
                    "When running on the cloud, you need to explicitly specify "
                    "a target architecture. Aborting..."
                )
                exit(1)
            if parsed.machine is not None:
                dtslogger.error(
                    "The parameter --machine (-H) cannot be set together with "
                    + "--cloud. Aborting..."
                )
                exit(1)
            # route the run to the native node
            if parsed.arch not in CLOUD_BUILDERS:
                dtslogger.error(f"No cloud machines found for target architecture {parsed.arch}. Aborting...")
                exit(1)
            # update machine parameter
            parsed.machine = get_cloud_builder(parsed.arch)
        else:
            # local builder is the default
            if parsed.machine is not None:
                # sanitize hostname
                parsed.machine = sanitize_hostname(parsed.machine)
            else:
                parsed.machine = DEFAULT_MACHINE

        # when we run against a remote machine, we need to sync the code
        if parsed.machine != DEFAULT_MACHINE:
            parsed.sync = True

        # x-docker runtime
        if parsed.use_x_docker:
            command_dir = os.path.dirname(os.path.abspath(__file__))
            parsed.runtime = os.path.join(command_dir, "x-docker")

        # check runtime
        if not parsed.cloud and shutil.which(parsed.runtime) is None:
            raise ValueError('Docker runtime binary "{}" not found!'.format(parsed.runtime))

        # ---

        dtslogger.info("Project workspace: {}".format(parsed.workdir))
        # show info about project
        shell.include.devel.info.command(shell, args)

        # get info about project
        project = DTProject(parsed.workdir)

        # container name
        if not parsed.name:
            parsed.name = "dts-run-{:s}".format(project.name)

        # subcommands
        if parsed.subcommand == "attach":
            dtslogger.info(f"Attempting to attach to container {parsed.name}...")
            # run
            _run_cmd(
                [
                    parsed.runtime,
                    "-H=%s" % parsed.machine,
                    "exec",
                    "-it",
                    parsed.name,
                    "/entrypoint.sh",
                    "bash",
                ],
                suppress_errors=True,
            )
            return

        # registry
        registry_to_use = get_registry_to_use()

        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f"Target architecture automatically set to {parsed.arch}.")

        # tag
        version = project.distro
        if parsed.tag:
            dtslogger.info(f"Overriding version {version!r} with {parsed.tag!r}")
            version = parsed.tag

        # get the module configuration
        # noinspection PyListCreation
        module_configuration_args = []
        # apply default module configuration
        module_configuration_args.append(f"--net={parsed.network_mode}")
        # environment
        if parsed.ros is not None:
            # parsed.ros = parsed.ros if parsed.ros.endswith('.local') else f'{parsed.ros}.local'
            module_configuration_args.append(f"-e=VEHICLE_NAME={parsed.ros}")
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
                    dtslogger.error(f"The path '{project_path}' is not a Duckietown project")
                # get project info
                proj = DTProject(project_path)
                rcode: str = parsed.sync_destination
                # (experimental): when we run remotely, use <rcode>/<project> as root
                local: bool = parsed.machine == DEFAULT_MACHINE
                root = os.path.join(rcode, proj.name) if not local else proj.path
                # get local and remote paths to code
                local_srcs, destination_srcs = proj.code_paths(root)
                # compile mountpoints
                for local_src, destination_src in zip(local_srcs, destination_srcs):
                    if parsed.read_write:
                        mount_option += ["-v", "{:s}:{:s}:rw".format(local_src, destination_src)]
                    else:
                        mount_option += ["-v", "{:s}:{:s}:ro".format(local_src, destination_src)]
                # get local and remote paths to launchers
                local_launchs, destination_launchs = proj.launch_paths(root)
                if isinstance(local_launchs, str):
                    local_launchs = [local_launchs]
                    destination_launchs = [destination_launchs]
                # compile mountpoints
                for local_launch, destination_launch in zip(local_launchs, destination_launchs):
                    mount_option += ["-v", "{:s}:{:s}".format(local_launch, destination_launch)]
                    # make sure the launchers are executable (local only)
                    if local:
                        try:
                            _run_cmd(["chmod", "a+x", os.path.join(local_launch, "*")], shell=True)
                        except Exception:
                            dtslogger.warning("An error occurred while making the launchers executable. "
                                              "Things might not work as expected.")

        # create image name
        image = project.image(
            arch=parsed.arch,
            loop=parsed.loop,
            registry=registry_to_use,
            owner=parsed.username,
            version=version,
        )

        # get info about docker endpoint
        # TODO: this can be moved to a separate function or command
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
            [] if not container_cmd_arguments else
            (["--"] if not cmd_option else []) + container_cmd_arguments
        )

        # environment
        if parsed.machine == DEFAULT_MACHINE:
            module_configuration_args += [
                f"-e=IMPERSONATE_UID={os.getuid()}",
                # NOTE: it is important to leave the container user's GID so that he can access his old files
            ]

        # docker arguments
        if not parsed.docker_args:
            parsed.docker_args = []
        if (not parsed.no_rm) or (not parsed.detach):
            parsed.docker_args += ["--rm"]
        if parsed.detach:
            parsed.docker_args += ["-d"]

        # add container name to docker args
        parsed.docker_args += ["--name", parsed.name]

        # escape spaces in arguments
        parsed.docker_args = [a.replace(" ", "\\ ") for a in parsed.docker_args]

        # sync
        if parsed.sync:
            # TODO: this can just become a call to devel.sync
            # only allowed when mounting remotely
            if parsed.machine == DEFAULT_MACHINE:
                dtslogger.error("The option -s/--sync can only be used together with -H/--machine")
                exit(2)
            # make sure rsync is installed
            ensure_command_is_installed("rsync", dependant="dts devel run")
            dtslogger.info(f"Syncing code with {parsed.machine.replace('.local', '')}...")
            remote_path = f"{parsed.sync_user}@{parsed.machine}:{parsed.sync_destination.rstrip('/')}/"
            # get projects' locations
            projects_to_sync = [parsed.workdir] if parsed.mount is True else []
            # sync secondary projects
            if isinstance(parsed.mount, str):
                projects_to_sync.extend(
                    [os.path.abspath(os.path.join(os.getcwd(), p.strip())) for p in parsed.mount.split(",")]
                )
            # run rsync
            for project_path in projects_to_sync:
                cmd = f"rsync --archive --delete --copy-links --chown={REMOTE_USER}:{REMOTE_GROUP} {project_path} {remote_path}"
                _run_cmd(cmd, shell=True)
            dtslogger.info(f"Code synced!")

        # run
        exitcode = _run_cmd(
            [parsed.runtime, "-H=%s" % parsed.machine, "run", "-it"]
            + module_configuration_args
            + parsed.docker_args
            + mount_option
            + [image]
            + cmd_option
            + cmd_arguments,
            suppress_errors=True,
            return_exitcode=True,
        )
        dtslogger.debug(f"Command exited with exit code [{exitcode}].")
        if parsed.detach:
            dtslogger.info("Your container is running in detached mode!")

    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(
        cmd, get_output=False, print_output=False, suppress_errors=False, shell=False, return_exitcode=False
):
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
        if return_exitcode:
            res = subprocess.run(cmd, shell=shell)
            return res.returncode
        else:
            try:
                subprocess.check_call(cmd, shell=shell)
            except subprocess.CalledProcessError as e:
                if not suppress_errors:
                    raise e
