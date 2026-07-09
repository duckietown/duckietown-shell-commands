import argparse
import copy
import getpass
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import platform
import plistlib
import sys
import time
from collections import namedtuple
from datetime import datetime
from types import SimpleNamespace
from typing import List, Optional

from math import floor, log2

from dt_shell import __version__ as shell_version, DTCommandAbs, DTShell, dtslogger
from utils.cli_utils import ask_confirmation, ensure_command_is_installed
from utils.duckietown_utils import (
    get_robot_configurations,
    get_robot_hardware,
    get_robot_types,
    WIRED_ROBOT_TYPES,
)
from utils.exceptions import InvalidUserInput
from utils.json_schema_form_utils import open_form_from_schema
from utils.misc_utils import human_time, sudo_open
from utils.progress_bar import ProgressBar
from .constants import (
    LIST_DEVICES_CMD,
    TIPS_AND_TRICKS,
    WPA_EAP_NETWORK_CONFIG,
    WPA_OPEN_NETWORK_CONFIG,
    WPA_PSK_NETWORK_CONFIG,
    NETPLAN_OPEN_NETWORK_CONFIG,
    NETPLAN_WPA_EAP_NETWORK_CONFIG,
    NETPLAN_WPA_PSK_NETWORK_CONFIG,
)

from disk_image.create.jetson_nano.private_command import DISK_IMAGE_VERSION as jetson_disk_image_version
from disk_image.create.jetson_orin_nano.private_command import DISK_IMAGE_VERSION as jetson_orin_disk_image_version

INIT_SD_CARD_VERSION = "2.1.0"  # incremental number, semantic version

Wifi = namedtuple("Wifi", "name ssid psk username password")

LEGACY_TMP_WORKDIR = "/tmp/duckietown/dts/init_sd_card"
HOME_DIR = os.path.expanduser("~")
FALLBACK_TMP_WORKDIR = os.path.join(HOME_DIR, ".cache", "duckietown", "dts", "init_sd_card")


def _get_existing_parent_dir(path: str) -> str:
    parent_dir = path
    while not os.path.isdir(parent_dir):
        next_parent_dir = os.path.dirname(parent_dir)
        if next_parent_dir == parent_dir:
            break
        parent_dir = next_parent_dir
    return parent_dir


def _can_create_workdir(path: str) -> bool:
    existing_parent_dir = _get_existing_parent_dir(path)
    required_mode = os.W_OK | os.X_OK
    return os.access(existing_parent_dir, required_mode)


def _get_tmp_workdir() -> str:
    candidate_dirs = (LEGACY_TMP_WORKDIR, FALLBACK_TMP_WORKDIR)
    for workdir in candidate_dirs:
        if _can_create_workdir(workdir):
            return workdir
    raise OSError("Could not determine a writable init_sd_card working directory.")


TMP_WORKDIR = _get_tmp_workdir()
BLOCK_SIZE = 1024**2
SAFE_SD_SIZE_MIN = 16
SAFE_SD_SIZE_MAX = 64
DEFAULT_ROBOT_TYPE = "duckiebot"
DEFAULT_WIFI_CONFIG = "duckietown:quackquack"
COMMAND_DIR = os.path.dirname(os.path.abspath(__file__))
SUPPORTED_STEPS = ["license", "download", "flash", "setup"]
NVIDIA_LICENSE_FILE = os.path.join(COMMAND_DIR, "nvidia-license.txt")
ROOT_PARTITIONS = ["root", "rootfs", "APP"]


def DISK_IMAGE_VERSION(robot_configuration, experimental=False, version_override=None):
    if version_override is not None:
        return version_override
    board_to_disk_image_version = {
        "raspberry_pi": {"stable": "1.2.1", "experimental": "1.2.1"},
        "raspberry_pi_64": {"stable": "4.0.0", "experimental": "4.0.0"},
        "jetson_nano_4gb": {"stable": jetson_disk_image_version, "experimental": "1.4.3"},
        "jetson_nano_2gb": {"stable": "1.2.2", "experimental": "1.2.2"},
        "jetson_orin_nano": {"stable": jetson_orin_disk_image_version, "experimental": jetson_orin_disk_image_version},
    }
    board, _ = get_robot_hardware(robot_configuration)
    stream = "stable" if not experimental else "experimental"
    return board_to_disk_image_version[board][stream]


def PLACEHOLDERS_VERSION(robot_configuration, experimental=False, version_override=None):
    board_to_placeholders_version = {
        "raspberry_pi": {
            # - stable
            "1.2.1": "1.1",
            # - experimental
            "-----": "1.1",
        },
        "raspberry_pi_64": {
            # - stable
            "4.0.0": "2.0",
            # - experimental
            "-----": "2.0",
        },
        "jetson_nano_4gb": {
            # - stable
            jetson_disk_image_version : "1.1",
            # - experimental
            "-----": "1.1",
        },
        "jetson_nano_2gb": {
            # - stable
            "1.2.2": "1.1",
            # - experimental
            "-----": "1.1",
        },
        "jetson_orin_nano": {
            # - stable
            jetson_orin_disk_image_version: "2.0",
            # - experimental
            "-----": "2.0",
        },
    }

    board, _ = get_robot_hardware(robot_configuration)
    version = DISK_IMAGE_VERSION(robot_configuration, experimental, version_override)

    board_versions = board_to_placeholders_version.get(board, {})
    placeholder_version = board_versions.get(version)

    if placeholder_version is None:
        dtslogger.warning(
            f"Unknown disk image version '{version}' for board '{board}', defaulting to placeholder version 1.1."
        )
        placeholder_version = "1.1"  # or raise an error if strict matching is required

    return placeholder_version


