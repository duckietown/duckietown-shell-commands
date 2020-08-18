import argparse
import getpass
import json
import os
import sys
import shutil
import subprocess
import time
import socket
from collections import namedtuple
from future import builtins
from datetime import datetime

from dt_shell import DTShell, dtslogger, DTCommandAbs, __version__ as shell_version
from utils.cli_utils import ProgressBar, ask_confirmation, check_program_dependency
from utils.duckietown_utils import get_robot_types, get_robot_configurations

from .constants import \
    TIPS_AND_TRICKS, \
    LIST_DEVICES_CMD, \
    INPUT_DEVICE_MSG, \
    WPA_OPEN_NETWORK_CONFIG, \
    WPA_PSK_NETWORK_CONFIG, \
    WPA_EAP_NETWORK_CONFIG

INIT_SD_CARD_VERSION = "2.0.5"  # incremental number, semantic version

Wifi = namedtuple("Wifi", "name ssid psk username password")

TMP_WORKDIR = "/tmp/duckietown/dts/init_sd_card"
DD_BLOCK_SIZE = "64K"
BASE_DISK_IMAGE = "dt-hypriotos-rpi-v1.11.1"
DISK_IMAGE_URL = \
    f"https://duckietown-public-storage.s3.amazonaws.com/disk_image/{BASE_DISK_IMAGE}.zip"
DEFAULT_ROBOT_TYPE = "duckiebot"
DEFAULT_WIFI_CONFIG = "duckietown:quackquack"
COMMAND_DIR = os.path.dirname(os.path.abspath(__file__))
SUPPORTED_STEPS = ['download', 'flash', 'verify', 'setup']
WIRED_ROBOT_TYPES = ['watchtower', 'traffic_light', 'town']


