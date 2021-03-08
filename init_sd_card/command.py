import argparse
import copy
import getpass
import json
import os
import pathlib
import re
import sys
import shutil
import subprocess
import time
import socket
from collections import namedtuple
from math import log2, floor
from types import SimpleNamespace
from typing import List

from datetime import datetime

from dt_shell import DTShell, dtslogger, DTCommandAbs, __version__ as shell_version
from utils.cli_utils import ProgressBar, ask_confirmation, check_program_dependency
from utils.duckietown_utils import \
    get_robot_types, \
    get_robot_configurations, \
    get_robot_hardware, \
    WIRED_ROBOT_TYPES
from utils.misc_utils import human_time, sudo_open

from .constants import (
    TIPS_AND_TRICKS,
    LIST_DEVICES_CMD,
    WPA_OPEN_NETWORK_CONFIG,
    WPA_PSK_NETWORK_CONFIG,
    WPA_EAP_NETWORK_CONFIG,
)

INIT_SD_CARD_VERSION = "2.1.0"  # incremental number, semantic version

Wifi = namedtuple("Wifi", "name ssid psk username password")

TMP_WORKDIR = "/tmp/duckietown/dts/init_sd_card"
BLOCK_SIZE = 1024 ** 2
SAFE_SD_SIZE_MIN = 16
SAFE_SD_SIZE_MAX = 64
DEFAULT_ROBOT_TYPE = "duckiebot"
DEFAULT_WIFI_CONFIG = "duckietown:quackquack"
COMMAND_DIR = os.path.dirname(os.path.abspath(__file__))
SUPPORTED_STEPS = ["license", "download", "flash", "verify", "setup"]
NVIDIA_LICENSE_FILE = os.path.join(COMMAND_DIR, "nvidia-license.txt")
ROOT_PARTITIONS = ["root", "APP"]


def DISK_IMAGE_VERSION(robot_configuration, experimental=False):
    board_to_disk_image_version = {
        "raspberry_pi": {
            "stable": "1.2.1",
            "experimental": "1.2.1"
        },
        "jetson_nano_4gb": {
            "stable": "1.2.0",
            "experimental": "1.2.0"
        },
        "jetson_nano_2gb": {
            "stable": "1.2.1",
            "experimental": "1.2.2"
        },
    }
    board, _ = get_robot_hardware(robot_configuration)
    stream = "stable" if not experimental else "experimental"
    return board_to_disk_image_version[board][stream]


def PLACEHOLDERS_VERSION(robot_configuration, experimental=False):
    board_to_placeholders_version = {
        "raspberry_pi": {
            "1.0": "1.0",
            "1.1": "1.1",
            "1.1.1": "1.1",
            "1.1.2": "1.1",
            "1.2.0": "1.1",
            "1.2.1": "1.1"
        },
        "jetson_nano_4gb": {
            "1.2.0": "1.1",
            "1.2.1": "1.1"
        },
        "jetson_nano_2gb": {
            "1.2.0": "1.1",
            "1.2.1": "1.1",
            "1.2.2": "1.1"
        },
    }
    board, _ = get_robot_hardware(robot_configuration)
    version = DISK_IMAGE_VERSION(robot_configuration, experimental)
    return board_to_placeholders_version[board][version]


def BASE_DISK_IMAGE(robot_configuration, experimental=False):
    board_to_disk_image = {
        "raspberry_pi":
            f"dt-hypriotos-rpi-v{DISK_IMAGE_VERSION(robot_configuration, experimental)}",
        "jetson_nano_4gb":
            f"dt-nvidia-jetpack-v{DISK_IMAGE_VERSION(robot_configuration, experimental)}-4gb",
        "jetson_nano_2gb":
            f"dt-nvidia-jetpack-v{DISK_IMAGE_VERSION(robot_configuration, experimental)}-2gb",
    }
    board, _ = get_robot_hardware(robot_configuration)
    return board_to_disk_image[board]


def DISK_IMAGE_CLOUD_LOCATION(robot_configuration, experimental=False):
    disk_image = BASE_DISK_IMAGE(robot_configuration, experimental)
    return f"disk_image/{disk_image}.zip"