def BASE_DISK_IMAGE(robot_configuration, experimental=False, version_override=None):
    disk_version = DISK_IMAGE_VERSION(robot_configuration, experimental, version_override)
    board_to_disk_image = {
        "raspberry_pi": f"dt-hypriotos-rpi-v{DISK_IMAGE_VERSION(robot_configuration, experimental)}",
        "raspberry_pi_64": f"dt-raspios-bookworm-lite-v{DISK_IMAGE_VERSION(robot_configuration, experimental)}-arm64v8",
        "jetson_nano_4gb": f"dt-nvidia-jetpack-v{DISK_IMAGE_VERSION(robot_configuration, experimental)}-4gb",
        "jetson_nano_2gb": f"dt-nvidia-jetpack-v{DISK_IMAGE_VERSION(robot_configuration, experimental)}-2gb",
        "jetson_orin_nano": f"dt-nvidia-jetpack-orin-v{DISK_IMAGE_VERSION(robot_configuration, experimental)}",
    }
    board, _ = get_robot_hardware(robot_configuration)
    return board_to_disk_image[board]


def DISK_IMAGE_CLOUD_LOCATION(robot_configuration, experimental=False, version_override=None):
    disk_image = BASE_DISK_IMAGE(robot_configuration, experimental, version_override)
    return f"disk_image/{disk_image}.zip"


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        parser = argparse.ArgumentParser()
        # configure parser
        parser.add_argument("--steps", default=",".join(SUPPORTED_STEPS), help="Steps to perform")
        parser.add_argument("--no-steps", default="", help="Steps NOT to perform")
        parser.add_argument("--hostname", default=None, help="Hostname of the device to flash")
        parser.add_argument("--device", default=None, help="The SD card device to flash")
        parser.add_argument("--country", default="US", help="2-letter country code (US, CA, CH, etc.)")
        parser.add_argument(
            "--wifi",
            dest="wifi",
            default=None,
            help="""
            Can specify one or more networks: "network:password,network:password,..."
            Default for watchtower and traffic_light is no wifi config.
            Default for other robot types is "duckietown:quackquack"

            Each network defined in the list can have between 1 and 3 arguments:

                - Open networks (no password)

                    network:    "ssid"


                - PSK (Pre-shared key) protected networks (no password)

                    network:    "ssid:psk"


                - EAP (Extensible Authentication Protocol) protected networks

                    network:    "ssid:username:password"

            """,
        )
        parser.add_argument(
            "--type",
            dest="robot_type",
            default=None,
            choices=get_robot_types(),
            help="Which type of robot we are setting up",
        )
        parser.add_argument(
            "--configuration",
            dest="robot_configuration",
            default=None,
            help="Which configuration your robot is in",
        )
        parser.add_argument(
            "--no-cache",
            default=False,
            action="store_true",
            help="Whether to use cached ISO image"
        )
        parser.add_argument(
            "--gui",
            default=False,
            action="store_true",
            help="Use (experimental) gui",
        )
        parser.add_argument(
            "--verify",
            default=False,
            action="store_true",
            help="Verify written data",
        )
        parser.add_argument(
            "--experimental",
            default=False,
            action="store_true",
            help="Use experimental disk image and parameters",
        )
        parser.add_argument(
            "-S",
            "--size",
            default=None,
            type=int,
            help="(Optional) Size of the SD card you are flashing",
        )
        parser.add_argument(
            "--workdir",
            default=TMP_WORKDIR,
            type=str,
            help="(Optional) temporary working directory to use"
        )
        parser.add_argument(
            "--version",
            dest="disk_image_version",
            default=None,
            help="Override the default disk image version to use"
        )
        parser.add_argument(
            "--placeholders-version",
            dest="placeholders_version",
            default=None,
            help="Override the default placeholders version to use"
        )
        parser.add_argument(
            "--image",
            default=None,
            help="Path to a local .img file to use instead of downloading.",
        )

        # parse arguments
        parsed = parser.parse_args(args=args)

        # GUI mode does not have required arguments
        gui: bool = parsed.gui
        if not gui and parsed.hostname is None:
            parser.error("The argument --hostname is required, unless you use --gui.")
            exit(1)

        # fetch given steps
        steps = parsed.steps.split(",")
        no_steps = parsed.no_steps.split(",")
        steps = [s for s in steps if s not in no_steps]

        # verify
        if parsed.verify:
            if "verify" in no_steps:
                raise ValueError("You cannot use --verify together with --no-steps verify")
            steps += ["verify"]

        # GUI
        if gui:
            # ask the user to fill in the form
            values: Optional[dict] = open_form_from_schema(
                shell,
                "init-sd-card",
                "v1",
                title="Initialize a new SD card",
                subtitle="Let's initialize a new Duckietown robot!",
                completion_message="All done!\nYou can now close this page and return to the terminal.",
            )
            if values is None:
                dtslogger.info("No configuration received, exiting...")
                exit(0)
            # populate args
            parsed.hostname = values["hostname"]
            parsed.robot_type = values["type"]
            parsed.robot_configuration = values[f"{parsed.robot_type}_configuration"]
            parsed.wifi = ",".join([f"{w['ssid']}:{w['wpa']}".strip(":") for w in values.get("wifi", [])])
            parsed.experimental = values["experimental"] == "true"
            parsed.size = int(values["size"])
            # the form includes all licenses
            if "license" in steps:
                steps.remove("license")
        # validate hostname and provide suggestion
        # 'valid' is True if parsed hostname is valid, or if user accepted the valid suggestion
        valid, valid_hostname = _validate_hostname(parsed.hostname)
        if not valid:
            return
        else:
            parsed.hostname = valid_hostname  # gets passed on to other services
        # default WiFi
        if parsed.wifi is None:
            if parsed.robot_type in WIRED_ROBOT_TYPES:
                parsed.wifi = ""
            else:
                parsed.wifi = DEFAULT_WIFI_CONFIG
        # print some usage tips and tricks
        print(TIPS_AND_TRICKS)
        # get the robot type
        if parsed.robot_type is None:
            granted = ask_confirmation(
                'You did not specify a robot type. Default is "{}"'.format(DEFAULT_ROBOT_TYPE)
            )
            if granted:
                parsed.robot_type = DEFAULT_ROBOT_TYPE
            else:
                dtslogger.info("Please retry while specifying a robot type. Bye bye!")
                exit(1)
        dtslogger.info(f"Robot type: {parsed.robot_type}")
        # get the robot configuration
        allowed_configs = get_robot_configurations(parsed.robot_type)
        if parsed.robot_configuration is None:
            dtslogger.info(
                f"You did not specify a robot configuration.\n"
                f"Given that your robot is a {parsed.robot_type}, possible "
                f"configurations are: {', '.join(allowed_configs)}"
            )
            # ---
            while True:
                r = input("Insert your robot's configuration: ")
                if r.strip() in allowed_configs:
                    parsed.robot_configuration = r.strip()
                    break
                dtslogger.warning(f"Configuration '{r}' not recognized. Please, retry.")
        # validate robot configuration
        if parsed.robot_configuration not in allowed_configs:
            dtslogger.error(
                f"Robot configuration {parsed.robot_configuration} not recognized "
                f"for robot type {parsed.robot_type}. Possible configurations "
                f"are: {', '.join(allowed_configs)}"
            )
            exit(2)
        dtslogger.info(f"Robot configuration: {parsed.robot_configuration}")

        # validate steps
        step2function = {
            "license": step_license,
            "download": step_download,
            "flash": step_flash,
            "verify": step_verify,
            "setup": step_setup,
        }
        # validate steps
        for step_name in steps:
            if step_name not in step2function:
                msg = "Cannot find step %r in %s" % (step_name, list(step2function))
                raise InvalidUserInput(msg)
        # compile hardware specific disk image name and url
        base_disk_image = BASE_DISK_IMAGE(parsed.robot_configuration, parsed.experimental, version_override=parsed.disk_image_version)

        # compile files destinations
        def in_file(e):
            return os.path.join(parsed.workdir, f"{base_disk_image}.{e}")

        # notify about licenses
        if "license" not in steps:
            board, _ = get_robot_hardware(parsed.robot_configuration)
            extra = (
                "   - License For Customer Use of NVIDIA Software\n"
                if board.startswith("jetson_nano")
                else ""
            )
            dtslogger.warning(
                'Skipping "license" step. You are implicitly agreeing to the following:\n'
                + extra
                + "   - Duckietown Terms and Conditions:\t"
                "https://duckietown.com/terms-and-conditions/\n"
                "   - Duckietown Software License:\t"
                "https://duckietown.com/sw-license/\n"
                "   - Duckietown Privacy Policy:\t\t"
                "https://duckietown.com/privacy/",
            )
        # prepare data
        data = {
            "robot_configuration": parsed.robot_configuration,
            "disk_zip": in_file("zip"),
            "disk_img": in_file("img"),
            "disk_metadata": in_file("json"),
            "steps": steps,
        }
        # perform steps
        for step_name in steps:
            data.update(step2function[step_name](shell, parsed, data))
        # ---
        if "flash" in steps:
            dtslogger.info("Flashing completed successfully!")
            if data["sd_type"] == "SD":
                dtslogger.info(
                    f"You can now unplug the SD card "
                    f"and put it inside a {parsed.robot_type.title()}. Have fun!"
                )


