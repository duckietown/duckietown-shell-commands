from utils.cli_utils import get_clean_env, start_command_in_subprocess

INIT_SD_CARD_VERSION = "2.0.5"  # incremental number, semantic version
HYPRIOTOS_STABLE_VERSION = "1.9.0"
HYPRIOTOS_EXPERIMENTAL_VERSION = "1.11.1"

CHANGELOG = (
    """
Current version: %s

Semantic versioning: x.y.z

Breaking changes augment x,
feature additions augment y,
minor changes increment z.

Newest changes applied to this SD CARD:

2.0.5 - 2019-07-07

    Initial boot-up LED feedback: alternating red-green
    during stacks initialization, solid green when ready

2.0.4 - 2019-04-11

    Copy in the default calibrations

2.0.3 - 2018-10-10

    Correct initialization for camera (on is 0 , not 1)


2.0.2 - 2018-10-10

    More documentation.

2.0.1 - 2018-10-10

    Added card version files in /data/stats/init_sd_card

    Set LED config to red

    Fixed config.txt


You can quickly check if something else was done at the URL:

    https://github.com/duckietown/duckietown-shell-commands/blob/master/init_sd_card/command.py


"""
    % INIT_SD_CARD_VERSION
)

import argparse
import datetime
import getpass
import hashlib
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import psutil
import time
from collections import namedtuple, OrderedDict
from os.path import join
from future import builtins
import yaml
from whichcraft import which
import re

from dt_shell import dtslogger, DTCommandAbs
from dt_shell.env_checks import check_docker_environment

USER = getpass.getuser()
TMP_ROOT_MOUNTPOINT = "/media/{USER}/root".format(USER=USER)
TMP_HYPRIOT_MOUNTPOINT = "/media/{USER}/HypriotOS".format(USER=USER)

DISK_HYPRIOTOS = "/dev/disk/by-label/HypriotOS"
DISK_ROOT = "/dev/disk/by-label/root"

DUCKIETOWN_TMP = "/tmp/duckietown"
DOCKER_IMAGES_CACHE_DIR = os.path.join(DUCKIETOWN_TMP, "docker_images")

PHASE_LOADING = "loading"
PHASE_DONE = "done"

SD_CARD_DEVICE = ""
DEFAULT_ROBOT_TYPE = "duckiebot"
MINIMAL_STACKS_TO_LOAD = ['DT18_00_basic']
DEFAULT_STACKS_TO_LOAD = "DT18_00_basic,DT18_01_health,DT18_02_others,DT18_03_interface,DT18_05_core"
DEFAULT_STACKS_TO_RUN = "DT18_00_basic,DT18_01_health,DT18_03_interface"
AIDO_STACKS_TO_LOAD = "DT18_00_basic,DT18_01_health,DT18_05_core"


# TODO: https://raw.githubusercontent.com/duckietown/Software/master18/misc/duckie.art


class InvalidUserInput(Exception):
    pass


from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        parser = argparse.ArgumentParser()

        parser.add_argument(
            "--steps",
            default="flash,expand,mount,setup,unmount",
            help="Steps to perform",
        )

        parser.add_argument("--hostname", required=True)
        parser.add_argument("--linux-username", default="duckie")
        parser.add_argument("--linux-password", default="quackquack")

        parser.add_argument(
            "--stacks-load",
            dest="stacks_to_load",
            default=DEFAULT_STACKS_TO_LOAD,
            help="which stacks to load",
        )
        parser.add_argument(
            "--stacks-run",
            dest="stacks_to_run",
            default=DEFAULT_STACKS_TO_RUN,
            help="which stacks to RUN by default",
        )

        parser.add_argument(
            "--reset-cache",
            dest="reset_cache",
            default=False,
            action="store_true",
            help="Deletes the cached images",
        )

        parser.add_argument(
            "--compress",
            dest="compress",
            default=False,
            action="store_true",
            help="Compress the images - use if you have a 16GB SD card",
        )

        parser.add_argument(
            "--device", dest="device", default="", help="The device with the SD card"
        )

        parser.add_argument(
            "--aido",
            dest="aido",
            default=False,
            action="store_true",
            help="Only load what is necessary for an AI-DO submission",
        )

        # parser.add_argument('--swap', default=False, action='store_true',
        #                     help='Create swap space')
        parser.add_argument(
            "--country", default="US", help="2-letter country code (US, CA, CH, etc.)"
        )
        parser.add_argument(
            "--wifi",
            dest="wifi",
            default="duckietown:quackquack",
            help="""
        Can specify one or more networks: "network:password,network:password,..."

                                    """,
        )

        parser.add_argument("--ethz-username", default=None)
        parser.add_argument("--ethz-password", default=None)

        parser.add_argument(
            "--experimental",
            dest="experimental",
            default=False,
            action="store_true",
            help="Use experimental settings",
        )

        parser.add_argument(
            '--type',
            dest='robot_type',
            default=None,
            choices=['duckiebot', 'watchtower'],
            help='Which type of robot we are setting up'
        )

        parser.add_argument(
            '--online',
            default=False,
            action="store_true",
            help='Whether to flash the images to the SD card'
        )

        parsed = parser.parse_args(args=args)

        global SD_CARD_DEVICE
        SD_CARD_DEVICE = parsed.device

        if parsed.reset_cache:
            dtslogger.info("Removing cache")
            if os.path.exists(DUCKIETOWN_TMP):
                shutil.rmtree(DUCKIETOWN_TMP)

        # if aido is set overwrite the stacks (don't load the base)
        if parsed.aido:
            parsed.stacks_to_load = AIDO_STACKS_TO_LOAD
            parsed.stacks_to_run = parsed.stacks_to_load

        # turn off wifi for type watchtower
        if parsed.robot_type == 'watchtower':
            parsed.wifi = ""

        if ("--online" in args) and ("--stacks-load" in args or "--stacks-run" in args):
            msg = "The option --online cannot be used together with --stacks-load/--stacks-run."
            raise Exception(msg)

        msg = """

## Tips and tricks

### Multiple networks

    dts init_sd_card --wifi network1:password1,network2:password2 --country US



### Steps

Without arguments the script performs the steps:

    flash
    expand
    mount
    setup
    unmount

You can use --steps to run only some of those:

    dts init_sd_card --steps expand,mount



    """
        print(msg)

        if "DOCKER_HOST" in os.environ:
            msg = "Removing DOCKER_HOST from os.environ."
            dtslogger.info(msg)
            os.environ.pop("DOCKER_HOST")

        check_docker_environment()
        check_good_platform()
        check_dependencies()

        if parsed.experimental:
            dtslogger.info("Running experimental mode!")

        if parsed.robot_type is None:
            while True:
                r = input('You did not specify a robot type. Default is "{}". Do you confirm? [y]'.format(DEFAULT_ROBOT_TYPE))
                if r.strip() in ['', 'y', 'Y', 'yes', 'YES', 'yup', 'YUP']:
                    parsed.robot_type = DEFAULT_ROBOT_TYPE
                    break;
                elif r.strip() in ['', 'n', 'N', 'no', 'NO', 'nope', 'NOPE']:
                    dtslogger.info('Please retry while specifying a robot type. Bye bye!')
                    exit(1)

        dtslogger.setLevel(logging.DEBUG)

        steps = parsed.steps.split(",")
        step2function = {
            "flash": step_flash,
            "expand": step_expand,
            "mount": step_mount,
            "setup": step_setup,
            "unmount": step_unmount,
        }

        for step_name in steps:
            if step_name not in step2function:
                msg = "Cannot find step %r in %s" % (step_name, list(step2function))
                raise InvalidUserInput(msg)

            step2function[step_name](shell, parsed)