class InvalidUserInput(Exception):
    pass


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        parser = argparse.ArgumentParser()
        # configure parser
        parser.add_argument(
            "--steps",
            default=','.join(SUPPORTED_STEPS),
            help="Steps to perform"
        )
        parser.add_argument(
            "--hostname",
            required=True,
            help="Hostname of the device to flash"
        )
        parser.add_argument(
            "--linux-username",
            default="duckie",
            help="Username of the linux user to create on the flashed device"
        )
        parser.add_argument(
            "--linux-password",
            default="quackquack",
            help="Password to access the linux user profile created on the flashed device"
        )
        parser.add_argument(
            "--device",
            default=None,
            help="The SD card device to flash"
        )
        parser.add_argument(
            "--country",
            default="US",
            help="2-letter country code (US, CA, CH, etc.)"
        )
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
            
            """
        )
        parser.add_argument(
            '--type',
            dest='robot_type',
            default=None,
            choices=get_robot_types(),
            help="Which type of robot we are setting up"
        )
        parser.add_argument(
            '--configuration',
            dest='robot_configuration',
            default=None,
            help="Which configuration your robot is in"
        )
        parser.add_argument(
            "--no-cache",
            default=False,
            action='store_true',
            help="Whether to use cached ISO image"
        )
        parser.add_argument(
            "--workdir",
            default=TMP_WORKDIR,
            type=str,
            help="(Optional) temporary working directory to use"
        )
        # parse arguments
        parsed = parser.parse_args(args=args)
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
                dtslogger.info('Please retry while specifying a robot type. Bye bye!')
                exit(1)
        dtslogger.info(f'Robot type: {parsed.robot_type}')
        # get the robot configuration
        allowed_configs = get_robot_configurations(parsed.robot_type)
        if parsed.robot_configuration is None:
            dtslogger.info(f"You did not specify a robot configuration.\n"
                           f"Given that your robot is a {parsed.robot_type}, possible "
                           f"configurations are: {', '.join(allowed_configs)}")
            # ---
            while True:
                r = input("Insert your robot's configuration: ")
                if r.strip() in allowed_configs:
                    parsed.robot_configuration = r.strip()
                    break
                dtslogger.warning(f"Configuration '{r}' not recognized. Please, retry.")
        # validate robot configuration
        if parsed.robot_configuration not in allowed_configs:
            dtslogger.error(f"Robot configuration {parsed.robot_configuration} not recognized "
                            f"for robot type {parsed.robot_type}. Possible configurations "
                            f"are: {', '.join(allowed_configs)}")
            exit(2)
        dtslogger.info(f'Robot configuration: {parsed.robot_configuration}')

        # fetch given steps
        steps = parsed.steps.split(",")
        step2function = {
            "download": step_download,
            "flash": step_flash,
            "verify": step_verify,
            "setup": step_setup
        }
        # validate steps
        for step_name in steps:
            if step_name not in step2function:
                msg = "Cannot find step %r in %s" % (step_name, list(step2function))
                raise InvalidUserInput(msg)
        # perform steps
        data = {}
        for step_name in steps:
            data.update(step2function[step_name](shell, parsed, data))
        # ---
        if 'flash' in steps:
            dtslogger.info('Flashing completed successfully!')
            if data['sd_type'] == 'SD':
                dtslogger.info(f'You can now unplug the SD card '
                               f'and put it inside a {parsed.robot_type.title()}. Have fun!')


def step_download(shell, parsed, data):
    # check if dependencies are met
    check_program_dependency("wget")
    check_program_dependency("unzip")

    # clear cache (if requested)
    if parsed.no_cache:
        dtslogger.info("Clearing cache")
        if os.path.exists(parsed.workdir):
            if parsed.workdir != TMP_WORKDIR:
                dtslogger.warn("A custom working directory is being used. The flag "
                               "--no-cache does not have an effect in this case.")
            else:
                shutil.rmtree(parsed.workdir)
    # create temporary dir
    _run_cmd(['mkdir', '-p', parsed.workdir])
    # compile files destinations
    out_file = lambda e: os.path.join(parsed.workdir, f"{BASE_DISK_IMAGE}.{e}")
    # download zip (if necessary)
    dtslogger.info('Looking for ZIP image file...')
    if not os.path.isfile(out_file('zip')):
        dtslogger.info('Downloading ZIP image...')
        try:
            _run_cmd(['wget', '--no-verbose', '--show-progress',
                      '--output-document', out_file('zip'), DISK_IMAGE_URL])
        except KeyboardInterrupt:
            dtslogger.info('Deleting partial ZIP file...')
            _run_cmd(['rm', out_file('zip')])
            exit(3)
    else:
        dtslogger.info(f"Reusing cached ZIP image file [{out_file('zip')}].")
    # unzip (if necessary)
    if not os.path.isfile(out_file('img')):
        dtslogger.info('Extracting ZIP image...')
        _run_cmd(['unzip', out_file('zip'), '-d', parsed.workdir])
    else:
        dtslogger.info(f"Reusing cached DISK image file [{out_file('img')}].")
    # ---
    return {
        'disk_img': out_file('img'),
        'disk_metadata': out_file('json')
    }


def step_flash(shell, parsed, data):
    # check if dependencies are met
    check_program_dependency("dd")
    check_program_dependency("sudo")
    check_program_dependency("lsblk")
    check_program_dependency("sync")

    # ask for a device if not set already
    if parsed.device is None:
        dtslogger.info(INPUT_DEVICE_MSG)
        _run_cmd(LIST_DEVICES_CMD, shell=True)
        msg = "Type the name of your device (include the '/dev' part):   "
        parsed.device = builtins.input(msg)

    # check if the device exists
    if parsed.device.startswith('/dev/'):
        sd_type = 'SD'
        if not os.path.exists(parsed.device):
            msg = "Device %s was not found on your system. Please, check." % parsed.device
            raise InvalidUserInput(msg)
    else:
        sd_type = 'File'
        if os.path.exists(parsed.device):
            msg = "File %s already exists, " % parsed.device + \
                  "if you continue, the file will be overwritten."
            granted = ask_confirmation(msg)
            if not granted:
                dtslogger.info('Please retry while specifying a valid device. Bye bye!')
                exit(4)

    # use dd to flash
    dtslogger.info('Flashing [{}] -> {}[{}]:'.format(data['disk_img'], sd_type, parsed.device))
    dd_cmd = (['sudo'] if sd_type == 'SD' else []) + [
        'dd', 'if={}'.format(data['disk_img']), 'of={}'.format(parsed.device),
        'bs={}'.format(DD_BLOCK_SIZE), 'status=progress'
    ]

    # create a progress bar to track the progress
    pbar = ProgressBar()
    tbytes = os.stat(data['disk_img']).st_size

    # launch dd
    dd = subprocess.Popen(dd_cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    dtslogger.debug(f"$ {dd_cmd}")

    # read status and update progress bar
    par = b""
    while dd.poll() is None:
        time.sleep(.5)
        # consume everything from the buffer
        char = dd.stderr.read(1)
        while len(char) == 1:
            if par is not None:
                par += char
            if char == b'\r':
                par = b""
            if char == b' ' and par is not None:
                try:
                    nbytes = float(par.decode('utf-8'))
                    progress = int(100 * (nbytes / tbytes))
                    pbar.update(progress)
                except ValueError:
                    pass
                par = None
            # get next char
            char = dd.stderr.read(1)
    # jump to 100% if success
    if dd.returncode == 0:
        pbar.update(100)

    # flush I/O buffer
    dtslogger.info('Flushing I/O buffer...')
    _run_cmd(['sync'])
    dtslogger.info('Done!')
    # ---
    dtslogger.info('{}[{}] flashed!'.format(sd_type, parsed.device))
    return {'sd_type': sd_type}


def step_verify(shell, parsed, data):
    dtslogger.info('Verifying {}[{}]...'.format(data.get('sd_type', ''), parsed.device))
    buf_size = 4096
    # create a progress bar to track the progress
    pbar = ProgressBar()
    tbytes = os.stat(data['disk_img']).st_size
    nbytes = 0
    # compare bytes
    try:
        with open(data['disk_img'], 'rb') as origin:
            with _sudo_open(parsed.device, 'rb') as destination:
                buffer1 = origin.read(buf_size)
                while buffer1:
                    buf1_len = len(buffer1)
                    buffer2 = destination.read(buf1_len)
                    buf2_len = len(buffer2)
                    # check lengths, then content
                    if buf1_len != buf2_len or buffer1 != buffer2:
                        raise IOError(
                            'Mismatch in range position [{}-{}]'.format(nbytes, nbytes + buf1_len)
                        )
                    # update progress bar
                    nbytes += buf1_len
                    progress = int(100 * (nbytes / tbytes))
                    pbar.update(progress)
                    # read another chunk
                    buffer1 = origin.read(buf_size)
    except IOError as e:
        sys.stdout.write('\n')
        sys.stdout.flush()
        dtslogger.error('The verification step failed. Please, try re-flashing.\n'
                        'The error reads:\n\n{}'.format(str(e)))
        exit(5)
    # ---
    dtslogger.info('{}[{}] successfully flashed!'.format(data.get('sd_type', ''), parsed.device))
    return {}


def step_setup(shell, parsed, data):
    # check if dependencies are met
    check_program_dependency("dd")
    check_program_dependency("sudo")
    check_program_dependency("sync")

    # compile data used to format placeholders
    surgery_data = {
        'hostname': parsed.hostname,
        'robot_type': parsed.robot_type,
        'token': shell.get_dt1_token(),
        'robot_configuration': parsed.robot_configuration,
        'wpa_networks': _get_wpa_networks(parsed),
        'wpa_country': parsed.country,
        'files_sanitize': None,
        'linux_username': parsed.linux_username,
        'linux_password': parsed.linux_password,
        'stats': json.dumps({
            'steps': {
                step: bool(step in parsed.steps) for step in SUPPORTED_STEPS
            },
            'input_name': BASE_DISK_IMAGE,
            'input_url': DISK_IMAGE_URL,
            'environment': {
                'hostname': socket.gethostname(),
                'user': getpass.getuser(),
                'shell_version': shell_version,
                'commands_version': shell.get_commands_version(),
                'init_sd_card_version': INIT_SD_CARD_VERSION
            },
            'parameters': parsed.__dict__,
            'stamp': time.time(),
            'stamp_human': datetime.now().isoformat()
        }, indent=4, sort_keys=True)
    }
    # read disk metadata
    with open(data['disk_metadata'], 'rt') as fin:
        disk_metadata = json.load(fin)
    # get surgery plan
    surgery_plan = disk_metadata['surgery_plan']
    # compile list of files to sanitize at first boot
    sanitize = map(lambda s: s['path'], filter(lambda s: s['partition'] == 'root', surgery_plan))
    surgery_data['files_sanitize'] = '\n'.join(map(lambda f: f'  - sanitize-file {f}', sanitize))
    # get disk image placeholders
    placeholders_dir = os.path.join(COMMAND_DIR, 'placeholders', f'v{disk_metadata["version"]}')
    # perform surgery
    dtslogger.info('Performing surgery on the SD card...')
    for surgery_bit in surgery_plan:
        dtslogger.info('Performing surgery on [{partition}]:{path}.'.format(**surgery_bit))
        # get placeholder info
        surgery_bit['placeholder'] = surgery_bit['placeholder']
        placeholder_file = os.path.join(placeholders_dir, surgery_bit['placeholder'])
        # make sure that the placeholder exists
        if not os.path.isfile(placeholder_file):
            print(placeholder_file)
            dtslogger.error(f"The placeholder {surgery_bit['placeholder']} is not recognized.")
            exit(6)
        # load placeholder file format
        with open(placeholder_file, 'rt') as fin:
            placeholder_fmt = fin.read()
        # create real (unmasked) content
        content = placeholder_fmt.format(**surgery_data).encode()
        used_bytes = len(content)
        block_size = surgery_bit['length_bytes']
        block_offset = surgery_bit['offset_bytes']
        # make sure the content does not exceed the block size
        if used_bytes > block_size:
            dtslogger.error(f"Content for placeholder {surgery_bit['placeholder']} exceeding the "
                            f'allocated space of {block_size} bytes.')
            exit(7)
        # create masked content (content is padded with new lines)
        masked_content = content + b'\n' * (block_size - used_bytes)
        # debug only
        assert len(masked_content) == block_size
        block_usage = int(100 * (used_bytes / float(block_size)))
        dtslogger.debug('Injecting {}/{} bytes ({}%) '.format(used_bytes, block_size, block_usage)
                        + 'into [{partition}]:{path}.'.format(**surgery_bit))
        # apply change
        dd_cmd = (['sudo'] if data.get('sd_type', 'SD') == 'SD' else []) + [
            'dd', 'of={}'.format(parsed.device), 'bs=1',
            'count={}'.format(block_size),
            'seek={}'.format(block_offset),
            'conv=notrunc'
        ]
        # launch dd
        dd = subprocess.Popen(dd_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        dtslogger.debug(f"$ {dd_cmd}")
        # write
        dd.stdin.write(masked_content)
        dd.stdin.flush()
        dd.stdin.close()
        dd.wait()
        # flush I/O buffer
        _run_cmd(['sync'])
    dtslogger.info('Surgery went OK!')
    # flush I/O buffer
    dtslogger.info('Flushing I/O buffer...')
    _run_cmd(['sync'])
    dtslogger.info('Done!')
    # ---
    return {}


def _sudo_open(filepath, *args, **kwargs):
    proc = subprocess.Popen(['sudo', 'cat', filepath], stdout=subprocess.PIPE)
    return proc.stdout


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
                password=connection.password
            )
            continue
        # PSK-secured network
        if connection.psk is not None:
            wpa_networks += WPA_PSK_NETWORK_CONFIG.format(
                cname=connection.name,
                ssid=connection.ssid,
                psk=connection.psk
            )
            continue
        # open network
        wpa_networks += WPA_OPEN_NETWORK_CONFIG.format(
            cname=connection.name,
            ssid=connection.ssid
        )
    # ---
    return wpa_networks


def _run_cmd(cmd, get_output=False, shell=False):
    dtslogger.debug("$ %s" % cmd)
    # turn [cmd] into "cmd" if shell is set to True
    if isinstance(cmd, list) and shell:
        cmd = ' '.join(cmd)
    # ---
    if get_output:
        return subprocess.check_output(cmd, shell=shell).decode('utf-8')
    else:
        subprocess.check_call(cmd, shell=shell)
