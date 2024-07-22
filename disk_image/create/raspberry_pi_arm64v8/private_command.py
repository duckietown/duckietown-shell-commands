from types import SimpleNamespace
from typing import List, Optional

from dt_shell import DTCommandAbs, dtslogger, DTShell, __version__ as shell_version

import argparse
import pathlib
import json
import os
import shutil
import subprocess
import time
import docker
import socket
import getpass
from datetime import datetime

from utils.cli_utils import ask_confirmation
from utils.misc_utils import human_time

from disk_image.create.constants import (
    PARTITION_MOUNTPOINT,
    FILE_PLACEHOLDER_SIGNATURE,
    TMP_WORKDIR,
    DISK_IMAGE_STATS_LOCATION,
    DOCKER_IMAGE_TEMPLATE,
    DATA_STORAGE_DISK_IMAGE_DIR,
)

from disk_image.create.utils import (
    VirtualSDCard,
    check_cli_tools,
    pull_docker_image,
    disk_template_partitions,
    disk_template_objects,
    find_placeholders_on_disk,
    get_file_first_line,
    get_file_length,
    run_cmd,
    run_cmd_in_partition,
    validator_autoboot_stack,
    validator_yaml_syntax,
    transfer_file,
    replace_in_file,
    list_files,
    copy_file,
    get_validator_fcn,
)

MODULES_TO_LOAD = [
    {"owner": "duckietown", "module": "portainer"},
    {"owner": "duckietown", "module": "dt-kvstore", "tag": "v0.2.0-arm64v8"},
]
DEFAULT_STACK = "robot"

# NOTE: -----------------------------------
#   The input image is:
#       Raspberry Pi OS
#       date: 15mar2024
#       sha: 58a3ec57402c86332e67789a6b8f149aeeb4e7bb0a16c9388a66ea6e07012e45
#   The image was downloaded, flashed to an SD card and:
#       - cmd: `rfkill unblock wlan`
#       - cmd: `sudo apt update`
#       - cmd: `sudo apt full-upgrade -y`
#       - cmd: `sudo apt install docker.io docker-compose inotify-tools emacs i2c-tools libraspberrypi-bin raspi-config sysprof`
#       - cmd: `sudo apt autoremove`
#       - cmd: `exit`
#       - re-login (let's history settle)
#       - cmd: `rm ~/.bash_history`
#   SD card was then dumped into an .img file and uploaded to S3
# -----------------------------------------

DISK_IMAGE_PARTITION_TABLE = {"bootfs": 1, "rootfs": 2, "configfs": 3}
DISK_IMAGE_PARTITION_MOUNTPOINT = {"bootfs": "/boot", "rootfs": "/", "configfs": "/config"}
AVAILABLE_STACKS_DIR = "/data/stacks/available"
ROOT_PARTITION = "rootfs"
CONFIG_PARTITION = "configfs"
DEFAULT_HOSTNAME = "robot"
DEFAULT_COUNTRY = "US"
DISK_IMAGE_SIZE_GB = 6
DISK_IMAGE_VERSION = "4.0.0"
PLACEHOLDERS_VERSION = "2.0"
OS_VERSION = "01jul2024"
DEVICE_ARCH = "arm64v8"
DEFAULT_DOCKER_REGISTRY = "docker.io"
DISK_IMAGE_NAME = f"raspios-bookworm-lite-v{OS_VERSION}-{DEVICE_ARCH}"
INPUT_DISK_IMAGE_URL = (
    f"https://duckietown-public-storage.s3.amazonaws.com/disk_image/disk_template/"
    f"{DISK_IMAGE_NAME}.zip"
)
TEMPLATE_FILE_VALIDATOR = {
    f"{ROOT_PARTITION}:/data/stacks/available/*.yaml":
        lambda *a, **kwa: validator_autoboot_stack(*a, **kwa, modules=MODULES_TO_LOAD, stack=DEFAULT_STACK),
    f"{ROOT_PARTITION}:/data/config/calibrations/*/default.yaml":
        lambda *a, **kwa: validator_yaml_syntax(*a, **kwa),
}
COMMAND_DIR = os.path.dirname(os.path.abspath(__file__))
DISK_TEMPLATE_DIR = os.path.join(COMMAND_DIR, "disk_template")
STACKS_DIR = os.path.join(COMMAND_DIR, "..", "..", "..", "stack", "stacks", DEFAULT_STACK)
SUPPORTED_STEPS: List[Optional[str]] = [
    "download",
    "create",
    "mount",
    "resize",
    "partition",
    "upgrade",
    "docker",
    "setup",
    "finalize",
    "unmount",
    "compress",
]
MANDATORY_STEPS = ["create", "mount", "unmount"]

APT_PACKAGES_TO_INSTALL = [
    "netplan.io",
]

APT_PACKAGES_TO_HOLD = [
    # list here packages that cannot be updated through `chroot`
    # "initramfs-tools"
]


