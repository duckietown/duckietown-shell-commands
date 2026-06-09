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
import getpass
import platform
from datetime import datetime

from utils.cli_utils import ask_confirmation
from utils.docker_utils import DEFAULT_REGISTRY
from utils.duckietown_utils import get_distro
from utils.misc_utils import human_time
from disk_image.create.steps import step_docker, step_push

from disk_image.create.constants import (
    PARTITION_MOUNTPOINT,
    FILE_PLACEHOLDER_SIGNATURE,
    TMP_WORKDIR,
    DISK_IMAGE_STATS_LOCATION,
    DOCKER_IMAGE_TEMPLATE,
    MODULES_TO_LOAD,
    DATA_STORAGE_DISK_IMAGE_DIR,
    AUTOBOOT_STACKS_DIR,
)

from disk_image.create.utils import (
    VirtualSDCard,
    check_cli_tools,
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
    copy_file,
    get_validator_fcn,
)

# JetPack 6.2.1 partition table for Jetson Orin Nano
# Uses A/B redundancy scheme with kernel, recovery, and ESP partitions
DISK_IMAGE_PARTITION_TABLE = {
    "APP": 1,
    "A_kernel": 2,
    "A_kernel-dtb": 3,
    "A_reserved_on_user": 4,
    "B_kernel": 5,
    "B_kernel-dtb": 6,
    "B_reserved_on_user": 7,
    "recovery": 8,
    "recovery-dtb": 9,
    "esp": 10,
    "recovery_alt": 11,
    "recovery-dtb_alt": 12,
    "esp_alt": 13,
    "UDA": 14,
    "reserved": 15,
}
DISK_IMAGE_SIZE_GB = 20
DISK_IMAGE_VERSION = "1.3.1"
ROOT_PARTITION = "APP"
JETPACK_VERSION = "6.2.1-B"
DEVICE_ARCH = "arm64v8"
JETPACK_DISK_IMAGE_NAME = f"nvidia-jetpack-orin-v{JETPACK_VERSION}"
INPUT_DISK_IMAGE_URL = (
    f"https://duckietown-public-storage.s3.amazonaws.com/"
    f"disk_image/disk_template/{JETPACK_DISK_IMAGE_NAME}.zip"
)
TEMPLATE_FILE_VALIDATOR = {
    f"{ROOT_PARTITION}:/data/autoboot/*.yaml": lambda *a, **kwa: validator_autoboot_stack(*a, **kwa),
    f"{ROOT_PARTITION}:/data/config/calibrations/*/default.yaml": lambda *a, **kwa: validator_yaml_syntax(*a, **kwa),
}
COMMAND_DIR = os.path.dirname(os.path.abspath(__file__))
DISK_TEMPLATE_DIR = os.path.join(COMMAND_DIR, "disk_template")
NVIDIA_LICENSE_FILE = os.path.join(COMMAND_DIR, "nvidia-license.txt")

STACKS = ["robot/basics", "duckietown/duckiebot", "ros1/duckiebot"]
STACKS_BASE_DIR = os.path.join(COMMAND_DIR, "..", "..", "..", "stack", "stacks")

SUPPORTED_STEPS = [
    "license",
    "download",
    "create",
    "mount",
    "fix",
    "resize",
    "upgrade",
    "docker",
    "setup",
    "finalize",
    "unmount",
    "compress",
]
MANDATORY_STEPS = ["license", "create", "mount", "unmount"]

APT_PACKAGES_TO_INSTALL = [
    "rsync",
    "nano",
    "htop",
    # provides the command `growpart`, used to resize the root partition at first boot
    "cloud-guest-utils",
    # provides the command `inotifywait`, used to monitor inode events on trigger sockets
    "inotify-tools",
    # needed to be able to perform `docker login` on the device
    "gnupg2",
    "pass",
    "netplan.io",
    "busybox",
]
APT_PACKAGES_TO_HOLD = [
    # list here packages that cannot be updated through `chroot`
    "rsyslog"
]
DIND_IMAGE_NAME = "docker:24.0.2-dind"
DEVICE_PLATFORM = "linux/arm64"


