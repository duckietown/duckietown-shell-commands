import glob

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from typing import List, Optional, Dict, Tuple

import yaml

from dt_shell import DTCommandAbs, dtslogger

from dtproject import DTProject
from dtproject.constants import (
    BUILD_COMPATIBILITY_MAP,
    CANONICAL_ARCH
)
from dtproject.types import LayerContainers, ContainerConfiguration
from utils.cli_utils import ensure_command_is_installed
from utils.docker_utils import (
    DEFAULT_MACHINE,
    DOCKER_INFO,
    get_endpoint_architecture,
    get_registry_to_use, CLOUD_BUILDERS, get_cloud_builder, merge_docker_compose_services,
)
from utils.misc_utils import human_size, sanitize_hostname, pretty_exc, pretty_yaml, random_string
from utils.multi_command_utils import MultiCommand

from .configuration import DEFAULT_TRUE

LAUNCHER_FMT = "dt-launcher-%s"
DEFAULT_MOUNTS = ["/var/run/avahi-daemon/socket", "/data/"]
REMOTE_USER = "duckie"
REMOTE_GROUP = "duckie"


class DTCommand(DTCommandAbs):
    help = "Runs the current project"

    @staticmethod
    def command(shell, args: list, **kwargs):
        # get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        container_cmd_arguments: Optional[List[str]] = None
        if parsed is None:
            # parse arguments
            parsed, _ = DTCommand.parser.parse_known_args(args=args)
            # try to interpret it as a multi-command
            multi = MultiCommand(DTCommand, shell, [("-H", "--machine")], args)
            if multi.is_multicommand:
                multi.execute()
                return
            # everything after "++" is a passthrough for the container's command
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
        else:
            # combine given args with default values
            default_parsed = DTCommand.parser.parse_args(args=[])
            for k, v in parsed.__dict__.items():
                setattr(default_parsed, k, v)
            parsed = default_parsed

        # ---
        parsed.workdir = os.path.abspath(parsed.workdir)

        # incompatible args
        # - mount and no-mount
        if isinstance(parsed.mount, (bool, str)) and parsed.mount and parsed.no_mount:
            dtslogger.error("You cannot both -m/--mount and --no-mount at the same time.")
            exit(1)

        # - docker args and configuration
        if parsed.configuration is not None and parsed.docker_args:
            dtslogger.error("You cannot use positional arguments together with -g/--configuration.")
            exit(1)

        # we mount the code inside the container by default unless we are using --cloud
        if parsed.mount is DEFAULT_TRUE:
            parsed.mount = not parsed.cloud

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

        # when we run against a remote machine, we need to sync the code (unless we are using --cloud)
        if parsed.machine != DEFAULT_MACHINE:
            parsed.sync = not parsed.cloud

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

        # container config - network mode
        cc_network_mode: str = parsed.network_mode
        # container config - environment
        cc_environment: Dict[str, str] = {}

        # environment
        if parsed.robot is not None:
            cc_environment["VEHICLE_NAME"] = parsed.robot

        # parse arguments
        mount_code = parsed.mount is True or isinstance(parsed.mount, str)

        cc_mountpoints: List[Tuple[str, str, str]] = []

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
            cc_mountpoints.append((mountpoint, mountpoint, "rw"))

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

                # mount code
                if not parsed.no_mount_code:
                    # get local and remote paths to code
                    local_srcs, destination_srcs = proj.code_paths(root)
                    # compile mountpoints
                    for local_src, destination_src in zip(local_srcs, destination_srcs):
                        if parsed.read_write:
                            cc_mountpoints.append((local_src, destination_src, "rw"))
                        else:
                            cc_mountpoints.append((local_src, destination_src, "ro"))

                # mount launchers
                if not parsed.no_mount_launchers:
                    # get local and remote paths to launchers
                    local_launchs, destination_launchs = proj.launch_paths(root)
                    if isinstance(local_launchs, str):
                        local_launchs = [local_launchs]
                        destination_launchs = [destination_launchs]
                    # compile mountpoints
                    for local_launch, destination_launch in zip(local_launchs, destination_launchs):
                        # mount only if the launchers dir exists
                        if not os.path.isdir(local_launch):
                            continue

                        cc_mountpoints.append((local_launch, destination_launch, "rw"))
                        # make sure the launchers are executable (local only)
                        if local:
                            # noinspection PyBroadException
                            try:
                                _run_cmd(["chmod", "a+x", os.path.join(local_launch, "*")], shell=True)
                            except Exception:
                                dtslogger.warning("An error occurred while making the launchers executable. "
                                                  "Things might not work as expected.")

                # mount libraries explicitly to support symlinks (local only)
                if not parsed.no_mount_libraries and local:
                    # get local and remote paths to code
                    local_srcs, destination_srcs = proj.code_paths(root)
                    for local_src, destination_src in zip(local_srcs, destination_srcs):
                        local_src = os.path.abspath(local_src)
                        # itearate over libraries
                        for local_lib in glob.glob(os.path.join(local_src, "libraries", "*")):
                            lib_name = os.path.basename(local_lib)
                            if os.path.islink(local_lib):
                                local_mountpoint = os.path.join(local_src, "libraries", f"__{lib_name}")
                                os.makedirs(local_mountpoint, exist_ok=True)
                                real_local_lib = os.path.realpath(local_lib)
                                destination_lib: str = os.path.join(destination_src, "libraries", f"__{lib_name}")
                                cc_mountpoints.append((real_local_lib, destination_lib, "rw"))

        # create image name
        cc_image = project.image(
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
                # noinspection PyBroadException
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
                except Exception as e:
                    msg = "Multiarch cannot be enabled on the target machine. This might create issues."
                    dtslogger.warning(msg)
                    dtslogger.debug("An exception occurred:\n" + pretty_exc(e, 4))
            else:
                msg = "Running an image for {} on {}. Multiarch not needed!".format(
                    parsed.arch, epoint["Architecture"]
                )
                dtslogger.info(msg)

        # pulling image (if requested)
        if parsed.pull or parsed.force_pull:
            # check if the endpoint contains an image with the same name
            is_present = False
            # noinspection PyBroadException
            try:
                out = _run_cmd(
                    ["docker", "-H=%s" % parsed.machine, "images", "--format", "{{.Repository}}:{{.Tag}}"],
                    get_output=True,
                    print_output=False,
                    suppress_errors=True,
                )
                is_present = cc_image in out
            except Exception as e:
                dtslogger.debug("An exception occurred:\n" + pretty_exc(e, 4))
            if not is_present or parsed.force_pull:
                # try to pull the image
                dtslogger.info(f'Pulling image "{cc_image}"...')
                # noinspection PyBroadException
                try:
                    _run_cmd(
                        ["docker", "-H=%s" % parsed.machine, "pull", cc_image],
                        get_output=True,
                        print_output=True,
                        suppress_errors=True,
                    )
                except Exception as e:
                    dtslogger.warning(
                        f'An error occurred while pulling the image "{cc_image}", maybe the image does not exist'
                    )
                    dtslogger.debug("An exception occurred:\n" + pretty_exc(e, 4))
            else:
                dtslogger.info(
                    "Found an image with the same name. Using it. User --force-pull to force a new pull."
                )

        # cmd option
        if parsed.cmd and parsed.launcher:
            raise ValueError("You cannot use the option --launcher together with --cmd.")
        if parsed.launcher:
            parsed.cmd = LAUNCHER_FMT % parsed.launcher

        cc_command: List[str] = [] if not parsed.cmd else [parsed.cmd]
        cc_command_arguments = (
            [] if not container_cmd_arguments else
            (["--"] if not cc_command else []) + container_cmd_arguments
        )

        # environment
        if parsed.machine == DEFAULT_MACHINE and not parsed.no_impersonate:
            host_uid: int = os.getuid()
            dtslogger.info(f"Impersonating host user with UID {host_uid}")
            # NOTE: it is important to leave the container user's GID so that he can access his old files
            cc_environment["IMPERSONATE_UID"] = str(host_uid)

        # docker arguments
        cc_remove: bool = False
        cc_detach: bool = False
        cc_docker_args: List[str] = parsed.docker_args or []

        if (not parsed.no_rm) or (not parsed.detach):
            cc_remove = True
        if parsed.detach:
            cc_detach = True

        # add container name to docker args
        cc_name: str = parsed.name

        # escape spaces in arguments
        cc_docker_args = [a.replace(" ", "\\ ") for a in cc_docker_args]

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
                cmd = (f"rsync --archive --delete --copy-links --chown={REMOTE_USER}:{REMOTE_GROUP} "
                       f"\"{project_path}\" \"{remote_path}\"")
                _run_cmd(cmd, shell=True)
            dtslogger.info(f"Code synced!")

        # run
        if parsed.configuration is None:
            # use docker CLI directly
            exitcode = _run_cmd(
                [parsed.runtime, "-H=%s" % parsed.machine, "run", "-it"]
                + [f"--net={cc_network_mode}"]
                + [f"-e={k}={v}" for k, v in cc_environment.items()]
                + [f"-v={src}:{dst}:{mode}" for src, dst, mode in cc_mountpoints]
                + (["--rm"] if cc_remove else [])
                + (["-d"] if cc_detach else [])
                + [f"--name={cc_name}"]
                + cc_docker_args
                + [cc_image]
                + cc_command
                + cc_command_arguments,
                suppress_errors=True,
                return_exitcode=True,
            )
            dtslogger.debug(f"Command exited with exit code [{exitcode}].")
            if parsed.detach:
                dtslogger.info("Your container is running in detached mode!")

        else:
            # use a temporary docker-compose file instead
            assert len(cc_docker_args) == 0

            # load configuration
            container_configurations: LayerContainers = project.layers.containers
            try:
                base_cc: ContainerConfiguration = container_configurations[parsed.configuration]
            except KeyError:
                dtslogger.error(f"Container configuration '{parsed.configuration}' not found in project. "
                                f"Valid container configurations are: {list(container_configurations.keys())}")
                exit(1)
            # create docker-compose configuration
            docker_compose = args_to_docker_compose(
                cc_image,
                cc_name,
                cc_network_mode,
                cc_environment,
                cc_mountpoints,
                cc_command,
                cc_command_arguments,
                base_cc
            )
            # write temporary docker-compose.yaml file and run it
            with tempfile.NamedTemporaryFile(mode="w", delete=True) as f:
                # write docker-compose file
                yaml.dump(docker_compose, f)
                f.flush()
                # run docker-compose
                dtslogger.info("Running container using docker-compose...")
                dtslogger.debug(f"Using docker-compose file [{f.name}] with configuration:\n"
                                f"{pretty_yaml(docker_compose, indent=4)}")
                # run docker-compose
                exitcode = _run_cmd(
                    [
                        "docker", f"-H={parsed.machine}", "compose",
                        "-f", f.name,
                        "-p", f"dts-devel-run-{random_string(4)}",
                        "up",
                        "--exit-code-from", cc_name,
                        "--abort-on-container-exit",
                    ]
                    + (["-d"] if cc_detach else []),
                    suppress_errors=True,
                    return_exitcode=True,
                )
                dtslogger.debug(f"Docker-compose exited with exit code [{exitcode}].")

    @staticmethod
    def complete(shell, word, line):
        return []


def args_to_docker_compose(
        image: str,
        cc_name: str,
        cc_network_mode: str,
        cc_environment: Dict[str, str],
        cc_mountpoints: List[Tuple[str, str, str]],
        cc_command: List[str],
        cc_command_arguments: List[str],
        base_cc: ContainerConfiguration
) -> dict:
    runtime_cc = {
        "image": image,
        "network_mode": cc_network_mode,
        "environment": cc_environment,
        "volumes": [f"{src}:{dst}:{mode}" for src, dst, mode in cc_mountpoints],
        "command": cc_command + cc_command_arguments,
        "stdin_open": True,
        "tty": True,
    }
    cfg = {
        "services": {
            cc_name: merge_docker_compose_services(base_cc.service, runtime_cc)
        },
    }
    return cfg


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
