from types import SimpleNamespace

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
import fnmatch
import getpass
from datetime import datetime

from utils.cli_utils import ask_confirmation
from utils.duckietown_utils import get_distro_version

from disk_image.create.constants import \
    PARTITION_MOUNTPOINT, \
    FILE_PLACEHOLDER_SIGNATURE, \
    TMP_WORKDIR, \
    DISK_IMAGE_STATS_LOCATION, \
    DOCKER_IMAGE_TEMPLATE, \
    MODULES_TO_LOAD, \
    DATA_STORAGE_DISK_IMAGE_DIR

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
)

DISK_IMAGE_PARTITION_TABLE = {"HypriotOS": 1, "root": 2}
ROOT_PARTITION = "root"
DISK_IMAGE_SIZE_GB = 8
DISK_IMAGE_VERSION = "1.1"
HYPRIOTOS_VERSION = "1.11.1"
HYPRIOTOS_DISK_IMAGE_NAME = f"hypriotos-rpi-v{HYPRIOTOS_VERSION}"
INPUT_DISK_IMAGE_URL = (
    f"https://github.com/hypriot/image-builder-rpi/releases/download/"
    f"v{HYPRIOTOS_VERSION}/{HYPRIOTOS_DISK_IMAGE_NAME}.img.zip"
)
TEMPLATE_FILE_VALIDATOR = {
    "root:/data/config/autoboot/*.yaml": lambda *a, **kwa: validator_autoboot_stack(*a, **kwa),
    "root:/data/config/calibrations/*/default.yaml": lambda *a, **kwa: validator_yaml_syntax(*a, **kwa),
}
DISK_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "disk_template")
SUPPORTED_STEPS = [
    "download",
    "create",
    "mount",
    "resize",
    "upgrade",
    "docker",
    "setup",
    "finalize",
    "unmount",
    "compress",
]
MANDATORY_STEPS = [
    "create",
    "mount",
    "unmount"
]

APT_PACKAGES_TO_INSTALL = [
    'rsync',
    'libnss-mdns'
]