def step_mount(shell, parsed):
    def refresh():
        cmd = ["sudo", "udevadm", "trigger"]
        _run_cmd(cmd)
        time.sleep(4)

    if not os.path.exists(TMP_HYPRIOT_MOUNTPOINT):
        refresh()
        cmd = ["udisksctl", "mount", "-b", DISK_HYPRIOTOS]
        _run_cmd(cmd)
    if not os.path.exists(TMP_ROOT_MOUNTPOINT):
        refresh()
        cmd = ["udisksctl", "mount", "-b", DISK_ROOT]
        _run_cmd(cmd)


def sync_data():
    # dtslogger.info('Now calling sync() - actually writing data to disk.')
    cmd = ["sync"]
    _run_cmd(cmd)


def step_unmount(shell, parsed):
    sync_data()
    cmd = ["udisksctl", "unmount", "-b", DISK_HYPRIOTOS]
    _run_cmd(cmd)
    cmd = ["udisksctl", "unmount", "-b", DISK_ROOT]
    _run_cmd(cmd)


def check_good_platform():
    p = platform.system().lower()

    if "darwin" in p:
        msg = "This procedure cannot be run on Mac. You need an Ubuntu machine."
        raise Exception(msg)


def friendly_size(b):
    gbs = b / (1024.0 * 1024.0 * 1024.0)
    return "%.3f GB" % gbs


def friendly_size_file(fn):
    s = os.stat(fn).st_size
    return friendly_size(s)


def copy_file(origin, destination, partition='root', overwrite=False):
    buffer_bytes = 100 * 1024 * 1024
    destination0 = destination
    partition = {'root': TMP_ROOT_MOUNTPOINT, 'boot': TMP_HYPRIOT_MOUNTPOINT}[partition]
    destination = destination[1:] if destination.startswith('/') else destination
    destination = os.path.join(partition, destination)
    size = os.stat(origin).st_size
    dtslogger.info(
        "Considering copying %s of size %s to SD:%s" % (origin, friendly_size_file(origin), destination0)
    )
    # create destination dir
    _run_cmd(['sudo', 'mkdir', '-p', os.path.dirname(destination)])
    # check if there is enough space
    available = psutil.disk_usage(partition).free
    dtslogger.info("available %s" % friendly_size(available))
    if available < size + buffer_bytes:
        msg = "You have %s available on %s but need %s for %s" % (
            friendly_size(available),
            partition,
            friendly_size_file(origin),
            origin,
        )
        dtslogger.info(msg)
        return
    dtslogger.info("OK, copying...")
    if os.path.exists(destination) and not overwrite:
        msg = "Skipping copying file that already exist at %s." % destination
        dtslogger.info(msg)
    else:
        if which("rsync"):
            cmd = ["sudo", "rsync", "-avP", origin, destination]
        else:
            cmd = ["sudo", "cp", origin, destination]
        _run_cmd(cmd)
        sync_data()