def step_license(_, parsed, __):
    print()
    # Duckietown legal stuff
    answer = ask_confirmation(
        f"\nBy proceeding you agree to the following,\n"
        f"   - Duckietown Terms and Conditions:\t"
        f"https://duckietown.com/terms-and-conditions/\n"
        f"   - Duckietown Software License:\t"
        f"https://duckietown.com/sw-license/\n"
        f"   - Duckietown Privacy Policy:\t\t"
        f"https://duckietown.com/privacy/",
        question="Do you accept?",
    )
    if not answer:
        dtslogger.error(
            "You must explicitly agree to the Term and Conditions, Software License "
            "and Privacy Policy of Duckietown to continue.\n"
            "For additional information, please contact info@duckietown.com."
        )
        exit(9)
    # NVIDIA Software License
    board, _ = get_robot_hardware(parsed.robot_configuration)
    if board.startswith("jetson_nano"):
        # ask to either agree or go away
        while True:
            print()
            answer = ask_confirmation(
                f"\nThis disk image uses the Nvidia Jetpack OS.\nBy proceeding, "
                f"you agree to the terms and conditions of the License For Customer Use of "
                f"NVIDIA Software",
                default="n",
                choices={"y": "Yes", "n": "No", "r": "Read License"},
                question="Do you accept?",
            )
            if answer == "r":
                # load license text
                with open(NVIDIA_LICENSE_FILE, "rt") as fin:
                    nvidia_license = fin.read()
                print(f"\n{nvidia_license}\n")
            elif answer == "y":
                break
            elif answer == "n":
                dtslogger.error("You must explicitly agree to the License first.")
                exit(8)
    print()
    return {}