class DTCommand(DTCommandAbs):

    help = "Prepares an .img disk file for a Raspberry Pi"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parser = argparse.ArgumentParser()
        # define parser arguments
        parser.add_argument(
            "--steps",
            type=str,
            default=",".join(SUPPORTED_STEPS),
            help="List of steps to perform (comma-separated)",
        )
        parser.add_argument(
            "--no-steps", type=str, default="", help="List of steps to skip (comma-separated)"
        )
        parser.add_argument(
            "-o", "--output", type=str, default=None, help="The destination directory for the output files"
        )
        parser.add_argument(
            "--no-cache",
            default=False,
            action="store_true",
            help="Whether to use previously downloaded base ISO image/zip archive (download step)",
        )
        parser.add_argument(
            "--workdir", type=str, default=TMP_WORKDIR, help="(Optional) temporary working directory to use"
        )
        parser.add_argument(
            "--cache-target",
            type=str,
            default=None,
            help="Target (cached) step to start from",
        )
        parser.add_argument(
            "--cache-record",
            type=str,
            default=None,
            help="Step to cache",
        )
        parser.add_argument(
            "--continue",
            dest="do_continue",
            default=False,
            action="store_true",
            help="Continue with the current artefact, do not overwrite (experts only)",
        )
        parser.add_argument(
            "--fast-compression",
            default=False,
            action="store_true",
            help="Use fast ZIP compression",
        )
        parser.add_argument(
            "--push",
            default=False,
            action="store_true",
            help="Whether to push the final compressed image to the Duckietown Cloud Storage",
        )
        # parse arguments
        parsed = parser.parse_args(args=args)
        stime = time.time()
        # check given steps
        f = lambda s: len(s) > 0
        parsed.steps = parsed.steps.split(",")
        parsed.steps = list(filter(f, parsed.steps))
        non_supported_steps = set(parsed.steps).difference(set(SUPPORTED_STEPS))
        if len(non_supported_steps):
            dtslogger.error(f"These steps are not supported: {non_supported_steps}")
            return
        # check given steps (to skip)
        parsed.no_steps = parsed.no_steps.split(",")
        parsed.no_steps = list(filter(f, parsed.no_steps))
        non_supported_steps = set(parsed.no_steps).difference(set(SUPPORTED_STEPS))
        if len(non_supported_steps):
            dtslogger.error(f"These steps are not supported: {non_supported_steps}")
            return
        # remove skipped steps
        if len(parsed.no_steps) > 0:
            skipped = set(parsed.steps).intersection(set(parsed.no_steps))
            parsed.steps = set(parsed.steps).difference(skipped)
            dtslogger.info(f"Skipping steps: [{', '.join(skipped)}]")
        # check steps caching
        if parsed.cache_target not in [None] + SUPPORTED_STEPS:
            dtslogger.error(f"Unknown step `{parsed.cache_target}`")
            return
        if parsed.cache_record not in [None] + SUPPORTED_STEPS:
            dtslogger.error(f"Unknown step `{parsed.cache_record}`")
            return
        # check dependencies
        check_cli_tools()
        # check if the output directory exists, create it if it does not
        if parsed.output is None:
            parsed.output = os.getcwd()
        if not os.path.exists(parsed.output):
            os.makedirs(parsed.output)
        # define output file template
        in_file_path = lambda ex: os.path.join(parsed.workdir, f"{DISK_IMAGE_NAME}.{ex}")
        input_image_name = pathlib.Path(in_file_path("img")).stem
        output_image_name = input_image_name.replace(OS_VERSION, DISK_IMAGE_VERSION)
        out_file_name = lambda ex: f"dt-{output_image_name}.{ex}"
        out_file_path = lambda ex: os.path.join(parsed.output, out_file_name(ex))
        cached_step_file_path = lambda step, ex: os.path.join(
            parsed.output, "cache", out_file_name(ex) + f".{step}"
        )
        # get version
        distro: str = shell.profile.distro.name
        # create a virtual SD card object
        sd_card = VirtualSDCard(out_file_path("img"), DISK_IMAGE_PARTITION_TABLE)
        # this is the surgey plan that will be performed by the init_sd_card command
        surgery_plan = []
        # define disk image origin
        disk_image_origin = in_file_path("img")
        using_cached_step = False
        # this holds the stats that will be stored in /data/stats/disk_image/build.json
        stats = {
            "steps": {step: bool(step in parsed.steps) for step in SUPPORTED_STEPS},
            "version": DISK_IMAGE_VERSION,
            "input_name": input_image_name,
            "input_url": INPUT_DISK_IMAGE_URL,
            "base_type": "Raspberry Pi OS",
            "base_version": OS_VERSION,
            "environment": {
                "hostname": socket.gethostname(),
                "user": getpass.getuser(),
                "shell_version": shell_version,
                "commands_version": shell.profile.distro.branch,
            },
            "modules": [
                DOCKER_IMAGE_TEMPLATE(
                    owner=module["owner"],
                    module=module["module"],
                    version=distro,
                    tag=module["tag"] if "tag" in module else None,
                    arch=DEVICE_ARCH,
                )
                for module in MODULES_TO_LOAD
            ],
            "template": {"directories": [], "files": []},
            "disk_size_gb": DISK_IMAGE_SIZE_GB,
            "stamp": time.time(),
            "stamp_human": datetime.now().isoformat(),
        }

        # create caching function
        def cache_step(step):
            if step != parsed.cache_record:
                return
            # cache step
            dtslogger.info(f"Caching step '{step}'...")
            cache_file_path = cached_step_file_path(step, "img")
            copy_file(out_file_path("img"), cache_file_path)
            dtslogger.info(f"Step '{step}' cached.")

        # use cached step
        if parsed.cache_target is not None:
            disk_image_origin = cached_step_file_path(parsed.cache_target, "img")
            if not os.path.isfile(disk_image_origin):
                dtslogger.error(f"No cached artifact found for step `{parsed.cache_target}`")
                return
            for step in SUPPORTED_STEPS[: SUPPORTED_STEPS.index(parsed.cache_target) + 1]:
                if step in MANDATORY_STEPS:
                    continue
                if step in parsed.steps:
                    parsed.steps.remove(step)
            using_cached_step = True

        # ---
        print()
        dtslogger.info(f"Steps to perform: {[s for s in SUPPORTED_STEPS if s in parsed.steps]}")
        #
        # STEPS:
        #
        # ------>
        # Step: download
        if "download" in parsed.steps:
            dtslogger.info("Step BEGIN: download")
            # clear cache (if requested)
            if parsed.no_cache:
                dtslogger.info("Clearing cache")
                if os.path.exists(parsed.workdir):
                    if parsed.workdir != TMP_WORKDIR:
                        dtslogger.warn(
                            "A custom working directory is being used. The flag "
                            "--no-cache does not have an effect in this case."
                        )
                    else:
                        shutil.rmtree(parsed.workdir)
            # create temporary dir
            run_cmd(["mkdir", "-p", parsed.workdir])
            # download zip (if necessary)
            dtslogger.info("Looking for ZIP image file...")
            if not os.path.isfile(in_file_path("zip")):
                dtslogger.info("Downloading ZIP image...")
                shell.include.data.get.command(
                    shell,
                    [],
                    parsed=SimpleNamespace(
                        file=[in_file_path("zip")],
                        object=[
                            os.path.join(
                                DATA_STORAGE_DISK_IMAGE_DIR, "disk_template", f"{DISK_IMAGE_NAME}.zip"
                            )
                        ],
                        space="public",
                    ),
                )
            else:
                dtslogger.info(f"Reusing cached ZIP image file [{in_file_path('zip')}].")
            # unzip (if necessary)
            if not os.path.isfile(in_file_path("img")):
                dtslogger.info("Extracting ZIP image...")
                try:
                    run_cmd(["unzip", in_file_path("zip"), "-d", parsed.workdir])
                except KeyboardInterrupt as e:
                    dtslogger.info("Cleaning up...")
                    run_cmd(["rm", "-f", in_file_path("img")])
                    raise e
            else:
                dtslogger.info(f"Reusing cached DISK image file [{in_file_path('img')}].")
            # ---
            cache_step("download")
            dtslogger.info("Step END: download\n")
        # Step: download
        # <------
        #
        # ------>
        # Step: create
        if "create" in parsed.steps:
            dtslogger.info("Step BEGIN: create")
            # check if the destination image already exists
            if os.path.exists(out_file_path("img")):
                msg = (
                    f"The destination file {out_file_path('img')} already exists. "
                    f"If you proceed, the file will be overwritten."
                )
                granted = ask_confirmation(msg)
                if not granted:
                    dtslogger.info("Aborting.")
                    return
            # create empty disk image
            if not using_cached_step:
                dtslogger.info(f"Creating empty disk image [{out_file_path('img')}]")
                run_cmd(
                    [
                        "dd",
                        "if=/dev/zero",
                        f"of={out_file_path('img')}",
                        f"bs={1024 * 1024}",
                        f"count={1024 * DISK_IMAGE_SIZE_GB}",
                    ]
                )
                dtslogger.info("Empty disk image created!")
            # make copy of the disk image
            dtslogger.info(f"Copying [{disk_image_origin}] -> [{out_file_path('img')}]")
            run_cmd(
                [
                    "dd",
                    f"if={disk_image_origin}",
                    f"of={out_file_path('img')}",
                    f"bs={1024 * 1024}",
                    "" if using_cached_step else "conv=notrunc",
                ]
            )
            # flush buffer
            dtslogger.info("Flushing I/O buffer...")
            run_cmd(["sync"])
            # ---
            cache_step("create")
            dtslogger.info("Step END: create\n")
        # Step: create
        # <------
        #
        # ------>
        # Step: mount
        if "mount" in parsed.steps:
            dtslogger.info("Step BEGIN: mount")
            # check if the destination image is already mounted
            loopdev = VirtualSDCard.find_loopdev(out_file_path("img"))
            sd_card.set_loopdev(loopdev)
            if loopdev:
                dtslogger.warn(
                    f"The destination file {out_file_path('img')} already exists "
                    f"and is mounted to {sd_card.loopdev}, skipping the 'mount' step."
                )
            else:
                # mount disk image
                dtslogger.info(f"Mounting {out_file_path('img')}...")
                sd_card.mount()
                dtslogger.info(f"Disk {out_file_path('img')} successfully mounted " f"on {sd_card.loopdev}")
            # ---
            cache_step("mount")
            dtslogger.info("Step END: mount\n")
        # Step: mount
        # <------
        #
        # ------>
        # Step: resize
        if "resize" in parsed.steps:
            dtslogger.info("Step BEGIN: resize")
            # make sure that the disk is mounted
            if not sd_card.is_mounted():
                dtslogger.error(f"The disk {out_file_path('img')} is not mounted.")
                return
            # get root partition id
            root_device = sd_card.partition_device(ROOT_PARTITION)
            # resize root partition to take the entire disk
            run_cmd(
                [
                    "sudo",
                    "parted",
                    "-s",
                    sd_card.loopdev,
                    "resizepart",
                    str(DISK_IMAGE_PARTITION_TABLE[ROOT_PARTITION]),
                    "100%",
                ]
            )
            # force driver to reload file size
            run_cmd(["sudo", "losetup", "-c", sd_card.loopdev])
            # show info about disk
            dtslogger.debug("\n" + run_cmd(["sudo", "fdisk", "-l", sd_card.loopdev], True))
            # fix file system
            run_cmd(["sudo", "e2fsck", "-y", "-f", root_device])
            # resize file system
            run_cmd(["sudo", "resize2fs", root_device])
            # ---
            cache_step("resize")
            dtslogger.info("Step END: resize\n")
        # Step: resize
        # <------
        #
        # ------>
        # Step: partition
        if "partition" in parsed.steps:
            dtslogger.info("Step BEGIN: partition")
            # make sure that the disk is mounted
            if not sd_card.is_mounted():
                dtslogger.error(f"The disk {out_file_path('img')} is not mounted.")
                return
            # get config partition id
            config_device = sd_card.partition_device(CONFIG_PARTITION)
            # create new partition
            run_cmd(
                "(" +
                # Add a new partition
                "echo n;" +
                # Primary partition
                "echo p;" +
                # Partition number
                "echo 3;" +
                # First sector (Accept default: 2048)
                "echo ;" +
                # Last sector (Accept default: 8191)
                "echo ;" +
                # Change partition type
                "echo t;" +
                # Partition number
                "echo 3;" +
                # Partition type 'FAT32 (LBA)' is 0c
                "echo 0c;" +
                # Write changes
                "echo w;" +
                f") | sudo fdisk {sd_card.loopdev}",
                shell=True
            )
            # make file system (FAT32 and 4096 bytes of block size (needed for comfortable surgery))
            run_cmd(["sudo", "mkfs", "-t", "fat", "-F", "32", "-S", "4096", config_device])
            # label file system
            run_cmd(["sudo", "fatlabel", config_device, CONFIG_PARTITION])
            # force reload partitions
            run_cmd(["sudo", "partprobe"])
            # show info about disk
            dtslogger.debug("\n" + run_cmd(["sudo", "fdisk", "-l", sd_card.loopdev], True))
            # ---
            cache_step("partition")
            dtslogger.info("Step END: partition\n")
        # Step: partition
        # <------
        #
        # ------>
        # Step: upgrade
        if "upgrade" in parsed.steps:
            dtslogger.info("Step BEGIN: upgrade")
            # from this point on, if anything weird happens, unmount the disk
            try:
                # make sure that the disk is mounted
                if not sd_card.is_mounted():
                    dtslogger.error(f"The disk {out_file_path('img')} is not mounted.")
                    return
                # check if the root disk device exists
                root_partition_disk = sd_card.partition_device(ROOT_PARTITION)
                if not os.path.exists(root_partition_disk):
                    raise ValueError(f"Disk device {root_partition_disk} not found")
                # mount `root` partition
                sd_card.mount_partition(ROOT_PARTITION)
                # from this point on, if anything weird happens, unmount the `root` disk
                try:
                    # copy QEMU, resolvconf
                    _transfer_file(ROOT_PARTITION, ["usr", "bin", "qemu-aarch64-static"])
                    _transfer_file(ROOT_PARTITION, ["run", "systemd", "resolve", "stub-resolv.conf"])
                    # mount /dev from the host
                    _dev = os.path.join(PARTITION_MOUNTPOINT(ROOT_PARTITION), "dev")
                    run_cmd(["sudo", "mount", "--bind", "/dev", _dev])
                    # configure the kernel for QEMU
                    run_cmd(
                        [
                            "docker",
                            "run",
                            "--rm",
                            "--privileged",
                            "multiarch/qemu-user-static:register",
                            "--reset",
                        ]
                    )
                    # try running a simple echo from the new chroot, if an error occurs, we need
                    # to check the QEMU configuration
                    try:
                        output = run_cmd_in_partition(
                            ROOT_PARTITION, 'echo "Hello from an ARM chroot"', get_output=True
                        )
                        if "Exec format error" in output:
                            raise Exception("Exec format error")
                    except (BaseException, subprocess.CalledProcessError) as e:
                        dtslogger.error(
                            "An error occurred while trying to run an ARM binary "
                            "from the temporary chroot.\n"
                            "This usually indicates a misconfiguration of QEMU "
                            "on the host.\n"
                            "Please, make sure that you have the packages "
                            "'qemu-user-static' and 'binfmt-support' installed "
                            "via APT.\n\n"
                            "The full error is:\n\t%s" % str(e)
                        )
                        exit(2)
                    # compile list of packages to hold
                    to_hold = " ".join(APT_PACKAGES_TO_HOLD)
                    # from this point on, if anything weird happens, unmount the `root` disk
                    try:
                        # run full-upgrade on the new root
                        run_cmd_in_partition(
                            ROOT_PARTITION,
                            "apt update && "
                            + (f"apt-mark hold {to_hold}" if len(to_hold) else ":")
                            + " && "
                            + "apt --yes --force-yes --no-install-recommends"
                            ' -o Dpkg::Options::="--force-confdef"'
                            ' -o Dpkg::Options::="--force-confold"'
                            " full-upgrade && " + (f"apt-mark unhold {to_hold}" if len(to_hold) else ":"),
                        )
                        # install packages
                        if APT_PACKAGES_TO_INSTALL:
                            pkgs = " ".join(APT_PACKAGES_TO_INSTALL)
                            run_cmd_in_partition(
                                ROOT_PARTITION,
                                "DEBIAN_FRONTEND=noninteractive "
                                f"apt install --yes --force-yes --no-install-recommends {pkgs}",
                            )
                        # clean packages
                        run_cmd_in_partition(
                            ROOT_PARTITION,
                            f"apt autoremove --yes",
                        )                        
                    except Exception as e:
                        raise e
                    # unomunt bind /dev
                    run_cmd(["sudo", "umount", _dev])
                except Exception as e:
                    sd_card.umount_partition(ROOT_PARTITION)
                    raise e
                # unmount ROOT_PARTITION
                sd_card.umount_partition(ROOT_PARTITION)
                # ---
            except Exception as e:
                sd_card.umount()
                raise e
            # ---
            cache_step("upgrade")
            dtslogger.info("Step END: upgrade\n")
        # Step: upgrade
        # <------
        #
        # ------>
        # Step: docker
        if "docker" in parsed.steps:
            dtslogger.info("Step BEGIN: docker")
            # from this point on, if anything weird happens, unmount the disk
            try:
                # make sure that the disk is mounted
                if not sd_card.is_mounted():
                    dtslogger.error(f"The disk {out_file_path('img')} is not mounted.")
                    return
                # check if the corresponding disk device exists
                partition_disk = sd_card.partition_device(ROOT_PARTITION)
                if not os.path.exists(partition_disk):
                    raise ValueError(f"Disk device {partition_disk} not found")
                # mount device
                sd_card.mount_partition(ROOT_PARTITION)
                # get local docker client
                local_docker = docker.from_env()
                # pull dind image
                pull_docker_image(local_docker, "docker:20.10.5-dind")
                # run auxiliary Docker engine
                remote_docker_dir = os.path.join(PARTITION_MOUNTPOINT(ROOT_PARTITION), "var", "lib", "docker")
                remote_docker_engine_container = local_docker.containers.run(
                    image="docker:20.10.5-dind",
                    detach=True,
                    remove=True,
                    auto_remove=True,
                    publish_all_ports=True,
                    privileged=True,
                    name="dts-disk-image-aux-docker",
                    volumes={remote_docker_dir: {"bind": "/var/lib/docker", "mode": "rw"}},
                    entrypoint=["dockerd", "--host=tcp://0.0.0.0:2375", "--bridge=none"],
                )
                dtslogger.info("Waiting 20 seconds for DIND to start...")
                time.sleep(20)
                # get IP address of the container
                container_info = local_docker.api.inspect_container("dts-disk-image-aux-docker")
                container_ip = container_info["NetworkSettings"]["IPAddress"]
                # create remote docker client
                endpoint_url = f"tcp://{container_ip}:2375"
                dtslogger.info(f"DIND should now be up, using endpoint URL `{endpoint_url}`.")
                remote_docker = docker.DockerClient(base_url=endpoint_url)
                # from this point on, if anything weird happens, stop container and unmount disk
                try:
                    dtslogger.info("Transferring Docker images...")
                    # pull images inside the disk image
                    for module in MODULES_TO_LOAD:
                        image = DOCKER_IMAGE_TEMPLATE(
                            owner=module["owner"],
                            module=module["module"],
                            version=distro,
                            tag=module["tag"] if "tag" in module else None,
                            arch=DEVICE_ARCH,
                        )
                        pull_docker_image(remote_docker, image, platform="linux/arm64")
                    # ---
                    dtslogger.info("Docker images successfully transferred!")
                except Exception as e:
                    # unmount disk
                    sd_card.umount()
                    raise e
                finally:
                    # stop container
                    remote_docker_engine_container.stop()
                    # unmount partition
                    sd_card.umount_partition(ROOT_PARTITION)
                # ---
            except Exception as e:
                # unmount disk
                sd_card.umount()
                raise e
            # ---
            cache_step("docker")
            dtslogger.info("Step END: docker\n")
        # Step: docker
        # <------
        #
        # ------>
        # Step: setup
        if "setup" in parsed.steps:
            dtslogger.info("Step BEGIN: setup")
            # from this point on, if anything weird happens, unmount the disk
            try:
                # make sure that the disk is mounted
                if not sd_card.is_mounted():
                    dtslogger.error(f"The disk {out_file_path('img')} is not mounted.")
                    return
                # find partitions to update
                partitions = disk_template_partitions(DISK_TEMPLATE_DIR)
                # put template objects inside the stats object
                for partition in partitions:
                    stats["template"]["directories"] = list(
                        map(
                            lambda u: u["relative"],
                            disk_template_objects(DISK_TEMPLATE_DIR, partition, "directory"),
                        )
                    )
                    stats["template"]["files"] = list(
                        map(
                            lambda u: u["relative"],
                            disk_template_objects(DISK_TEMPLATE_DIR, partition, "file"),
                        )
                    )
                # make sure that all the partitions are there
                for partition in partitions:
                    # check if the partition defined in the disk_template dir exists
                    if partition not in DISK_IMAGE_PARTITION_TABLE:
                        raise ValueError(f"Partition {partition} not declared in partition table")
                    # check if the corresponding disk device exists
                    partition_disk = sd_card.partition_device(partition)
                    if not os.path.exists(partition_disk):
                        raise ValueError(f"Disk device {partition_disk} not found")
                    # mount device
                    sd_card.mount_partition(partition)
                    # from this point on, if anything weird happens, unmount the disk
                    try:
                        dtslogger.info(f'Updating partition "{partition}":')
                        # create directory structure from disk template
                        dirs = disk_template_objects(DISK_TEMPLATE_DIR, partition, "directory")
                        for update in dirs:
                            dtslogger.info(f"- Creating directory [{update['relative']}]")
                            # create destination
                            run_cmd(["sudo", "mkdir", "-p", update["destination"]])
                        # copy stacks (root only)
                        if partition == ROOT_PARTITION:
                            for stack in list_files(STACKS_DIR, "yaml"):
                                origin = os.path.join(STACKS_DIR, stack)
                                destination = os.path.join(
                                    PARTITION_MOUNTPOINT(partition), AVAILABLE_STACKS_DIR.lstrip("/"), stack
                                )
                                relative = os.path.join(AVAILABLE_STACKS_DIR, stack)
                                # validate file
                                validator = _get_validator_fcn(partition, relative)
                                if validator:
                                    dtslogger.debug(f"Validating file {relative}...")
                                    validator(shell, origin, relative, arch=DEVICE_ARCH)
                                # create or modify file
                                effect = "MODIFY" if os.path.exists(destination) else "NEW"
                                dtslogger.info(f"- Updating file ({effect}) [{relative}]")
                                # copy new file
                                run_cmd(["sudo", "cp", origin, destination])
                                # add architecture as default value in the stack file
                                dtslogger.debug(
                                    "- Replacing '{ARCH}' with '{ARCH:-%s}' in %s"
                                    % (DEVICE_ARCH, destination)
                                )
                                replace_in_file("{ARCH}", "{ARCH:-%s}" %
                                                DEVICE_ARCH, destination)
                                # add registry as default value in the stack file
                                dtslogger.debug(
                                    "- Replacing '{REGISTRY}' with '{REGISTRY:-%s}' in %s"
                                    % (DEFAULT_DOCKER_REGISTRY, destination)
                                )
                                replace_in_file("{REGISTRY}", "{REGISTRY:-%s}" %
                                                DEFAULT_DOCKER_REGISTRY, destination)
                        # apply changes from disk_template
                        files = disk_template_objects(DISK_TEMPLATE_DIR, partition, "file")
                        for update in files:
                            # validate file
                            validator = _get_validator_fcn(partition, update["relative"])
                            if validator:
                                dtslogger.debug(f"Validating file {update['relative']}...")
                                validator(shell, update["origin"], update["relative"], arch=DEVICE_ARCH)
                            # create or modify file
                            effect = "MODIFY" if os.path.exists(update["destination"]) else "NEW"
                            dtslogger.info(f"- Updating file ({effect}) [{update['relative']}]")
                            # copy new file
                            run_cmd(["sudo", "cp", update["origin"], update["destination"]])
                            # get first line of file
                            file_first_line = get_file_first_line(update["destination"])
                            # only files containing a known placeholder will be part of the surgery
                            if file_first_line.startswith(FILE_PLACEHOLDER_SIGNATURE):
                                placeholder = file_first_line[len(FILE_PLACEHOLDER_SIGNATURE) :]
                                # get stats about file
                                real_bytes, max_bytes = get_file_length(update["destination"])
                                # saturate file so that it occupies the entire pagefile
                                run_cmd(["sudo", "truncate", f"--size={max_bytes}", update["destination"]])
                                # store preliminary info about the surgery
                                surgery_plan.append(
                                    {
                                        "partition": partition,
                                        "partition_id": DISK_IMAGE_PARTITION_TABLE[partition],
                                        "mountpoint": DISK_IMAGE_PARTITION_MOUNTPOINT[partition],
                                        "path": update["relative"],
                                        "placeholder": placeholder,
                                        "offset_bytes": None,
                                        "used_bytes": real_bytes,
                                        "length_bytes": max_bytes,
                                    }
                                )
                        # special handling of the ROOT partition
                        if partition == ROOT_PARTITION:
                            # store stats before closing the [root] partition
                            stats_filepath = os.path.join(
                                PARTITION_MOUNTPOINT(partition), DISK_IMAGE_STATS_LOCATION
                            )
                            with open(out_file_path("stats"), "wt") as fout:
                                json.dump(stats, fout, indent=4, sort_keys=True)
                            run_cmd(["sudo", "cp", out_file_path("stats"), stats_filepath])
                            # setup services
                            run_cmd_in_partition(
                                ROOT_PARTITION,
                                "ln"
                                " -s -f"
                                " /etc/systemd/system/dt_init.service"
                                " /etc/systemd/system/multi-user.target.wants/dt_init.service",
                            )
                        # flush I/O buffer
                        dtslogger.info("Flushing I/O buffer...")
                        run_cmd(["sync"])
                        # ---
                        dtslogger.info(f"Partition {partition} updated!")
                    except Exception as e:
                        sd_card.umount_partition(partition)
                        raise e
                    # umount partition
                    sd_card.umount_partition(partition)
                # ---
            except Exception as e:
                sd_card.umount()
                raise e
            # finalize surgery plan
            dtslogger.info("Locating files for surgery in the disk image...")
            placeholders = find_placeholders_on_disk(out_file_path("img"))
            for i in range(len(surgery_plan)):
                full_placeholder = f"{FILE_PLACEHOLDER_SIGNATURE}{surgery_plan[i]['placeholder']}"
                # check if the placeholder was found
                if full_placeholder not in placeholders:
                    raise ValueError(
                        f'The string "{full_placeholder}" '
                        f"was not found in the disk image {out_file_path('img')}"
                    )
                # update surgery plan
                surgery_plan[i]["offset_bytes"] = placeholders[full_placeholder]
            dtslogger.info("All files located successfully!")

            # perform surgery with empty data, the placeholders will remain valid to be used again but the SD card
            # will be usable without another surgery as long as the robot provides an initialization procedure
            # compile data used to format placeholders
            surgery_data = {
                "hostname": DEFAULT_HOSTNAME,
                "country": DEFAULT_COUNTRY,
                "token": "",
                "robot_type": "",
                "robot_configuration": "",
                "robot_distro": shell.profile.distro.name,
                "netplan_wifi_networks": "{}",
                "sanitize_files": None,
                "stats": "",
            }
            # compile list of files to sanitize at first boot
            sanitize = map(lambda _s: os.path.join(_s["mountpoint"], _s["path"].lstrip("/")), surgery_plan)
            surgery_data["sanitize_files"] = "\n".join(map(lambda _f: f'dt-sanitize-file "{_f}"', sanitize))
            # get disk image placeholders
            placeholders_dir = os.path.join(COMMAND_DIR, "..", "..", "..", "init_sd_card", "placeholders",
                                            f"v{PLACEHOLDERS_VERSION}")
            # perform surgery
            dtslogger.info("Performing default data surgery on the image disk...")
            for surgery_bit in surgery_plan:
                dtslogger.info("Performing surgery on [{partition}]:{path}.".format(**surgery_bit))
                # get placeholder info
                placeholder = surgery_bit["placeholder"]
                placeholder_file = os.path.join(placeholders_dir, placeholder)
                # make sure that the placeholder exists
                if not os.path.isfile(placeholder_file):
                    print(placeholder_file)
                    dtslogger.error(f"The placeholder {placeholder} is not recognized.")
                    raise FileNotFoundError(placeholder_file)
                # load placeholder file format
                with open(placeholder_file, "rt") as fin:
                    placeholder_fmt = fin.read()
                # create real (unmasked) content
                content = placeholder_fmt.format(**surgery_data).encode()
                used_bytes = len(content)
                block_size = surgery_bit["length_bytes"]
                block_offset = surgery_bit["offset_bytes"]
                # make sure the content does not exceed the block size
                if used_bytes > block_size:
                    dtslogger.error(
                        "File [{partition}]:{path} exceeding ".format(**surgery_bit)
                        + f"budget of {block_size} bytes (by {used_bytes - block_size} bytes)."
                    )
                    exit(7)
                # create masked content (content is padded with new lines)
                masked_content = content + b"\n" * (block_size - used_bytes)
                # debug only
                assert len(masked_content) == block_size
                block_usage = int(100 * (used_bytes / float(block_size)))
                dtslogger.debug(
                    "Injecting {}/{} bytes ({}%) ".format(used_bytes, block_size, block_usage)
                    + "into [{partition}]:{path}.".format(**surgery_bit)
                )
                # apply change
                dd_cmd = [
                    "dd",
                    "of={}".format(out_file_path("img")),
                    "bs=1",
                    "count={}".format(block_size),
                    "seek={}".format(block_offset),
                    "conv=notrunc",
                ]
                # launch dd
                dd = subprocess.Popen(dd_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
                dtslogger.debug(f"$ {dd_cmd}")
                # write
                dd.stdin.write(masked_content)
                dd.stdin.flush()
                dd.stdin.close()
                dd.wait()
            dtslogger.info("Surgery completed!")
            # ---
            cache_step("setup")
            dtslogger.info("Step END: setup\n")
        # Step: setup
        # <------
        #
        # ------>
        # Step: finalize
        if "finalize" in parsed.steps:
            dtslogger.info("Step BEGIN: finalize")
            # compute image sha256
            dtslogger.info(f"Computing SHA256 checksum of {out_file_path('img')}...")
            disk_image_sha256 = sd_card.disk_image_sha()
            dtslogger.info(f"SHA256: {disk_image_sha256}")
            # store surgery plan and other info
            dtslogger.info(f"Storing metadata in {out_file_path('json')}...")
            metadata = {
                "version": DISK_IMAGE_VERSION,
                "disk_image": os.path.basename(out_file_path("img")),
                "sha256": disk_image_sha256,
                "distro": shell.profile.distro.name,
                "surgery_plan": surgery_plan,
            }
            with open(out_file_path("json"), "wt") as fout:
                json.dump(metadata, fout, indent=4, sort_keys=True)
            dtslogger.info("Done!")
            # ---
            cache_step("finalize")
            dtslogger.info("Step END: finalize\n")
        # Step: finalize
        # <------
        #
        # ------>
        # Step: unmount
        if "unmount" in parsed.steps:
            dtslogger.info("Step BEGIN: unmount")
            sd_card.umount()
            cache_step("unmount")
            dtslogger.info("Step END: unmount\n")
        # Step: unmount
        # <------
        #
        # ------>
        # Step: compress
        if "compress" in parsed.steps:
            dtslogger.info("Step BEGIN: compress")
            dtslogger.info("Compressing disk image...")
            zip_cmd = ["zip", "-j"]
            if parsed.fast_compression:
                zip_cmd += ["-1"]
            zip_cmd += [out_file_path("zip"), out_file_path("img"), out_file_path("json")]
            run_cmd(zip_cmd)
            dtslogger.info("Done!")
            cache_step("compress")
            dtslogger.info("Step END: compress\n")
        # Step: compress
        # <------
        #
        # ------>
        # Step: push
        if parsed.push:
            if "compress" not in parsed.steps:
                dtslogger.warning("The step 'compress' was not performed. No artifacts to push.")
                return
            dtslogger.info("Step BEGIN: push")
            dtslogger.info("Pushing disk image...")
            shell.include.data.push.command(
                shell,
                [],
                parsed=SimpleNamespace(
                    file=[out_file_path("zip")],
                    object=[os.path.join(DATA_STORAGE_DISK_IMAGE_DIR, out_file_name("zip"))],
                    space="public",
                    compress=False
                ),
            )
            dtslogger.info("Done!")
            dtslogger.info("Step END: push\n")
        # Step: push
        # <------
        dtslogger.info(f"Completed in {human_time(time.time() - stime)}")

    @staticmethod
    def complete(shell, word, line):
        return []


def _get_validator_fcn(partition, path):
    return get_validator_fcn(TEMPLATE_FILE_VALIDATOR, partition, path)


def _transfer_file(partition, location):
    return transfer_file(DISK_TEMPLATE_DIR, partition, location)