def step_flash(shell, parsed):
    deps = ["wget", "tar", "udisksctl", "docker", "base64", "gzip", "udevadm", "lsblk"]
    for dep in deps:
        check_program_dependency(dep)

    # Ask for a device  if not set already:
    global SD_CARD_DEVICE
    if SD_CARD_DEVICE == "":
        msg = "Please type the device with your SD card. Please be careful to pick the right device and \
to include '/dev/'. Here's a list of the devices on your system:"
        dtslogger.info(msg)

        script_file = get_resource("list_disks.sh")
        script_cmd = "/bin/bash %s" % script_file
        start_command_in_subprocess(script_cmd)

        msg = "Type the name of your device (include the '/dev' part):   "
        SD_CARD_DEVICE = builtins.input(msg)

    # Check if the device exists
    if not os.path.exists(SD_CARD_DEVICE):
        msg = (
            "Device %s was not found on your system. Maybe you mistyped something."
            % SD_CARD_DEVICE
        )
        raise Exception(msg)

    script_file = get_resource("init_sd_card.sh")
    script_cmd = "/bin/bash %s" % script_file
    env = get_clean_env()
    env["INIT_SD_CARD_DEV"] = SD_CARD_DEVICE
    # pass HypriotOS version to init_sd_card script
    if parsed.experimental:
        env["HYPRIOTOS_VERSION"] = HYPRIOTOS_EXPERIMENTAL_VERSION
    else:
        env["HYPRIOTOS_VERSION"] = HYPRIOTOS_STABLE_VERSION
    start_command_in_subprocess(script_cmd, env)

    dtslogger.info("Waiting 5 seconds for the device to get ready...")
    time.sleep(5)

    dtslogger.info("Partitions created:")
    cmd = ["sudo", "lsblk", SD_CARD_DEVICE]
    _run_cmd(cmd)