class InvalidUserInput(Exception):
    pass


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        parser = argparse.ArgumentParser()
        # configure parser
        parser.add_argument("--steps", default=",".join(SUPPORTED_STEPS), help="Steps to perform")
        parser.add_argument("--no-steps", default="", help="Steps NOT to perform")
        parser.add_argument("--hostname", required=True, help="Hostname of the device to flash")
        parser.add_argument("--device", default=None, help="The SD card device to flash")
        parser.add_argument("--country", default="US",
                            help="2-letter country code (US, CA, CH, etc.)")
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
            "--no-cache", default=False, action="store_true",
            help="Whether to use cached ISO image"
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
            "--workdir", default=TMP_WORKDIR, type=str,
            help="(Optional) temporary working directory to use"
        )
        # parse arguments
        parsed = parser.parse_args(args=args)
        # validate hostname
        if not _validate_hostname(parsed.hostname):
            return
        # default WiFi
        if parsed.wifi is None:
            if parsed.robot_type in WIRED_ROBOT_TYPES:
                parsed.wifi = ""
            else:
                parsed.wifi = DEFAULT_WIFI_CONFIG
        # make sure the token is set
        # noinspection PyBroadException
        try:
            shell.get_dt1_token()
        except Exception:
            dtslogger.error("You have not set a token for this shell.\n"
                            "You can get a token from the following URL,\n\n"
                            "\thttps://www.duckietown.org/site/your-token   \n\n"
                            "and set it using the following command,\n\n"
                            "\tdts tok set\n")
            return
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

        # fetch given steps
        steps = parsed.steps.split(",")
        no_steps = parsed.no_steps.split(",")
        steps = [s for s in steps if s not in no_steps]
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
        base_disk_image = BASE_DISK_IMAGE(parsed.robot_configuration, parsed.experimental)
        # compile files destinations
        in_file = lambda e: os.path.join(parsed.workdir, f"{base_disk_image}.{e}")
        # prepare data
        data = {
            "robot_configuration": parsed.robot_configuration,
            "disk_zip": in_file("zip"),
            "disk_img": in_file("img"),
            "disk_metadata": in_file("json"),
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
    board, _ = get_robot_hardware(parsed.robot_configuration)
    if board.startswith("jetson_nano"):
        # ask to either agree or go away
        while True:
            answer = ask_confirmation(
                f"This disk image uses the Nvidia Jetpack OS. By proceeding, "
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
                dtslogger.error("You must explicitly agree to the License first.")
                exit(8)
    return {}


def step_download(shell, parsed, data):
    # check if dependencies are met
    check_program_dependency("unzip")

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
        disk_image = DISK_IMAGE_CLOUD_LOCATION(parsed.robot_configuration, parsed.experimental)
        # download zip
        shell.include.data.get.command(
            shell, [],
            parsed=SimpleNamespace(object=[disk_image], file=[data["disk_zip"]], space="public")
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
    check_program_dependency("sudo")
    check_program_dependency("lsblk")
    check_program_dependency("umount")
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
                if txt.strip() == 'q':
                    dtslogger.info('Exiting')
                    exit()
                sd_size = int(txt)
                assert sd_size > 0
            except (ValueError, AssertionError):
                continue
            standard = log2(sd_size) - floor(log2(sd_size)) == 0
            if not (SAFE_SD_SIZE_MIN <= sd_size <= SAFE_SD_SIZE_MAX) or not standard:
                answer = ask_confirmation(f"You are indicating a non standard size: {sd_size}GB",
                                          default="n", question="Proceed?")
                if not answer:
                    dtslogger.info('Exiting')
                    exit()
            break
        # get all available devices
        devices_all = _get_devices()
        # all device with size within 20% of the given size are a match
        devices_fit = list(filter(
            lambda d: abs(d.size_gb - sd_size) < (0.2 * sd_size), devices_all
        ))
        # if there is any fit, show them
        if devices_fit:
            print(f"The following devices were found (size ~{sd_size}GB):")
            _print_devices_table(devices_fit)
        else:
            answer = ask_confirmation(f"No devices were found with a size of ~{sd_size}GB.",
                                      question="Do you want to see all the disks available?",
                                      default="n")
            if not answer:
                dtslogger.info("Sounds good! Exiting...")
                exit()
            # show all
            dtslogger.warn("Be aware that picking the wrong device might result in irreversible "
                           "damage to your operating system or data loss.")
            print("\nThe following devices are available:")
            _print_devices_table(devices_all)

        device = None
        while device is None:
            msg = "Type the name of your device: "
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
            dtslogger.info(f'Trying to unmount all partitions from device {parsed.device}')
            cmd = f"for n in {parsed.device}* ; do umount $n || . ; done"
            _run_cmd(cmd, shell=True, quiet=True)
            dtslogger.info('All partitions unmounted.')
        except BaseException:
            dtslogger.warn("An error occurred while unmounting the partitions of your SD card. "
                           "Though this is not critical, you might experience issues with your SD "
                           "card after flashing is complete. If that is the case, make sure to "
                           "unmount all disks from your SD card before flashing the next time.")

    # use dd to flash
    dtslogger.info("Flashing File[{}] -> {}[{}]:".format(data["disk_img"], sd_type, parsed.device))
    dd_py = os.path.join(pathlib.Path(__file__).parent.absolute(), 'dd.py')
    bsize = str(BLOCK_SIZE)
    dd_cmd = (["sudo"] if sd_type == "SD" else []) + [
        dd_py, "--input", data["disk_img"], "--output", parsed.device, "--block-size", bsize
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
            with sudo_open(parsed.device, "rb") as destination:
                buffer1 = origin.read(buf_size)
                while buffer1:
                    buf1_len = len(buffer1)
                    buffer2 = destination.read(buf1_len)
                    buf2_len = len(buffer2)
                    # check lengths, then content
                    if buf1_len != buf2_len or buffer1 != buffer2:
                        raise IOError(
                            "Mismatch in range position [{}-{}]".format(nbytes, nbytes + buf1_len))
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
            "The verification step failed. Please, try re-flashing.\n" 
            "The error reads:\n\n{}".format(
                str(e))
        )
        exit(5)
    dtslogger.info("Verified in {}".format(human_time(time.time() - stime)))
    # ---
    dtslogger.info("{}[{}] successfully flashed!".format(data.get("sd_type", ""), parsed.device))
    return {}


def step_setup(shell, parsed, data):
    # check if dependencies are met
    check_program_dependency("dd")
    check_program_dependency("sudo")
    check_program_dependency("sync")

    # compile data used to format placeholders
    surgery_data = {
        "hostname": parsed.hostname,
        "robot_type": parsed.robot_type,
        "token": shell.get_dt1_token(),
        "robot_configuration": parsed.robot_configuration,
        "wpa_networks": _get_wpa_networks(parsed),
        "wpa_country": parsed.country,
        "sanitize_files": None,
        "stats": json.dumps(
            {
                "steps": {step: bool(step in parsed.steps) for step in SUPPORTED_STEPS},
                "base_disk_name": BASE_DISK_IMAGE(parsed.robot_configuration, parsed.experimental),
                "base_disk_version": DISK_IMAGE_VERSION(parsed.robot_configuration,
                                                        parsed.experimental),
                "base_disk_location": DISK_IMAGE_CLOUD_LOCATION(
                    parsed.robot_configuration, parsed.experimental
                ),
                "environment": {
                    "hostname": socket.gethostname(),
                    "user": getpass.getuser(),
                    "shell_version": shell_version,
                    "commands_version": shell.get_commands_version(),
                    "init_sd_card_version": INIT_SD_CARD_VERSION,
                },
                "parameters": parsed.__dict__,
                "stamp": time.time(),
                "stamp_human": datetime.now().isoformat(),
            },
            indent=4,
            sort_keys=True,
        ),
    }
    # read disk metadata
    with open(data["disk_metadata"], "rt") as fin:
        disk_metadata = json.load(fin)
    # get surgery plan
    surgery_plan = disk_metadata["surgery_plan"]
    # compile list of files to sanitize at first boot
    sanitize = map(lambda s: s["path"],
                   filter(lambda s: s["partition"] in ROOT_PARTITIONS, surgery_plan))
    surgery_data["sanitize_files"] = "\n".join(map(lambda f: f'dt-sanitize-file "{f}"', sanitize))
    # get disk image placeholders
    placeholders_version = PLACEHOLDERS_VERSION(parsed.robot_configuration, parsed.experimental)
    placeholders_dir = os.path.join(COMMAND_DIR, "placeholders", f"v{placeholders_version}")
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
        dd_cmd = (["sudo"] if data.get("sd_type", "SD") == "SD" else []) + [
            "dd",
            "of={}".format(parsed.device),
            "bs=1",
            "count={}".format(block_size),
            "seek={}".format(block_offset),
            "conv=notrunc",
        ]
        # write twice (found to increase success rate)
        for wpass in range(2):
            # launch dd
            dd = subprocess.Popen(dd_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            dtslogger.debug(f"[{wpass + 1}/2] $ {dd_cmd}")
            # write
            dd.stdin.write(masked_content)
            dd.stdin.flush()
            dd.stdin.close()
            dd.wait()
            # flush I/O buffer
            _run_cmd(["sync"])
    dtslogger.info("Surgery went OK!")
    # flush I/O buffer
    dtslogger.info("Flushing I/O buffer...")
    _run_cmd(["sync"])
    dtslogger.info("Done!")
    # ---
    return {}


def _validate_hostname(hostname):
    if not re.match('^[a-zA-Z0-9]+$', hostname):
        dtslogger.error('The hostname can only contain alphanumeric symbols [a-z,A-Z,0-9].')
        return False
    return True


def _interpret_wifi_string(s):
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


def _get_wpa_networks(parsed):
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
        outputs = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    else:
        outputs = {}
    # ---
    if get_output:
        return subprocess.check_output(cmd, shell=shell, env=env).decode("utf-8")
    else:
        subprocess.check_call(cmd, shell=shell, env=env, **outputs)


def _get_devices() -> List[SimpleNamespace]:
    units = {
        'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3, 'T': 1024 ** 4
    }
    lsblk = _run_cmd(LIST_DEVICES_CMD, get_output=True, shell=True)
    out = []
    for line in lsblk.split('\n'):
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
            size_gb = size_b / units['G']
            out.append(SimpleNamespace(
                device=device,
                size_b=size_b,
                size_gb=size_gb
            ))
    return out


def _print_devices_table(devices: List[SimpleNamespace]):
    row_fmt = "{:15s}{:12s}{}"
    print()
    print(row_fmt.format("Name", "Size", "Plugged in"))
    for device in devices:
        # try to get the creation time of the device file, that should be the plug-in time
        device_file = pathlib.Path(device.device)
        plugin_time = datetime.fromtimestamp(device_file.stat().st_ctime)
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
    for value, unit in zip([days, hours, minutes, seconds], ['day', 'hour', 'minute', 'second']):
        value = int(value[0])
        if value <= 0:
            continue
        unit = unit if value == 1 else f"{unit}s"
        parts.append(f"{value} {unit}")
    return ", ".join(parts)