class DTCommand(DTCommandAbs):

    help = "Prepares an .img disk file for a Raspberry Pi"

    @staticmethod
    def command(shell: DTShell, args):
        parser = argparse.ArgumentParser()
        # define parser arguments
        parser.add_argument(
            "--steps",
            type=str,
            default=",".join(SUPPORTED_STEPS),
            help="List of steps to perform (comma-separated)",
        )
        parser.add_argument(
            "--no-steps",
            type=str,
            default="",
            help="List of steps to skip (comma-separated)",
        )
        parser.add_argument(
            "-o",
            "--output",
            type=str,
            default=None,
            help="The destination directory for the output file"
        )
        parser.add_argument(
            "--no-cache",
            default=False,
            action="store_true",
            help="Whether to use cached ISO image"
        )
        parser.add_argument(
            "--workdir",
            default=TMP_WORKDIR,
            type=str,
            help="(Optional) temporary working directory to use"
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
            "--push",
            default=False,
            action="store_true",
            help="Whether to push the final compressed image to the Duckietown Cloud Storage",
        )
        # parse arguments
        parsed = parser.parse_args(args=args)
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
            dtslogger.error(f'Unknown step `{parsed.cache_target}`')
            return
        if parsed.cache_record not in [None] + SUPPORTED_STEPS:
            dtslogger.error(f'Unknown step `{parsed.cache_record}`')
            return
        # check dependencies
        check_cli_tools()
        # check if the output directory exists, create it if it does not
        if parsed.output is None:
            parsed.output = os.getcwd()
        if not os.path.exists(parsed.output):
            os.makedirs(parsed.output)
        # define output file template
        in_file_path = lambda ex: os.path.join(parsed.workdir, f"{HYPRIOTOS_DISK_IMAGE_NAME}.{ex}")
        input_image_name = pathlib.Path(in_file_path("img")).stem
        output_image_name = input_image_name.replace(HYPRIOTOS_VERSION, DISK_IMAGE_VERSION)
        out_file_name = lambda ex: f"dt-{output_image_name}.{ex}"
        out_file_path = lambda ex: os.path.join(parsed.output, out_file_name(ex))
        cached_step_file_path = lambda step, ex: \
            os.path.join(parsed.output, 'cache', out_file_name(ex) + f'.{step}')
        # get version
        distro = get_distro_version(shell)
        # create a virtual SD card object
        sd_card = VirtualSDCard(out_file_path("img"), DISK_IMAGE_PARTITION_TABLE)
        # this is the surgey plan that will be performed by the init_sd_card command
        surgery_plan = []
        # define disk image origin (by default we use the official vanilla nVidia JetPack OS)
        disk_image_origin = in_file_path('img')
        using_cached_step = False
        # this holds the stats that will be stored in /data/stats/disk_image/build.json
        stats = {
            "steps": {step: bool(step in parsed.steps) for step in SUPPORTED_STEPS},
            "version": DISK_IMAGE_VERSION,
            "input_name": input_image_name,
            "input_url": INPUT_DISK_IMAGE_URL,
            "base_type": "HypriotOS",
            "base_version": HYPRIOTOS_VERSION,
            "environment": {
                "hostname": socket.gethostname(),
                "user": getpass.getuser(),
                "shell_version": shell_version,
                "commands_version": shell.get_commands_version(),
            },
            "modules": [
                DOCKER_IMAGE_TEMPLATE(
                    owner=module["owner"],
                    module=module["module"],
                    version=distro,
                    tag=module["tag"] if "tag" in module else None,
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
            cache_file_path = cached_step_file_path(step, 'img')
            _copy_file(out_file_path('img'), cache_file_path)
            dtslogger.info(f"Step '{step}' cached.")

        # use cached step
        if parsed.cache_target is not None:
            disk_image_origin = cached_step_file_path(parsed.cache_target, 'img')
            if not os.path.isfile(disk_image_origin):
                dtslogger.error(f'No cached artifact found for step `{parsed.cache_target}`')
                return
            for step in SUPPORTED_STEPS[:SUPPORTED_STEPS.index(parsed.cache_target)+1]:
                if step in MANDATORY_STEPS:
                    continue
                parsed.steps.remove(step)
            using_cached_step = True

        print()
        #
        # STEPS:
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
                try:
                    run_cmd(
                        [
                            "wget",
                            "--no-verbose",
                            "--show-progress",
                            "--continue",
                            "--output-document",
                            in_file_path("zip"),
                            INPUT_DISK_IMAGE_URL,
                        ]
                    )
                except KeyboardInterrupt as e:
                    dtslogger.info("Cleaning up...")
                    run_cmd(["rm", "-rf", in_file_path("zip")])
                    raise e
            else:
                dtslogger.info(f"Reusing cached ZIP image file [{in_file_path('zip')}].")
            # unzip (if necessary)
            if not os.path.isfile(in_file_path("img")):
                dtslogger.info("Extracting ZIP image...")
                try:
                    run_cmd(["unzip", in_file_path("zip"), "-d", parsed.workdir])
                except KeyboardInterrupt as e:
                    dtslogger.info("Cleaning up...")
                    run_cmd(["rm", "-rf", in_file_path("img")])
                    raise e
            else:
                dtslogger.info(f"Reusing cached DISK image file [{in_file_path('img')}].")
            # ---
            cache_step('download')
            dtslogger.info("Step END: download\n")
        # Step: download
        # <------
        #
        # STEPS:
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
                    "" if using_cached_step else "conv=notrunc"
                ]
            )
            # flush buffer
            dtslogger.info("Flushing I/O buffer...")
            run_cmd(["sync"])
            # ---
            cache_step('create')
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
            cache_step('mount')
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
            # get original disk identifier
            disk_identifier = sd_card.get_disk_identifier()
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
            run_cmd(["sudo", "e2fsck", "-f", root_device])
            # resize file system
            run_cmd(["sudo", "resize2fs", root_device])
            dtslogger.info("Waiting 5 seconds for changes to take effect...")
            time.sleep(5)
            # make sure that the changes had an effect
            assert sd_card.get_disk_identifier() != disk_identifier
            # restore disk identifier
            sd_card.set_disk_identifier(disk_identifier)
            assert sd_card.get_disk_identifier() == disk_identifier
            # ---
            cache_step('resize')
            dtslogger.info("Step END: resize\n")
        # Step: resize
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
                # check if the `root` disk device exists
                root_partition_disk = sd_card.partition_device(ROOT_PARTITION)
                if not os.path.exists(root_partition_disk):
                    raise ValueError(f"Disk device {root_partition_disk} not found")
                # check if the `HypriotOS` disk device exists
                hypriotos_partition_disk = sd_card.partition_device("HypriotOS")
                if not os.path.exists(hypriotos_partition_disk):
                    raise ValueError(f"Disk device {hypriotos_partition_disk} not found")
                # mount `root` partition
                sd_card.mount_partition(ROOT_PARTITION)
                # from this point on, if anything weird happens, unmount the `root` disk
                try:
                    # copy resolvconf
                    _rcf = os.path.join(PARTITION_MOUNTPOINT(ROOT_PARTITION), 'etc', 'resolv.conf')
                    run_cmd(["sudo", "rm", "-f", _rcf])
                    transfer_file(ROOT_PARTITION, ['etc', 'resolv.conf'])
                    # mount /dev from the host
                    _dev = os.path.join(PARTITION_MOUNTPOINT(ROOT_PARTITION), "dev")
                    run_cmd(["sudo", "mount", "--bind", "/dev", _dev])
                    # configure the kernel for QEMU
                    run_cmd([
                        "docker",
                        "run",
                        "--rm",
                        "--privileged",
                        "multiarch/qemu-user-static:register",
                        "--reset",
                    ])
                    # try running a simple echo from the new chroot, if an error occurs, we need
                    # to check the QEMU configuration
                    try:
                        output = run_cmd_in_partition(
                            ROOT_PARTITION, 'echo "Hello from an ARM chroot!"', get_output=True
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
                    # mount the partition HypriotOS as root:/boot
                    _boot = os.path.join(PARTITION_MOUNTPOINT(ROOT_PARTITION), "boot")
                    run_cmd(["sudo", "mount", "-t", "auto", hypriotos_partition_disk, _boot])
                    # from this point on, if anything weird happens, unmount the `root` disk
                    try:
                        # run full-upgrade on the new root
                        run_cmd_in_partition(
                            ROOT_PARTITION,
                            "apt update && "
                            "apt --yes --force-yes --no-install-recommends"
                            ' -o Dpkg::Options::="--force-confdef"'
                            ' -o Dpkg::Options::="--force-confold"'
                            " full-upgrade"
                        )
                        # install packages
                        if APT_PACKAGES_TO_INSTALL:
                            pkgs = " ".join(APT_PACKAGES_TO_INSTALL)
                            run_cmd_in_partition(
                                ROOT_PARTITION,
                                f"DEBIAN_FRONTEND=noninteractive "
                                f"apt install --yes --force-yes --no-install-recommends {pkgs}",
                            )
                        # upgrade libseccomp
                        # (see: https://github.com/duckietown/duckietown-shell-commands/issues/200)
                        transfer_file(ROOT_PARTITION, ["tmp", "libseccomp2_2.4.3-1+b1_armhf.deb"])
                        run_cmd_in_partition(
                            ROOT_PARTITION,
                            "dpkg -i /tmp/libseccomp2_2.4.3-1+b1_armhf.deb && "
                            "rm /tmp/libseccomp2_2.4.3-1+b1_armhf.deb"
                        )
                    except Exception as e:
                        run_cmd(["sudo", "umount", _boot])
                        raise e
                    # unomunt bind /dev
                    run_cmd(["sudo", "umount", _dev])
                    # unmount 'HypriotOS'
                    run_cmd(["sudo", "umount", _boot])
                except Exception as e:
                    sd_card.umount_partition(ROOT_PARTITION)
                    raise e
                # unmount 'root'
                sd_card.umount_partition(ROOT_PARTITION)
                # ---
            except Exception as e:
                sd_card.umount()
                raise e
            # ---
            cache_step('upgrade')
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
                pull_docker_image(local_docker, "docker:dind")
                # run auxiliary Docker engine
                remote_docker_dir = os.path.join(PARTITION_MOUNTPOINT(ROOT_PARTITION), "var", "lib", "docker")
                remote_docker_engine_container = local_docker.containers.run(
                    image="docker:dind",
                    detach=True,
                    auto_remove=True,
                    publish_all_ports=True,
                    privileged=True,
                    name="dts-disk-image-aux-docker",
                    volumes={remote_docker_dir: {"bind": "/var/lib/docker", "mode": "rw"}},
                    entrypoint=["dockerd", "--host=tcp://0.0.0.0:2375"],
                )
                time.sleep(2)
                # get IP address of the container
                container_info = local_docker.api.inspect_container("dts-disk-image-aux-docker")
                container_ip = container_info["NetworkSettings"]["IPAddress"]
                # create remote docker client
                time.sleep(2)
                remote_docker = docker.DockerClient(base_url=f"tcp://{container_ip}:2375")
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
                        )
                        pull_docker_image(remote_docker, image)
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
            cache_step('docker')
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
                        for update in disk_template_objects(DISK_TEMPLATE_DIR, partition, "directory"):
                            dtslogger.info(f"- Creating directory [{update['relative']}]")
                            # create destination
                            run_cmd(["sudo", "mkdir", "-p", update["destination"]])
                        # apply changes from disk_template
                        for update in disk_template_objects(DISK_TEMPLATE_DIR, partition, "file"):
                            # validate file
                            validator = _get_validator_fcn(partition, update["relative"])
                            if validator:
                                dtslogger.debug(f"Validating file {update['relative']}...")
                                validator(shell, update["origin"], update["relative"])
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
                                        "path": update["relative"],
                                        "placeholder": placeholder,
                                        "offset_bytes": None,
                                        "used_bytes": real_bytes,
                                        "length_bytes": max_bytes,
                                    }
                                )
                        # special handling of the ROOT partition
                        if partition == ROOT_PARTITION:
                            # store stats before closing the partition
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
                                " -s"
                                " /etc/systemd/system/dt_init.service"
                                " /etc/systemd/system/multi-user.target.wants/dt_init.service"
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
            dtslogger.info("Locating files for surgery in disk image...")
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
            # ---
            cache_step('setup')
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
                "surgery_plan": surgery_plan,
            }
            with open(out_file_path("json"), "wt") as fout:
                json.dump(metadata, fout, indent=4, sort_keys=True)
            dtslogger.info("Done!")
            # ---
            cache_step('finalize')
            dtslogger.info("Step END: finalize\n")
        # Step: finalize
        # <------
        #
        # ------>
        # Step: unmount
        if "unmount" in parsed.steps:
            dtslogger.info("Step BEGIN: unmount")
            sd_card.umount()
            cache_step('unmount')
            dtslogger.info("Step END: unmount\n")
        # Step: unmount
        # <------
        #
        # ------>
        # Step: compress
        if "compress" in parsed.steps:
            dtslogger.info("Step BEGIN: compress")
            dtslogger.info("Compressing disk image...")
            run_cmd(["zip", "-j", out_file_path("zip"), out_file_path("img"), out_file_path("json")])
            dtslogger.info("Done!")
            cache_step('compress')
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
                ),
            )
            dtslogger.info("Done!")
            dtslogger.info("Step END: push\n")
        # Step: push
        # <------

    @staticmethod
    def complete(shell, word, line):
        return []


def _get_validator_fcn(partition, path):
    key = f"{partition}:{path}"
    for _k, _f in TEMPLATE_FILE_VALIDATOR.items():
        if fnmatch.fnmatch(key, _k):
            return _f
    return None


def _copy_file(origin, destination):
    # create destination directory
    os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
    # make copy of the file
    dtslogger.info(f"Copying [{origin}] -> [{destination}]")
    run_cmd(["cp", origin, destination])


def transfer_file(partition, location):
    _local_filepath = os.path.join(DISK_TEMPLATE_DIR, partition, *location)
    _remote_filepath = os.path.join(PARTITION_MOUNTPOINT(partition), *location)
    run_cmd(["sudo", "cp", _local_filepath, _remote_filepath])