class DTCommand(DTCommandAbs):

    help = "Prepares an .img disk file for an Nvidia Jetson Orin Nano"

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
            "--push",
            default=False,
            action="store_true",
            help="Whether to push the final compressed image to the Duckietown Cloud Storage",
        )
        parser.add_argument(
            "--input-image",
            type=str,
            default=None,
            help="Path to a pre-downloaded/extracted disk image. "
                 "If provided, the download step will be skipped and this image will be used as the base.",
        )
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = parser.parse_args(args=args)
        else:
            parsed = DTCommand._resolve_parsed([], parsed, parser=parser)
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
        jetpack_disk_image_name = JETPACK_DISK_IMAGE_NAME
        in_file_path = lambda ex: os.path.join(parsed.workdir, f"{jetpack_disk_image_name}.{ex}")
        input_image_name = pathlib.Path(in_file_path("img")).stem
        output_image_name = input_image_name.replace(JETPACK_VERSION, DISK_IMAGE_VERSION)
        out_file_name = lambda ex: f"dt-{output_image_name}.{ex}"
        out_file_path = lambda ex: os.path.join(parsed.output, out_file_name(ex))
        cached_step_file_path = lambda step, ex: os.path.join(
            parsed.output, "cache", out_file_name(ex) + f".{step}"
        )
        # handle custom input image
        custom_input_image = None
        if parsed.input_image is not None:
            custom_input_image = os.path.abspath(parsed.input_image)
            if not os.path.isfile(custom_input_image):
                dtslogger.error(f"Input image file not found: {custom_input_image}")
                return
            dtslogger.info(f"Using custom input image: {custom_input_image}")
        # get version
        distro = get_distro(shell)
        # create a virtual SD card object
        sd_card = VirtualSDCard(out_file_path("img"), DISK_IMAGE_PARTITION_TABLE)
        # this is the surgey plan that will be performed by the init_sd_card command
        surgery_plan = []
        # define disk image origin (by default we use the official vanilla nVidia JetPack OS)
        # if a custom input image is provided, use it as the source
        disk_image_origin = in_file_path("img")
        if custom_input_image is not None:
            disk_image_origin = custom_input_image
        using_cached_step = False
        # this holds the stats that will be stored in /data/stats/disk_image/build.json
        stats = {
            "steps": {step: bool(step in parsed.steps) for step in SUPPORTED_STEPS},
            "version": DISK_IMAGE_VERSION,
            "input_name": input_image_name,
            "input_url": INPUT_DISK_IMAGE_URL,
            "base_type": "Nvidia Jetpack",
            "base_version": JETPACK_VERSION,
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
                parsed.steps.discard(step)
            using_cached_step = True
        # verify that the input image exists before proceeding with create/mount steps
        if "create" in parsed.steps and not os.path.isfile(disk_image_origin):
            dtslogger.error(
                f"Input image file not found at {disk_image_origin}. "
                f"Please ensure the 'download' step is included or provide a valid --input-image."
            )
            return

        # ---
        print()
        dtslogger.info(f"Steps to perform: {[s for s in SUPPORTED_STEPS if s in parsed.steps]}")
        #
        # STEPS:
        # ------>
        # Step: license
        if "license" in parsed.steps:
            dtslogger.info("Step BEGIN: license")
            # ask to either agree or go away
            while True:
                answer = ask_confirmation(
                    f"This disk image uses the Nvidia Jetpack v{JETPACK_VERSION}. By proceeding, "
                    f"you agree to the terms and conditions of the License For Customer Use of "
                    f'NVIDIA Software"',
                    default="n",
                    choices={"a": "Accept", "n": "Reject", "r": "Read License"},
                    question="Do you accept?",
                )
                if answer == "r":
                    # load license text
                    with open(NVIDIA_LICENSE_FILE, "rt") as fin:
                        nvidia_license = fin.read()
                    print(f"\n{nvidia_license}\n")
                elif answer == "a":
                    break
                elif answer == "n":
                    dtslogger.error("You must agree to the License first.")
                    exit(9)
            # ---
            cache_step("license")
            dtslogger.info("Step END: license\n")
        else:
            dtslogger.warning(
                'Skipping "license" step. You are implicitly agreeing to the terms '
                "and conditions of the License For Customer Use of NVIDIA Software."
            )
        # Step: license
        # <------
        #
        # ------>
        # Step: download
        if "download" in parsed.steps:
            dtslogger.info("Step BEGIN: download")
            # if a custom input image was provided, copy it to the working directory
            if custom_input_image is not None:
                dtslogger.info(f"Using provided input image: {custom_input_image}")
                # create temporary dir
                run_cmd(["mkdir", "-p", parsed.workdir])
                # copy custom image to standard location
                if not os.path.isfile(in_file_path("img")):
                    dtslogger.info(f"Copying input image to {in_file_path('img')}...")
                    copy_file(custom_input_image, in_file_path("img"))
                    dtslogger.info("Input image copied successfully")
                else:
                    dtslogger.info(f"Image already exists at {in_file_path('img')}, skipping copy")
            else:
                # standard download flow
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
                                    DATA_STORAGE_DISK_IMAGE_DIR, f"{jetpack_disk_image_name}.img.zip"
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
        # Step: fix
        if "fix" in parsed.steps:
            dtslogger.info("Step BEGIN: fix")
            # fix GPT partition table
            dtslogger.info(f"Fixing GPT partition table on [{sd_card.loopdev}]")
            cmd = ["sudo", "gdisk", sd_card.loopdev]
            dtslogger.debug("$ %s" % cmd)
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE)
            time.sleep(1)
            p.communicate("x\ne\nw\ny\n".encode("ascii"))
            dtslogger.info("Done!")
            # ---
            cache_step("fix")
            dtslogger.info("Step END: fix\n")
        # Step: fix
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
            try:
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
                # force kernel to re-read partition table by detaching and re-attaching
                # this is necessary after gdisk modifies the partition table
                run_cmd(["sudo", "losetup", "-d", sd_card.loopdev])
                # re-attach with -P to automatically discover partitions
                lodev_output = subprocess.check_output(
                    ["sudo", "losetup", "-f", "-P", "--show", out_file_path("img")]
                ).decode("utf-8").strip()
                sd_card.set_loopdev(lodev_output)
                # refresh udev to recognize new partition devices
                run_cmd(["sudo", "udevadm", "trigger"])
                # update root_device to use the new loop device
                root_device = sd_card.partition_device(ROOT_PARTITION)
            except subprocess.CalledProcessError as e:
                dtslogger.warning(
                    "Failed to re-read partition table. If running this command inside a container, "
                    "ensure you start it with the '--privileged' flag to allow access to loop devices and "
                    "partition management capabilities."
                )
                pass

            # show info about disk
            dtslogger.debug("\n" + run_cmd(["sudo", "fdisk", "-l", sd_card.loopdev], True))
            # fix file system
            run_cmd(["sudo", "e2fsck", "-f", "-p", root_device])
            # resize file system
            run_cmd(["sudo", "resize2fs", root_device])
            # ---
            cache_step("resize")
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
                # check if the root disk device exists
                root_partition_disk = sd_card.partition_device(ROOT_PARTITION)
                if not os.path.exists(root_partition_disk):
                    raise ValueError(f"Disk device {root_partition_disk} not found")
                # mount `root` partition
                sd_card.mount_partition(ROOT_PARTITION)
                # dev partition from the host is mounted to _dev
                _dev = os.path.join(PARTITION_MOUNTPOINT(ROOT_PARTITION), "dev")
                # from this point on, if anything weird happens, unmount the `root` disk
                try:
                    # detect host architecture for QEMU conditional
                    host_arch = platform.machine()  # returns 'x86_64', 'aarch64', etc.
                    is_native_arm = host_arch == 'aarch64'
                    
                    # copy resolvconf (always needed)
                    _transfer_file(ROOT_PARTITION, ["run", "resolvconf", "resolv.conf"])
                    # mount /dev from the host
                    run_cmd(["sudo", "mount", "--bind", "/dev", _dev])
                    
                    # only setup QEMU on non-native ARM64 hosts (e.g., x86_64)
                    if not is_native_arm:
                        dtslogger.info(f"Host architecture detected as {host_arch} - setting up QEMU for ARM64 emulation")
                        # copy QEMU for x86 to ARM64 emulation
                        _transfer_file(ROOT_PARTITION, ["usr", "bin", "qemu-aarch64-static"])
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
                    else:
                        dtslogger.info(f"Native ARM64 host detected ({host_arch}) - skipping QEMU setup")
                    # from this point on, if anything weird happens, unmount the `root` disk
                    try:
                        # Disable GUI first (before any apt operations)
                        run_cmd_in_partition(
                            ROOT_PARTITION,
                            "systemctl set-default multi-user.target 2>/dev/null || true"
                        )

                        # update package index
                        run_cmd_in_partition(
                            ROOT_PARTITION,
                            "apt-get update -o Acquire::ForceIPv4=true"
                        )
                        # # Get the exact installed l4t-core version (e.g., 36.4.4-20250616085344)
                        # l4t_core_version = run_cmd_in_partition(
                        #     ROOT_PARTITION,
                        #     "dpkg-query -W -f='${Version}' nvidia-l4t-core 2>/dev/null || echo ''",
                        #     get_output=True
                        # ).strip()
                        # dtslogger.info(f"Installed nvidia-l4t-core version: {l4t_core_version}")
                        
                        # if l4t_core_version:
                        #     # Downgrade nvidia packages that require a different l4t-core version
                        #     # to versions compatible with the installed l4t-core
                        #     nvidia_pkgs_to_fix = [
                        #         "nvidia-l4t-jetsonpower-gui-tools",
                        #         "nvidia-l4t-nvfancontrol", 
                        #         "nvidia-l4t-nvpmodel",
                        #         "nvidia-l4t-nvpmodel-gui-tools",
                        #     ]
                        #     # Downgrade all packages at once to avoid dependency issues
                        #     pkgs_with_version = " ".join([f"{pkg}={l4t_core_version}" for pkg in nvidia_pkgs_to_fix])
                        #     dtslogger.info(f"Downgrading nvidia packages to {l4t_core_version}")
                        #     run_cmd_in_partition(
                        #         ROOT_PARTITION,
                        #         f"DEBIAN_FRONTEND=noninteractive apt install --yes --allow-downgrades -o Acquire::ForceIPv4=true {pkgs_with_version}",
                        #     )
                        
                        # Now fix any remaining broken dependencies
                        run_cmd_in_partition(
                            ROOT_PARTITION,
                            "DEBIAN_FRONTEND=noninteractive apt --fix-broken install --yes -o Acquire::ForceIPv4=true"
                        )
                        
                        # Install the packages we need
                        if APT_PACKAGES_TO_INSTALL:
                            pkgs = " ".join(APT_PACKAGES_TO_INSTALL)
                            dtslogger.info(f"Installing packages: {pkgs}")
                            run_cmd_in_partition(
                                ROOT_PARTITION,
                                "DEBIAN_FRONTEND=noninteractive "
                                "apt install --yes --no-install-recommends "
                                "-o Acquire::ForceIPv4=true "
                                f"{pkgs}",
                            )
                        # clean packages
                        run_cmd_in_partition(
                            ROOT_PARTITION,
                            "apt autoremove --yes",
                        )
                    except Exception as e:
                        raise e
                    # unmount bind mounts
                    try:
                        run_cmd(["sudo", "umount", _dev])
                    except:
                        pass
                except Exception as e:
                    # unmount bind mounts (with fallback if not mounted)
                    try:
                        run_cmd(["sudo", "umount", _dev])
                    except:
                        pass
                    # unmount partition
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
            # Call the refactored function:
            step_docker(
                sd_card=sd_card,
                out_file_path=out_file_path,
                ROOT_PARTITION=ROOT_PARTITION,
                STACKS=STACKS,
                STACKS_BASE_DIR=STACKS_BASE_DIR,
                DEVICE_PLATFORM=DEVICE_PLATFORM,
                DIND_IMAGE_NAME=DIND_IMAGE_NAME,
                architecture=DEVICE_ARCH
            )
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
                        # copy stacks (APP only)
                        if partition == ROOT_PARTITION:
                            abs_stacks_base = os.path.abspath(STACKS_BASE_DIR)
                            for stack in STACKS:
                                origin = os.path.join(abs_stacks_base, stack + ".yaml")
                                destination = os.path.join(
                                    PARTITION_MOUNTPOINT(partition), AUTOBOOT_STACKS_DIR.lstrip("/"), stack + '.yaml'
                                )
                                relative = os.path.join(AUTOBOOT_STACKS_DIR, stack)
                                # # validate file
                                # validator = _get_validator_fcn(partition, relative)
                                # if validator:
                                #     dtslogger.debug(f"Validating file {relative}...")
                                #     validator(shell, origin, relative, arch=DEVICE_ARCH)
                                # create or modify file
                                effect = "MODIFY" if os.path.exists(destination) else "NEW"
                                dtslogger.info(f"- Updating file ({effect}) [{relative}]")
                                run_cmd(["sudo", "mkdir", "-p", os.path.dirname(destination)])
                                # copy new file
                                run_cmd(["sudo", "cp", origin, destination])
                                # add architecture as default value in the stack file
                                dtslogger.debug(
                                    "- Replacing '{ARCH}' with '{ARCH:-%s}' in %s"
                                    % (DEVICE_ARCH, destination)
                                )
                                replace_in_file("{ARCH}", "{ARCH:-%s}" % DEVICE_ARCH, destination)
                                # add registry as default value in the stack file
                                dtslogger.debug(
                                    "- Replacing '{REGISTRY}' with '{REGISTRY:-%s}' in %s"
                                    % (DEFAULT_REGISTRY, destination)
                                )
                                replace_in_file(
                                    "{REGISTRY}", "{REGISTRY:-%s}" % DEFAULT_REGISTRY, destination
                                )
                        # apply changes from disk_template
                        files = disk_template_objects(DISK_TEMPLATE_DIR, partition, "file")
                        for update in files:
                            # validate file
                            # validator = _get_validator_fcn(partition, update["relative"])
                            # if validator:
                                # dtslogger.debug(f"Validating file {update['relative']}...")
                                # validator(shell, update["origin"], update["relative"], arch=DEVICE_ARCH)
                            # create or modify file
                            effect = "MODIFY" if os.path.exists(update["destination"]) else "NEW"
                            dtslogger.info(f"- Updating file ({effect}) [{update['relative']}]")
                            # copy new file
                            run_cmd(["sudo", "cp", update["origin"], update["destination"]])
                            # get first line of file
                            file_first_line = get_file_first_line(update["destination"])
                            # only files containing a known placeholder will be part of the surgery
                            if file_first_line.startswith(FILE_PLACEHOLDER_SIGNATURE):
                                placeholder = file_first_line[len(FILE_PLACEHOLDER_SIGNATURE):]
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
                dtslogger.debug(f"An error occurred: {str(e)}")
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
            # flush I/O buffers before unmounting
            dtslogger.info("Syncing filesystem buffers...")
            run_cmd(["sync"])
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
            if os.path.isfile(out_file_path("zip")):
                dtslogger.info(f"Reusing existing ZIP file [{out_file_path('zip')}], skipping compression.")
            else:
                dtslogger.info("Compressing disk image...")
                run_cmd(["zip", "-j", out_file_path("zip"), out_file_path("img"), out_file_path("json")])
                dtslogger.info("Done!")
            cache_step("compress")
            dtslogger.info("Step END: compress\n")
        # Step: compress
        # <------
        
        if parsed.push:
            if "compress" not in parsed.steps:
                dtslogger.warning("The step 'compress' was not performed. No artifacts to push.")
                return
            step_push(shell, out_file_name("zip"), out_file_path("zip"))
        
        dtslogger.info(f"Completed in {human_time(time.time() - stime)}")

    @staticmethod
    def complete(shell, word, line):
        return []


def _get_validator_fcn(partition, path):
    return get_validator_fcn(TEMPLATE_FILE_VALIDATOR, partition, path)


def _transfer_file(partition, location):
    return transfer_file(DISK_TEMPLATE_DIR, partition, location)