def step_download(shell, parsed, data):
    # use local image if specified
    if parsed.image:
        dtslogger.info(f"Using provided local disk image: {parsed.image}")
        if not os.path.isfile(parsed.image):
            dtslogger.error(f"The specified image file does not exist: {parsed.image}")
            exit(3)
        # create temp dir if it doesn't exist
        _run_cmd(["mkdir", "-p", parsed.workdir])
        # copy .img to expected location
        shutil.copy(parsed.image, data["disk_img"])
        return {}

    # check if dependencies are met
    ensure_command_is_installed("unzip")

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
    _run_cmd(["mkdir", "-p", parsed.workdir])
    # download zip (if necessary)
    dtslogger.info("Looking for ZIP image file...")
    if not os.path.isfile(data["disk_zip"]):
        dtslogger.info("Downloading ZIP image...")
        # get disk image location on the cloud
        disk_image = DISK_IMAGE_CLOUD_LOCATION(parsed.robot_configuration, parsed.experimental, version_override=getattr(parsed, "disk_image_version", None))
        # download zip
        shell.include.data.get.command(
            shell, [], parsed=SimpleNamespace(object=[disk_image], file=[data["disk_zip"]], space="public")
        )
    else:
        dtslogger.info(f"Reusing cached ZIP image file [{data['disk_zip']}].")
    # unzip (if necessary)
    if not os.path.isfile(data["disk_img"]):
        dtslogger.info("Extracting ZIP image...")
        _run_cmd(["unzip", data["disk_zip"], "-d", parsed.workdir])
    else:
        dtslogger.info(f"Reusing cached DISK image file [{data['disk_img']}].")
    # ---
    return {}


def step_flash(_, parsed, data):
    # check if dependencies are met
    _ensure_flash_dependencies()
    print("=" * 30)

    # ask for a device if not set already
    if parsed.device is None:
        sd_size = 0 if parsed.size is None else parsed.size
        # ask user first what is their desired device size as a confirmation.
        while sd_size <= 0:
            msg = "Please, enter the size of your SD card (in GB): "
            # noinspection PyBroadException
            try:
                txt = input(msg)
                if txt.strip() == "q":
                    dtslogger.info("Exiting")
                    exit()
                sd_size = int(txt)
                assert sd_size > 0
            except (ValueError, AssertionError):
                continue
            standard = log2(sd_size) - floor(log2(sd_size)) == 0
            if not (SAFE_SD_SIZE_MIN <= sd_size <= SAFE_SD_SIZE_MAX) or not standard:
                answer = ask_confirmation(
                    f"You are indicating a non standard size: {sd_size}GB", default="n", question="Proceed?"
                )
                if not answer:
                    dtslogger.info("Exiting")
                    exit()
            break
        # get all available devices
        devices_all = _get_devices()
        # all device with size within 20% of the given size are a match
        devices_fit = list(filter(lambda d: abs(d.size_gb - sd_size) < (0.2 * sd_size), devices_all))
        # if there is any fit, show them
        if devices_fit:
            print(f"The following devices were found (size ~{sd_size}GB):")
            _print_devices_table(devices_fit)
        else:
            answer = ask_confirmation(
                f"No devices were found with a size of ~{sd_size}GB.",
                question="Do you want to see all the disks available?",
                default="n",
            )
            if not answer:
                dtslogger.info("Sounds good! Exiting...")
                exit()
            # show all
            dtslogger.warn(
                "Be aware that picking the wrong device might result in irreversible "
                "damage to your operating system or data loss."
            )
            print("\nThe following devices are available:")
            _print_devices_table(devices_all)

        device = None
        while device is None:
            msg = "Type the name of the device of choice (from the list above): "
            txt = input(msg)
            if len(txt.strip()) > 0:
                device = txt
        parsed.device = device

    # check if the device exists
    if parsed.device.startswith("/dev/"):
        sd_type = "SD"
        if not os.path.exists(parsed.device):
            msg = "Device %s was not found on your system. Please, check." % parsed.device
            raise InvalidUserInput(msg)
    else:
        sd_type = "File"
        if os.path.exists(parsed.device):
            msg = f"File {parsed.device} already exists, it will be overwritten."
            granted = ask_confirmation(msg)
            if not granted:
                dtslogger.info("Please retry while specifying a valid device. Bye bye!")
                exit(4)

    # unmount all partitions if SD card
    if sd_type == "SD":
        # noinspection PyBroadException
        try:
            dtslogger.info(f"Trying to unmount all partitions from device {parsed.device}")
            _unmount_device(parsed.device)
            dtslogger.info("All partitions unmounted.")
        except BaseException:
            dtslogger.warn(
                "An error occurred while unmounting the partitions of your SD card. "
                "Though this is not critical, you might experience issues with your SD "
                "card after flashing is complete. If that is the case, make sure to "
                "unmount all disks from your SD card before flashing the next time."
            )

    # use dd to flash
    dtslogger.info("Flashing File[{}] -> {}[{}]:".format(data["disk_img"], sd_type, parsed.device))
    dd_py = os.path.join(pathlib.Path(__file__).parent.absolute(), "dd.py")
    bsize = str(BLOCK_SIZE)
    dd_cmd = (["sudo"] if sd_type == "SD" else []) + [
        dd_py,
        "--input",
        data["disk_img"],
        "--output",
        parsed.device,
        "--block-size",
        bsize,
    ]
    _run_cmd(dd_cmd)
    # ---
    dtslogger.info("{}[{}] flashed!".format(sd_type, parsed.device))
    return {"sd_type": sd_type}