def step_expand(shell, parsed):
    deps = ["parted", "resize2fs", "e2fsck", "lsblk", "fdisk", "umount"]
    for dep in deps:
        check_program_dependency(dep)

    global SD_CARD_DEVICE

    if not os.path.exists(SD_CARD_DEVICE):
        msg = "This only works assuming device == %s" % SD_CARD_DEVICE
        raise Exception(msg)
    else:
        msg = "Found device %s." % SD_CARD_DEVICE
        dtslogger.info(msg)

    # Some devices get only a number added to the disk name, other get p + a number
    if os.path.exists(SD_CARD_DEVICE + "1"):
        DEVp1 = SD_CARD_DEVICE + "1"
        DEVp2 = SD_CARD_DEVICE + "2"
    elif os.path.exists(SD_CARD_DEVICE + "p1"):
        DEVp1 = SD_CARD_DEVICE + "p1"
        DEVp2 = SD_CARD_DEVICE + "p2"
    else:
        msg = "The two partitions of device %s could not be found." % SD_CARD_DEVICE
        raise Exception(msg)

    # Unmount the devices and check if this worked, otherwise parted will fail
    p = subprocess.Popen(["lsblk"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ret, err = p.communicate()

    if DEVp1 in ret.decode("utf-8"):
        cmd = ["sudo", "umount", DEVp1]
        _run_cmd(cmd)
    if DEVp2 in ret.decode("utf-8"):
        cmd = ["sudo", "umount", DEVp2]
        _run_cmd(cmd)

    p = subprocess.Popen(["lsblk"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ret, err = p.communicate()

    if DEVp1 in ret.decode("utf-8") or DEVp2 in ret.decode("utf-8"):
        msg = (
            "Automatic unmounting of %s and %s was unsuccessful. Please do it manually and run again."
            % (DEVp1, DEVp2)
        )
        raise Exception(msg)

    # Do the expansion
    dtslogger.info("Current status:")
    cmd = ["sudo", "lsblk", SD_CARD_DEVICE]
    _run_cmd(cmd)

    # get the disk identifier of the SD card (experimental mode only)
    uuid = None
    if parsed.experimental:
        # IMPORTANT: This must be executed before `parted`
        p = re.compile(".*Disk identifier: 0x([0-9a-z]*).*")
        cmd = ["sudo", "fdisk", "-l", SD_CARD_DEVICE]
        dtslogger.debug("$ %s" % cmd)
        pc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        ret, err = pc.communicate()
        m = p.search(ret.decode("utf-8"))
        uuid = m.group(1)

    cmd = ["sudo", "parted", "-s", SD_CARD_DEVICE, "resizepart", "2", "100%"]
    _run_cmd(cmd)

    cmd = ["sudo", "e2fsck", "-f", DEVp2]
    _run_cmd(cmd)

    cmd = ["sudo", "resize2fs", DEVp2]
    _run_cmd(cmd)

    # restore the original disk identifier (experimental mode only)
    if parsed.experimental:
        cmd = ["sudo", "fdisk", SD_CARD_DEVICE]
        dtslogger.debug("$ %s" % cmd)
        p = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE
        )
        ret, err = p.communicate(input=("x\ni\n0x%s\nr\nw" % uuid).encode("ascii"))
        print(ret.decode("utf-8"))

    dtslogger.info("Updated status:")
    cmd = ["sudo", "lsblk", SD_CARD_DEVICE]
    _run_cmd(cmd)


def step_setup(shell, parsed):
    token = shell.get_dt1_token()
    if not os.path.exists(DUCKIETOWN_TMP):
        os.makedirs(DUCKIETOWN_TMP)

    # check_has_space(where=DUCKIETOWN_TMP, min_available_gb=20.0)

    try:
        check_valid_hostname(parsed.hostname)
    except ValueError as e:
        msg = "The string %r is not a valid hostname: %s." % (parsed.hostname, e)
        raise Exception(msg)

    if not os.path.exists(TMP_ROOT_MOUNTPOINT):
        msg = "Disk not mounted: %s" % TMP_ROOT_MOUNTPOINT
        raise Exception(msg)

    if not os.path.exists(TMP_HYPRIOT_MOUNTPOINT):
        msg = "Disk not mounted: %s" % TMP_HYPRIOT_MOUNTPOINT
        raise Exception(msg)

    ssh_key_pri = get_resource("DT18_key_00")
    ssh_key_pub = get_resource("DT18_key_00.pub")
    user_data_file = get_resource("USER_DATA.in.yaml")

    user_data = yaml.load(open(user_data_file).read())

    def add_file(path, content, permissions="0755"):
        d = dict(content=content, path=path, permissions=permissions)

        dtslogger.info("Adding file %s" % path)
        # dtslogger.info('Adding file %s with content:\n---------\n%s\n----------' % (path, content))
        user_data["write_files"].append(d)

    def add_file_local(path, local, permissions="0755"):
        if not os.path.exists(local):
            msg = "Could not find %s" % local
            raise Exception(msg)
        content = open(local).read()
        add_file(path, content, permissions)

    user_data["hostname"] = parsed.hostname
    user_data["users"][0]["name"] = parsed.linux_username
    user_data["users"][0]["plain_text_passwd"] = parsed.linux_password

    user_home_path = "/home/{0}/".format(parsed.linux_username)

    add_file_local(
        path=os.path.join(user_home_path, ".ssh/authorized_keys"), local=ssh_key_pub
    )

    # Configure runcmd
    add_run_cmd(user_data, 'echo "Initialization STARTED"')

    cmd = 'date -s "%s"' % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    add_run_cmd(user_data, cmd)

    add_run_cmd(user_data, "chown -R 1000:1000 {home}".format(home=user_home_path))

    add_run_cmd(user_data, "dd if=/dev/zero of=/swap0 bs=1M count=2048")
    add_run_cmd(user_data, "mkswap /swap0")
    add_run_cmd(user_data, 'echo "/swap0 swap swap" >> /etc/fstab')
    add_run_cmd(user_data, "chmod 0600 /swap0")
    add_run_cmd(user_data, "swapon -a")

    add_run_cmd(user_data, "raspi-config nonint do_camera 0")
    add_run_cmd(user_data, "raspi-config nonint do_i2c 0")

    # Start the blinking feedback: the RPi red and green LEDs will alternately flash
    # on and off until all Docker stacks are up
    cmd = """/bin/bash -c "while ! cat /data/boot-log.txt | grep -q 'All stacks up'; """
    cmd += """do echo 1 | sudo tee /sys/class/leds/led0/brightness > /dev/null; """
    cmd += (
        """echo 0 | sudo tee /sys/class/leds/led1/brightness > /dev/null; sleep 0.5; """
    )
    cmd += """echo 0 | sudo tee /sys/class/leds/led0/brightness > /dev/null; """
    cmd += """echo 1 | sudo tee /sys/class/leds/led1/brightness > /dev/null; sleep 0.5; done; """
    cmd += """echo 1 | sudo tee /sys/class/leds/led0/brightness > /dev/null; """
    cmd += """echo 0 | sudo tee /sys/class/leds/led1/brightness > /dev/null" > /dev/null 2>&1 & """
    add_run_cmd(user_data, cmd)

    # raspi-config nonint do_wifi_country %s"

    # https://www.raspberrypi.org/forums/viewtopic.php?t=21632
    # sudo
    # sudo mkswap /swap0
    # sudo echo "/swap0 swap swap" >> /etc/fstab
    # sudo chmod 0600 /swap0
    # sudo swapon -a
    # DT shell config

    dtshell_config = dict(token_dt1=token)
    add_file(
        path=os.path.join(user_home_path, ".dt-shell/config"),
        content=json.dumps(dtshell_config),
    )
    add_file(path=os.path.join("/secrets/tokens/dt1"), content=token)

    add_file(
        path="/data/stats/init_sd_card/README.txt",
        content="""

The files in this directory:

    version        incremental number
    CHANGELOG      description of latest changes

    flash_time     ISO-formatted date of when this card was flashed
    flash_user     user who flashed
    flash_machine  machine that flashed

    parameters

        hostname       Hostname used for flashing. (Helps checking if it changed.)

    """.strip(),
    )
    add_file(path="/data/stats/init_sd_card/CHANGELOG", content=CHANGELOG)
    add_file(path="/data/stats/init_sd_card/version", content=str(INIT_SD_CARD_VERSION))
    add_file(
        path="/data/stats/init_sd_card/flash_time",
        content=datetime.datetime.now().isoformat(),
    )
    add_file(path="/data/stats/init_sd_card/flash_user", content=getpass.getuser())
    add_file(
        path="/data/stats/init_sd_card/flash_machine", content=socket.gethostname()
    )
    add_file(
        path="/data/stats/init_sd_card/parameters/hostname", content=parsed.hostname
    )
    add_file(
        path="/data/stats/init_sd_card/parameters/linux_username",
        content=parsed.linux_username,
    )
    add_file(
        path="/data/stats/init_sd_card/parameters/stacks_to_run",
        content=parsed.stacks_to_run,
    )
    add_file(
        path="/data/stats/init_sd_card/parameters/stacks_to_load",
        content=parsed.stacks_to_load,
    )
    add_file(
        path="/data/stats/init_sd_card/parameters/compress",
        content=str(int(parsed.compress)),
    )
    add_file(
        path="/data/stats/init_sd_card/parameters/device", content=str(parsed.device)
    )
    add_file(
        path="/data/stats/init_sd_card/parameters/country", content=str(parsed.country)
    )
    add_file(path="/data/stats/init_sd_card/parameters/wifi", content=str(parsed.wifi))
    add_file(
        path="/data/stats/init_sd_card/parameters/ethz_username",
        content=str(parsed.ethz_username),
    )
    add_file(path='/data/stats/init_sd_card/parameters/robot_type', content=str(parsed.robot_type))

    add_file(
        path="/data/stats/MAC/README.txt",
        content="""

Two files will be created in this directory, called "eth0" and "wlan0",
and they will contain the MAC addresses of the two interfaces.

If they are not there, it means that the boot process was interrupted.

    """.strip(),
    )

    # remove non-static services
    user_data['bootcmd'].append('find /etc/avahi/services -type f ! -name "dt.static.*.service" -exec rm -f {} \;')

    # flash static services
    add_file_local(
        '/etc/avahi/services/dt.static.presence.service',
        get_resource(os.path.join('avahi_services', 'dt.presence.service'))
    )
    add_file_local(
        '/etc/avahi/services/dt.static.robot_type.service',
        get_resource(os.path.join('avahi_services', 'dt.robot_type.{}.service'.format(parsed.robot_type)))
    )

    # flash temporary services
    add_file_local(
        '/etc/avahi/services/dt.device-init.service',
        get_resource(os.path.join('avahi_services', 'dt.device-init.service'))
    )

    configure_ssh(parsed, ssh_key_pri, ssh_key_pub)
    configure_networks(parsed, add_file)
    copy_default_calibrations(add_file)

    add_run_cmd(user_data, "cat /sys/class/net/eth0/address > /data/stats/MAC/eth0")
    add_run_cmd(user_data, "cat /sys/class/net/wlan0/address > /data/stats/MAC/wlan0")

    configure_images(parsed, user_data, add_file_local, add_file)

    add_run_cmd(user_data, 'echo "Intialization COMPLETED"')

    user_data_yaml = yaml.dump(user_data, default_flow_style=False)
    user_data_yaml = '#cloud-config\n' + user_data_yaml

    validate_user_data(user_data_yaml)

    write_to_hypriot("user-data", user_data_yaml)

    write_to_hypriot(
        "config.txt",
        """
hdmi_force_hotplug=1
enable_uart=0

# camera settings, see http://elinux.org/RPiconfig#Camera

# enable
start_x=1

disable_camera_led=0

gpu_mem=16

# Enable audio (added by raspberrypi-sys-mods)
dtparam=audio=on

dtparam=i2c1=on
dtparam=i2c_arm=on

            """,
    )
    dtslogger.info("setup step concluded")


def configure_images(parsed, user_data, add_file_local, add_file):
    # read and validate docker-compose stacks
    arg_stacks_to_load = list(filter(lambda s: len(s) > 0, parsed.stacks_to_load.split(",")))
    arg_stacks_to_run = list(filter(lambda s: len(s) > 0, parsed.stacks_to_run.split(",")))
    dtslogger.info("Stacks to load: %s" % arg_stacks_to_load)
    dtslogger.info("Stacks to run: %s" % arg_stacks_to_run)

    # make sure stacks_to_run is a subset of stacks_to_load
    for _ in arg_stacks_to_run:
        if _ not in arg_stacks_to_load:
            msg = "If you want to run %r you need to load it as well." % _
            raise Exception(msg)

    # the device loader expects:
    # - .tar files to be loaded (docker load) in /data/loader/images_to_load
    # - .yaml files to be loaded (parse yaml and load images) in /data/loader/stacks_to_load
    # - .yaml files to be run (docker compose up) at every boot in /data/loader/stacks_to_run

    stacks_for_images_to_load = []
    stacks_to_load = arg_stacks_to_load
    stacks_to_run = arg_stacks_to_run

    if parsed.online:
        # online:
        # - only minimal configuration gets copied to the SD card
        stacks_for_images_to_load = MINIMAL_STACKS_TO_LOAD
        # load everything (but the minimal)
        stacks_to_load = [_ for _ in arg_stacks_to_load if _ not in MINIMAL_STACKS_TO_LOAD]
    else:
        # offline:
        # - all the selected images get copied to the SD card
        stacks_for_images_to_load = stacks_to_load
        stacks_to_load = []

    # export images to tar files
    stack2yaml = get_stack2yaml(
        stacks_for_images_to_load, get_resource("stacks")
    )
    stack2info = save_images(stack2yaml, compress=parsed.compress)

    # copy images to SD card
    stacks_written = []
    stack2archive_rpath = {}
    dtslogger.debug(stack2info)
    for stack, stack_info in stack2info.items():
        tgz = stack_info.archive
        rpath = os.path.join("data", "loader", "images_to_load", os.path.basename(tgz))
        copy_file(tgz, rpath)
        stack2archive_rpath[stack] = os.path.join("/", rpath)
        stacks_written.append(stack)

    # copy stacks_to_load and stacks_to_run to SD card
    for stack_type, stacks_deck in {'load': stacks_to_load, 'run': stacks_to_run}.items():
        for cf in stacks_deck:
            # local path
            lpath = get_resource(os.path.join("stacks", cf + ".yaml"))
            # path on PI
            rpath = "/data/loader/stacks_to_{}/{}.yaml".format(stack_type, cf)

            if which("docker-compose") is None:
                msg = "Could not find docker-compose. Cannot validate file."
                dtslogger.error(msg)
            else:
                _run_cmd(["docker-compose", "-f", lpath, "config", "--quiet"])

            copy_file(lpath, rpath)

    client = check_docker_environment()

    stacks_not_to_run = [_ for _ in stacks_to_load if _ not in stacks_to_run]

    order = stacks_to_run + stacks_not_to_run

    for cf in order:

        if (cf in stacks_written) and (cf in MINIMAL_STACKS_TO_LOAD):

            log_current_phase(
                user_data, PHASE_LOADING, "Stack %s: Loading containers" % cf
            )

            cmd = "docker load --input %s && rm %s" % (
                stack2archive_rpath[cf],
                stack2archive_rpath[cf],
            )
            add_run_cmd(user_data, cmd)

            add_file(
                stack2archive_rpath[cf] + ".labels.json",
                json.dumps(stack2info[cf].image_name2id, indent=4),
            )

            for image_name, image_id in stack2info[cf].image_name2id.items():
                image = client.images.get(image_name)
                image_id = str(image.id)
                dtslogger.info("id for %s: %s" % (image_name, image_id))
                cmd = ["docker", "tag", image_id, image_name]
                print(cmd)
                add_run_cmd(user_data, cmd)

            if cf in stacks_to_run:
                msg = "Adding the stack %r as default running" % cf
                dtslogger.info(msg)

                log_current_phase(
                    user_data, PHASE_LOADING, "Stack %s: docker-compose up" % cf
                )
                cmd = [
                    "docker-compose",
                    "--file",
                    "/data/loader/stacks_to_run/%s.yaml" % cf,
                    "-p",
                    cf,
                    "up",
                    "-d",
                ]
                add_run_cmd(user_data, cmd)
                user_data["bootcmd"].append(cmd)  # every boot

    # NOTE: The RPi blinking feedback expects that "All stacks up" will be written to the /data/boot-log.txt file.
    # If modifying, make sure to adjust the blinking feedback


def configure_networks(parsed, add_file):
    # TODO: make configurable
    DUCKSSID = parsed.hostname + "-wifi"
    DUCKPASS = "quackquack"
    add_file(
        path="/var/local/wificfg.json",
        content="""
{{
  "dnsmasq_cfg": {{
     "address": "/#/192.168.27.1",
     "dhcp_range": "192.168.27.100,192.168.27.150,1h",
     "vendor_class": "set:device,IoT"
  }},
  "host_apd_cfg": {{
     "ip": "192.168.27.1",
     "ssid": "{DUCKSSID}",
     "wpa_passphrase": "{DUCKPASS}",
     "channel": "6"
  }},
  "wpa_supplicant_cfg": {{
     "cfg_file": "/etc/wpa_supplicant/wpa_supplicant.conf"
  }}
}}
    """.format(
            DUCKSSID=DUCKSSID, DUCKPASS=DUCKPASS
        ),
    )
    wpa_supplicant = """

ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country={country}

    """.format(
        country=parsed.country
    )
    networks = interpret_wifi_string(parsed.wifi)
    for connection in networks:
        wpa_supplicant += """
network={{
  id_str="{cname}"
  ssid="{WIFISSID}"
  psk="{WIFIPASS}"
  key_mgmt=WPA-PSK
}}
                """.format(
            WIFISSID=connection.ssid,
            cname=connection.name,
            WIFIPASS=connection.password,
        )

    if parsed.ethz_username:
        if parsed.ethz_password is None:
            msg = "You should provide a password for ETH account using --ethz-password."
            raise Exception(msg)

        wpa_supplicant += """

network={{
    id_str="eth_network"
    ssid="eth"
    key_mgmt=WPA-EAP
    group=CCMP TKIP
    pairwise=CCMP TKIP
    eap=PEAP
    proto=RSN
    identity="{username}"
    password="{password}"
    phase1="peaplabel=0"
    phase2="auth=MSCHAPV2"
    priority=1
}}

    """.format(
            username=parsed.ethz_username, password=parsed.ethz_password
        )

    add_file(path="/etc/wpa_supplicant/wpa_supplicant.conf", content=wpa_supplicant)


def configure_ssh(parsed, ssh_key_pri, ssh_key_pub):
    ssh_dir = os.path.expanduser("~/.ssh")
    if not os.path.exists(ssh_dir):
        os.makedirs(ssh_dir)

    ssh_key_pri_copied = os.path.join(ssh_dir, "DT18_key_00")
    ssh_key_pub_copied = os.path.join(ssh_dir, "DT18_key_00.pub")

    if not os.path.exists(ssh_key_pri_copied):
        shutil.copy(ssh_key_pri, ssh_key_pri_copied)
    if not os.path.exists(ssh_key_pub_copied):
        shutil.copy(ssh_key_pub, ssh_key_pub_copied)
    os.chmod(ssh_key_pri_copied, 0o600)

    ssh_config = os.path.join(ssh_dir, "config")
    if not os.path.exists(ssh_config):
        msg = "Could not find ssh config file %s" % ssh_config
        dtslogger.info(msg)
        current = ""
    else:

        current = open(ssh_config).read()

    bit = """

# --- init_sd_card generated ---

# Use the key for all hosts
IdentityFile {IDENTITY}

Host {HOSTNAME}
    User {DTS_USERNAME}
    Hostname {HOSTNAME}.local
    IdentityFile {IDENTITY}
    StrictHostKeyChecking no
# ------------------------------

    """.format(
        HOSTNAME=parsed.hostname,
        IDENTITY=ssh_key_pri_copied,
        DTS_USERNAME=parsed.linux_username,
    )

    if bit not in current:
        dtslogger.info("Updating ~/.ssh/config with: " + bit)
        with open(ssh_config, "a") as f:
            f.write(bit)
    else:
        dtslogger.info("Configuration already found in ~/.ssh/config")


def copy_default_calibrations(add_file):
    kin_calib = get_resource("calib_kin_default.yaml")
    ext_cam_calib = get_resource("calib_cam_ext_default.yaml")
    int_cam_calib = get_resource("calib_cam_int_default.yaml")

    kin_calib_file = open(kin_calib)
    ext_cam_calib_file = open(ext_cam_calib)
    int_cam_calib_file = open(int_cam_calib)

    add_file(
        path="/data/config/calibrations/kinematics/default.yaml",
        content=yaml.dump(yaml.load(kin_calib_file), default_flow_style=False),
    )
    add_file(
        path="/data/config/calibrations/camera_extrinsic/default.yaml",
        content=yaml.dump(yaml.load(ext_cam_calib_file), default_flow_style=False),
    )
    add_file(
        path="/data/config/calibrations/camera_intrinsic/default.yaml",
        content=yaml.dump(yaml.load(int_cam_calib_file), default_flow_style=False),
    )


def _run_cmd(cmd):
    dtslogger.debug("$ %s" % cmd)
    subprocess.check_call(cmd)


def check_program_dependency(exe):
    p = which(exe)
    if p is None:
        msg = "Could not find program %r" % exe
        raise Exception(msg)
    dtslogger.debug("Found %r at %s" % (exe, p))


def check_dependencies():
    try:
        import psutil
    except ImportError as e:
        msg = "This program requires psutil: %s" % e
        msg += "\n\tapt install python-psutil"
        msg += "\n\tpip install --user psutil"
        raise Exception(msg)


def get_resource(filename):
    script_files = os.path.dirname(os.path.realpath(__file__))

    script_file = join(script_files, filename)

    if not os.path.exists(script_file):
        msg = "Could not find script %s" % script_file
        raise Exception(msg)
    return script_file


def check_valid_hostname(hostname):
    import re

    # https://stackoverflow.com/questions/2532053/validate-a-hostname-string
    if len(hostname) > 253:
        raise ValueError("Hostname too long")

    allowed = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)
    if not allowed.match(hostname):
        msg = "Invalid chars in %r" % hostname
        raise ValueError(msg)

    if "-" in hostname:
        msg = (
            'Cannot use the hostname %r. It cannot contain "-" because of a ROS limitation. '
            % hostname
        )
        raise ValueError(msg)

    if len(hostname) < 3:
        msg = "This hostname is too short. Choose something more descriptive."
        raise ValueError(msg)


Wifi = namedtuple("Wifi", "ssid password name")


# import tempfile
#
#
# def write_to_root(rpath, contents):
#     if not os.path.exists(TMP_ROOT_MOUNTPOINT):
#         msg = 'Disk not mounted: %s' % TMP_ROOT_MOUNTPOINT
#         raise Exception(msg)
#     # for some reason it is mounted as root
#
#     dest = os.path.join(TMP_ROOT_MOUNTPOINT, rpath)
#     d = os.path.dirname(dest)
#     if not os.path.exists(d):
#         # os.makedirs(d)
#         cmd = ['sudo', 'mkdirs', d]
#         _run_cmd(cmd)
#     t = tempfile.mktemp()
#     with open(t, 'w') as f:
#         f.write(contents)
#
#     cmd = ['sudo', 'cp', t, dest]
#     _run_cmd(cmd)
#     dtslogger.info('Written to %s' % dest)
#     os.unlink(t)


def write_to_hypriot(rpath, contents):
    if not os.path.exists(TMP_HYPRIOT_MOUNTPOINT):
        msg = "Disk not mounted: %s" % TMP_HYPRIOT_MOUNTPOINT
        raise Exception(msg)
    x = os.path.join(TMP_HYPRIOT_MOUNTPOINT, rpath)
    d = os.path.dirname(x)
    if not os.path.exists(d):
        os.makedirs(d)
    with open(x, "w") as f:
        f.write(contents)
    dtslogger.info("Written to %s" % x)


def interpret_wifi_string(s):
    results = []
    if len(s.strip()) == 0:
        return []
    for i, connection in enumerate(s.split(",")):
        tokens = connection.split(":")
        if len(tokens) != 2:
            msg = "Invalid wifi string %r" % s
            raise Exception(msg)
        wifissid, wifipass = tokens
        wifissid = wifissid.strip()
        wifipass = wifipass.strip()
        name = "network%d" % (i + 1)
        results.append(Wifi(wifissid, wifipass, name))
    return results


StackInfo = namedtuple("StackInfo", "archive image_name2id hname")


def save_images(stack2yaml, compress):
    """
        returns stack2info
    """
    cache_dir = DOCKER_IMAGES_CACHE_DIR
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    client = check_docker_environment()

    stack2info = {}

    for cf, config in stack2yaml.items():
        image_name2id = {}
        for service, service_config in config["services"].items():
            image_name = service_config["image"]
            dtslogger.info("Pulling %s" % image_name)
            cmd = ["docker", "pull", image_name]
            _run_cmd(cmd)
            image = client.images.get(image_name)
            image_id = str(image.id)
            image_name2id[image_name] = image_id

        hname = get_md5("-".join(sorted(list(image_name2id.values()))))[:8]

        if compress:
            destination = os.path.join(cache_dir, cf + "-" + hname + ".tar.gz")
        else:
            destination = os.path.join(cache_dir, cf + "-" + hname + ".tar")

        destination0 = os.path.join(cache_dir, cf + "-" + hname + ".tar")

        stack2info[cf] = StackInfo(
            archive=destination, image_name2id=image_name2id, hname=hname
        )

        if os.path.exists(destination):
            msg = "Using cached file %s" % destination
            dtslogger.info(msg)
            continue

        dtslogger.info("Saving to %s" % destination0)
        cmd = ["docker", "save", "-o", destination0] + list(image_name2id.values())
        _run_cmd(cmd)
        if compress:
            cmd = ["gzip", "-f", destination0]
            _run_cmd(cmd)

            assert not os.path.exists(destination0)
            assert os.path.exists(destination)
        else:
            assert destination == destination0

        msg = "Saved archive %s of size %s" % (
            destination,
            friendly_size_file(destination),
        )
        dtslogger.info(msg)

    assert len(stack2info) == len(stack2yaml)
    return stack2info


def log_current_phase(user_data, phase, msg):
    # NOTE: double json.dumps to add escaped quotes
    j = json.dumps(json.dumps(dict(phase=phase, msg=msg)))
    cmd = "echo %s >> /data/boot-log.txt" % j
    user_data["runcmd"].append(cmd)


def add_run_cmd(user_data, cmd):
    # PRE action (NOTE: double json.dumps to add escaped quotes)
    pre_json = json.dumps(json.dumps(dict(cmd=cmd, msg='running command', pos=len(user_data['runcmd']))))
    cmd_pre = 'echo %s >> /data/command.json' % pre_json
    user_data['runcmd'].append(cmd_pre)
    # COMMAND
    user_data['runcmd'].append(cmd)
    # POST action (NOTE: double json.dumps to add escaped quotes)
    post_json = json.dumps(json.dumps(dict(cmd=cmd, msg='finished command', pos=len(user_data['runcmd']))))
    cmd_post = 'echo %s >> /data/command.json' % post_json
    user_data['runcmd'].append(cmd_post)


def get_stack2yaml(stacks, base):
    names = os.listdir(base)
    all_stacks = [os.path.splitext(_)[0] for _ in names if _.endswith("yaml")]
    dtslogger.info("The stacks that are available are: %s" % ", ".join(all_stacks))
    dtslogger.info("You asked to use %s" % stacks)
    use = []
    for s in stacks:
        if s not in all_stacks:
            msg = "Cannot find stack %r in %s" % (s, all_stacks)
            raise Exception(msg)
        use.append(s)

    stacks2yaml = OrderedDict()
    for sn in use:
        lpath = join(base, sn + ".yaml")
        if not os.path.exists(lpath):
            raise Exception(lpath)

        stacks2yaml[sn] = yaml.load(open(lpath).read())
    return stacks2yaml


def validate_user_data(user_data_yaml):
    if "VARIABLE" in user_data_yaml:
        msg = "Invalid user_data_yaml:\n" + user_data_yaml
        msg += "\n\nThe above contains VARIABLE"
        raise Exception(msg)

    try:
        import requests
    except ImportError:
        msg = 'Skipping validation because "requests" not installed.'
        dtslogger.warning(msg)
    else:
        url = "https://validate.core-os.net/validate"
        r = requests.put(url, data=user_data_yaml)
        info = json.loads(r.content.decode("utf-8"))
        result = info["result"]
        nerrors = 0
        for x in result:
            kind = x["kind"]
            line = x["line"]
            message = x["message"]
            m = "Invalid at line %s: %s" % (line, message)
            m += "| %s" % user_data_yaml.split("\n")[line - 1]

            if kind == "error":
                dtslogger.error(m)
                nerrors += 1
            else:
                ignore = [
                    "bootcmd",
                    "package_upgrade",
                    "runcmd",
                    "ssh_pwauth",
                    "sudo",
                    "chpasswd",
                    "lock_passwd",
                    "plain_text_passwd",
                ]
                show = False
                for i in ignore:
                    if 'unrecognized key "%s"' % i in m:
                        break
                else:
                    show = True
                if show:
                    dtslogger.warning(m)
        if nerrors:
            msg = "There are %d errors: exiting" % nerrors
            raise Exception(msg)


class NotEnoughSpace(Exception):
    pass


def check_has_space(where, min_available_gb):
    try:
        import psutil
    except ImportError:
        msg = "Skipping disk check because psutil not installed."
        dtslogger.info(msg)
    else:
        disk = psutil.disk_usage(where)
        disk_available_gb = disk.free / (1024 * 1024 * 1024.0)

        if disk_available_gb < min_available_gb:
            msg = (
                "This procedure requires that you have at least %f GB of memory."
                % min_available_gb
            )
            msg += "\nYou only have %.2f GB available on %s." % (
                disk_available_gb,
                where,
            )
            dtslogger.error(msg)
            raise NotEnoughSpace(msg)
        else:
            msg = "You have %.2f GB available on %s. " % (disk_available_gb, where)
            dtslogger.info(msg)


def get_md5(contents):
    m = hashlib.md5()
    m.update(contents.encode("utf-8"))
    s = m.hexdigest()
    return s