def step_verify(_, parsed, data):
    dtslogger.info("Verifying {}[{}]...".format(data.get("sd_type", ""), parsed.device))
    buf_size = 16 * 1024
    # create a progress bar to track the progress
    pbar = ProgressBar(header="Verifying [ETA: ND]")
    tbytes = os.stat(data["disk_img"]).st_size
    nbytes = 0
    stime = time.time()
    # compare bytes
    try:
        with open(data["disk_img"], "rb") as origin:
            # Check that parsed.device is not None
            if parsed.device is None:
                dtslogger.error("Destination device is None. If you're skipping the flash step, please provide a device using the --device flag.")
            with sudo_open(parsed.device, "rb") as destination:
                buffer1 = origin.read(buf_size)
                while buffer1:
                    buf1_len = len(buffer1)
                    buffer2 = destination.read(buf1_len)
                    buf2_len = len(buffer2)
                    # check lengths, then content
                    if buf1_len != buf2_len or buffer1 != buffer2:
                        raise IOError("Mismatch in range position [{}-{}]".format(nbytes, nbytes + buf1_len))
                    # update progress bar
                    nbytes += buf1_len
                    progress = int(100 * (nbytes / tbytes))
                    pbar.update(progress)
                    # compute ETA
                    if progress > 0:
                        elapsed = time.time() - stime
                        eta = (100 - progress) * (elapsed / progress)
                        pbar.set_header("Verifying [ETA: {}]".format(human_time(eta, True)))
                    # read another chunk
                    buffer1 = origin.read(buf_size)
    except IOError as e:
        sys.stdout.write("\n")
        sys.stdout.flush()
        dtslogger.error(
            "The verification step failed. Please, try re-flashing.\n" "The error reads:\n\n{}".format(str(e))
        )
        exit(5)
    dtslogger.info("Verified in {}".format(human_time(time.time() - stime)))
    # ---
    dtslogger.info("{}[{}] successfully flashed!".format(data.get("sd_type", ""), parsed.device))
    return {}


def step_setup(shell: DTShell, parsed: argparse.Namespace, data: dict):
    # check if dependencies are met
    ensure_command_is_installed("dd")
    ensure_command_is_installed("sudo")
    ensure_command_is_installed("sync")
    is_sd_target = parsed.device is not None and parsed.device.startswith("/dev/")
    if is_sd_target:
        dtslogger.info(f"Unmounting device {parsed.device} before applying setup data...")
        _unmount_device(parsed.device)
        if platform.system() == "Darwin":
            time.sleep(0.5)
    target_device = parsed.device
    # make a copy of the command parameters and remove wifi passwords
    params = copy.deepcopy(parsed.__dict__)
    wfstr = lambda w: w if ":" not in w else (w.split(":")[0] + ":***")
    params["wifi"] = ",".join(list(map(wfstr, params["wifi"].split(","))))
    # compile data used to format placeholders
    surgery_data = {
        "hostname": parsed.hostname,  # contains value after _validate_hostname
        "country": parsed.country,
        "robot_type": parsed.robot_type,
        "token": shell.profile.secrets.dt_token,
        "robot_configuration": parsed.robot_configuration,
        "robot_distro": shell.profile.distro.name,
        "netplan_wifi_networks": _get_netplan_wifi_configuration(parsed),
        # netplan configurations for v2.0 placeholders (Jetson Orin Nano)
        "netplan_open_networks": _get_netplan_networks(parsed, "open"),
        "netplan_wpa_psk_networks": _get_netplan_networks(parsed, "psk"),
        "netplan_wpa_eap_networks": _get_netplan_networks(parsed, "eap"),
        "sanitize_files": None,
        "stats": json.dumps(
            {
                "steps": {step: bool(step in data["steps"]) for step in SUPPORTED_STEPS},
                "base_disk_name": BASE_DISK_IMAGE(parsed.robot_configuration, parsed.experimental, version_override=getattr(parsed, "disk_image_version", None)),
                "base_disk_version": DISK_IMAGE_VERSION(parsed.robot_configuration, parsed.experimental, version_override=getattr(parsed, "disk_image_version", None)),
                "base_disk_location": DISK_IMAGE_CLOUD_LOCATION(
                    parsed.robot_configuration, parsed.experimental, version_override=getattr(parsed, "disk_image_version", None)
                ),
                "environment": {
                    "hostname": socket.gethostname(),
                    "user": getpass.getuser(),
                    "shell_version": shell_version,
                    "commands_version": shell.profile.distro.name,
                    "init_sd_card_version": INIT_SD_CARD_VERSION,
                },
                "parameters": params,
                "stamp": time.time(),
                "stamp_human": datetime.now().isoformat(),
            },
            indent=4,
            sort_keys=True,
        ),
        # placeholders v1.1
        "wpa_networks": _get_wpa_supplicant_wifi_configuration(parsed),
        "wpa_country": parsed.country,
    }
    # read disk metadata
    with open(data["disk_metadata"], "rt") as fin:
        disk_metadata = json.load(fin)
    # get surgery plan
    surgery_plan = disk_metadata["surgery_plan"]
    # compile list of files to sanitize at first boot
    sanitize = map(lambda s: s["path"], filter(lambda s: s["partition"] in ROOT_PARTITIONS, surgery_plan))
    surgery_data["sanitize_files"] = "\n".join(map(lambda f: f'dt-sanitize-file "{f}"', sanitize))
    # get disk image placeholders
    if parsed.placeholders_version is not None:
        placeholders_version = parsed.placeholders_version
    else:
        placeholders_version = PLACEHOLDERS_VERSION(parsed.robot_configuration, parsed.experimental, version_override=getattr(parsed, "disk_image_version", None))
    placeholders_dir = os.path.join(COMMAND_DIR, "placeholders", "v" + placeholders_version)
    # perform surgery
    dtslogger.info("Performing surgery on the SD card...")
    for surgery_bit in surgery_plan:
        dtslogger.info("Performing surgery on [{partition}]:{path}.".format(**surgery_bit))
        # get placeholder info
        surgery_bit["placeholder"] = surgery_bit["placeholder"]
        placeholder_file = os.path.join(placeholders_dir, surgery_bit["placeholder"])
        # make sure that the placeholder exists
        if not os.path.isfile(placeholder_file):
            print(placeholder_file)
            dtslogger.error(f"The placeholder {surgery_bit['placeholder']} is not recognized.")
            exit(6)
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
        dd_cmd = (["sudo"] if is_sd_target else []) + [
            "dd",
            "of={}".format(target_device),
            "bs=1",
            "count={}".format(block_size),
            "seek={}".format(block_offset),
            "conv=notrunc",
        ]
        # write twice (found to increase success rate)
        for wpass in range(2):
            retries = 10 if is_sd_target and platform.system() == "Darwin" else 1
            for attempt in range(retries):
                if is_sd_target:
                    _unmount_device(parsed.device)
                    if platform.system() == "Darwin":
                        time.sleep(0.5)
                # launch dd
                dd = subprocess.Popen(dd_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
                dtslogger.debug(f"[{wpass + 1}/2] $ {dd_cmd}")
                _, stderr = dd.communicate(masked_content)
                if dd.returncode == 0:
                    break
                error = stderr.decode("utf-8", errors="replace").strip()
                can_retry = (
                    platform.system() == "Darwin"
                    and "Resource busy" in error
                    and attempt + 1 < retries
                )
                if can_retry:
                    dtslogger.warning(
                        f"Write target {target_device} is busy, retrying "
                        f"({attempt + 1}/{retries})..."
                    )
                    time.sleep(0.5)
                    continue
                raise RuntimeError(
                    f"Failed to inject placeholder {surgery_bit['placeholder']} into {target_device}: {error}"
                )
            # flush I/O buffer
            _run_cmd(["sync"])
    dtslogger.info("Surgery went OK!")
    # flush I/O buffer
    dtslogger.info("Flushing I/O buffer...")
    _run_cmd(["sync"])
    dtslogger.info("Done!")
    # ---
    return {}


def _validate_hostname(hostname: str):
    # The proper regex for RFC 952 should be:
    # ^(([a-zA-Z]|[a-zA-Z][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z]|[A-Za-z][A-Za-z0-9\-]*[A-Za-z0-9])$
    # We modify that since we do not wish "hyphen" and "dot" to be valid for ROS reasons.
    # Must start with a lowercase letter, followed by zero or more lowercase letters or digits.
    pattern = r"^[a-z][a-z0-9]*$"
    if not re.match(pattern, hostname):
        # suggest a valid name with the same logic stated above
        # filter for lowercase alphanumeric
        filtered = ''.join(c.lower() for c in hostname if c.isalnum())
        # remove digits at the beginning (must start with a letter)
        suggestion = re.sub(r'^\d+', '', filtered)
        # if no valid suggestion can be derived, abort gracefully
        if not re.match(pattern, suggestion):
            dtslogger.error(
                f"The hostname '{hostname}' is not valid and no valid suggestion could be derived.\n"
                "Hostnames must start with a lowercase letter (a-z) and contain only "
                "lowercase letters (a-z) and numbers (0-9).\n"
                "Please provide a valid hostname and repeat the step."
            )
            return False, ""

        granted = ask_confirmation(
            message=(
                "The hostname can only contain lowercase letters (a-z) and numbers (0-9). "
                "It must start with a letter."
            ),
            question=f'Do you want to use the hostname "{suggestion}" instead?',
        )
        if granted:
            dtslogger.info(
                f'Proceeding with new valid hostname: "{suggestion}"'
            )
            return True, suggestion
        else:
            dtslogger.info(
                "Operation aborted. Please provide a valid hostname and repeat the step."
            )
            return False, ""  # no valid hostname chosen
    # original user input is valid
    return True, hostname


def _interpret_wifi_string(s) -> List[Wifi]:
    results = []
    if len(s.strip()) == 0:
        return []
    for i, connection in enumerate(s.split(",")):
        name = f"network_{i + 1}"
        tokens = list(map(lambda t: t.strip(), connection.split(":")))
        # valid wifi strings are
        #
        #   - ssid                          (open networks)
        #   - ssid:pass                     (WPA-PSK authentication w/ shared key `pass`)
        #   - ssid:username:password        (WPA-EAP authentication w/ identity username:password)
        #
        if len(tokens) not in [1, 2, 3]:
            msg = "Invalid wifi string %r" % s
            raise Exception(msg)
        # parse tokens
        wifissid, arg1, arg2, *_ = tokens + [None] * 2
        if arg1 is None:
            results.append(Wifi(name, wifissid, None, None, None))
        elif arg2 is None:
            results.append(Wifi(name, wifissid, arg1, None, None))
        else:
            results.append(Wifi(name, wifissid, None, arg1, arg2))
        # ---
    return results


def _get_wpa_supplicant_wifi_configuration(parsed):
    networks = _interpret_wifi_string(parsed.wifi)
    wpa_networks = ""
    for connection in networks:
        # EAP-secured network
        if connection.username is not None:
            wpa_networks += WPA_EAP_NETWORK_CONFIG.format(
                cname=connection.name,
                ssid=connection.ssid,
                username=connection.username,
                password=connection.password,
            )
            continue
        # PSK-secured network
        if connection.psk is not None:
            wpa_networks += WPA_PSK_NETWORK_CONFIG.format(
                cname=connection.name, ssid=connection.ssid, psk=connection.psk
            )
            continue
        # open network
        wpa_networks += WPA_OPEN_NETWORK_CONFIG.format(cname=connection.name, ssid=connection.ssid)
    # ---
    return wpa_networks


def _get_netplan_wifi_configuration(parsed) -> str:
    networks = _interpret_wifi_string(parsed.wifi)
    wifis = []

    for connection in networks:
        if connection.ssid == "duckietown" and connection.psk == "quackquack":
            # Replace the duckietown:quackquack network with a placeholder. This network is already included
            # in the base disk image and should not be added again to avoid a duplicate in the netplan configuration file.
            connection = _interpret_wifi_string("mywifi:mypassword")[0]

        if connection.username is not None:
            wifi = NETPLAN_WPA_EAP_NETWORK_CONFIG.format(
                ssid=connection.ssid,
                username=connection.username,
                password=connection.password,
            )
        # PSK-secured network
        elif connection.psk is not None:
            wifi = NETPLAN_WPA_PSK_NETWORK_CONFIG.format(
                ssid=connection.ssid,
                psk=connection.psk
            )
        # open network
        else:
            wifi = NETPLAN_OPEN_NETWORK_CONFIG.format(
                ssid=connection.ssid
            )
        # ---
        wifis.append(wifi)
    # ---
    return "\n".join(wifis)


def _get_netplan_networks(parsed, network_type: str) -> str:
    """Generate netplan YAML network configurations for Ubuntu 22.04+ (placeholders v2.0)"""
    networks = _interpret_wifi_string(parsed.wifi)
    netplan_networks = ""
    for connection in networks:
        # EAP-secured network
        if connection.username is not None:
            if network_type == "eap":
                netplan_networks += NETPLAN_WPA_EAP_NETWORK_CONFIG.format(
                    ssid=connection.ssid,
                    username=connection.username,
                    password=connection.password,
                )
            continue
        # PSK-secured network
        if connection.psk is not None:
            if network_type == "psk":
                netplan_networks += NETPLAN_WPA_PSK_NETWORK_CONFIG.format(
                    ssid=connection.ssid, psk=connection.psk
                )
            continue
        # open network
        if network_type == "open":
            netplan_networks += NETPLAN_OPEN_NETWORK_CONFIG.format(ssid=connection.ssid)
    # ---
    return netplan_networks


def _run_cmd(cmd, get_output=False, shell=False, quiet=False):
    dtslogger.debug("$ %s" % cmd)
    env = copy.deepcopy(os.environ)
    # force English language
    env["LC_ALL"] = "C"
    # turn [cmd] into "cmd" if shell is set to True
    if isinstance(cmd, list) and shell:
        cmd = " ".join(cmd)
    # manage output
    if quiet:
        outputs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    else:
        outputs = {}
    # ---
    if get_output:
        return subprocess.check_output(cmd, shell=shell, env=env).decode("utf-8")
    else:
        subprocess.check_call(cmd, shell=shell, env=env, **outputs)


def _ensure_flash_dependencies():
    ensure_command_is_installed("sudo")
    if platform.system() == "Darwin":
        ensure_command_is_installed("diskutil")
        return
    ensure_command_is_installed("lsblk")
    ensure_command_is_installed("umount")


def _unmount_device(device: str):
    if platform.system() == "Darwin":
        _run_cmd(["diskutil", "unmountDisk", "force", _get_darwin_block_device(device)], quiet=True)
        return
    cmd = f"for n in {device}* ; do umount $n || . ; done"
    _run_cmd(cmd, shell=True, quiet=True)


def _get_darwin_block_device(device: str) -> str:
    if device.startswith("/dev/rdisk"):
        return "/dev/disk" + device[len("/dev/rdisk") :]
    return device


def _get_devices() -> List[SimpleNamespace]:
    if platform.system() == "Darwin":
        return _get_darwin_devices()
    units = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    lsblk = _run_cmd(LIST_DEVICES_CMD, get_output=True, shell=True)
    out = []
    for line in lsblk.split("\n"):
        findings = re.findall(r"^(/dev/[\w\d]+)\s+disk\s+(\d+(?:[.]\d+)?)([KMGT])\s+", line)
        if findings:
            device, size, unit, *_ = findings[0]
            if unit not in units:
                continue
            try:
                size = float(size)
            except ValueError:
                continue
            size_b = size * units[unit]
            size_gb = size_b / units["G"]
            out.append(SimpleNamespace(device=device, size_b=size_b, size_gb=size_gb))
    return out


def _get_darwin_devices() -> List[SimpleNamespace]:
    devices = plistlib.loads(_run_cmd(["diskutil", "list", "-plist"], get_output=True).encode("utf-8"))
    out = []
    for device_identifier in devices.get("WholeDisks", []):
        info = plistlib.loads(_run_cmd(["diskutil", "info", "-plist", device_identifier], get_output=True).encode("utf-8"))
        if not info.get("WholeDisk"):
            continue
        if not info.get("RemovableMediaOrExternalDevice"):
            continue
        if not info.get("WritableMedia", True):
            continue
        size_b = info.get("Size")
        device_node = info.get("DeviceNode")
        if not device_node or size_b is None:
            continue
        try:
            size_b = int(size_b)
        except (TypeError, ValueError):
            continue
        size_gb = size_b / float(1024**3)
        out.append(SimpleNamespace(device=device_node, size_b=size_b, size_gb=size_gb))
    return out


def _print_devices_table(devices: List[SimpleNamespace]):
    row_fmt = "{:15s}{:12s}{}"
    print()
    print(row_fmt.format("Name", "Size", "Plugged in"))
    for device in devices:
        # try to get the oldest time between access, modify and change time the device file,
        # that should be a good approximation of the plug-in time (unless the device was used
        # by the user before flashing).
        device_file = pathlib.Path(device.device)
        plugin_time = datetime.fromtimestamp(
            min(device_file.stat().st_ctime, device_file.stat().st_atime, device_file.stat().st_mtime)
        )
        time_since_plugin = _time_diff_txt(plugin_time, datetime.now()) + " ago"
        print(row_fmt.format(device.device, f"{device.size_gb}GB", time_since_plugin))
    print()


def _time_diff_txt(d1, d2) -> str:
    duration_in_s = (d2 - d1).total_seconds()
    days = divmod(duration_in_s, 86400)  # Get days (without [0]!)
    hours = divmod(days[1], 3600)  # Use remainder of days to calc hours
    minutes = divmod(hours[1], 60)  # Use remainder of hours to calc minutes
    seconds = divmod(minutes[1], 1)  # Use remainder of minutes to calc seconds
    parts = []
    for value, unit in zip([days, hours, minutes, seconds], ["day", "hour", "minute", "second"]):
        value = int(value[0])
        if value <= 0:
            continue
        unit = unit if value == 1 else f"{unit}s"
        parts.append(f"{value} {unit}")
    return ", ".join(parts)
