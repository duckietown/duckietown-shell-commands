from __future__ import print_function

import argparse
import datetime
import getpass
import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from collections import namedtuple, OrderedDict
from os.path import join

import yaml
from whichcraft import which

from dt_shell import dtslogger, DTCommandAbs
from dt_shell.env_checks import check_docker_environment

USER = getpass.getuser()
TMP_ROOT_MOUNTPOINT = "/media/{USER}/root".format(USER=USER)
TMP_HYPRIOT_MOUNTPOINT = "/media/{USER}/HypriotOS".format(USER=USER)

DISK_HYPRIOTOS = '/dev/disk/by-label/HypriotOS'
DISK_ROOT = '/dev/disk/by-label/root'

DUCKIETOWN_TMP = '/tmp/duckietown'
DOCKER_IMAGES_CACHE_DIR = os.path.join(DUCKIETOWN_TMP, 'docker_images')

PHASE_LOADING = 'loading'
PHASE_DONE = 'done'

SD_CARD_DEVICE = ""

# TODO: https://raw.githubusercontent.com/duckietown/Software/master18/misc/duckie.art


class InvalidUserInput(Exception):
    pass


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        parser = argparse.ArgumentParser()

        parser.add_argument('--steps', default="flash,expand,mount,setup,unmount",
                            help="Steps to perform")

        parser.add_argument('--hostname', default='duckiebot')
        parser.add_argument('--linux-username', default='duckie')
        parser.add_argument('--linux-password', default='quackquack')

        parser.add_argument('--stacks-load', dest="stacks_to_load",
                            default="DT18_00_basic,DT18_01_health_stats,DT18_02_others,DT18_05_duckiebot_base",
                            help="which stacks to load")
        parser.add_argument('--stacks-run', dest="stacks_to_run", default="DT18_00_basic,DT18_01_health_stats",
                            help="which stacks to RUN by default")

        parser.add_argument('--reset-cache', dest='reset_cache', default=False, action='store_true',
                            help='Deletes the cached images')

        parser.add_argument('--compress', dest='compress', default=False, action='store_true',
                            help='Compress the images - use if you have a 16GB SD card')

        parser.add_argument('--device', dest='device', default='',
                            help='The device with the SD card')

        # parser.add_argument('--swap', default=False, action='store_true',
        #                     help='Create swap space')
        parser.add_argument('--country', default="US",
                            help="2-letter country code (US, CA, CH, etc.)")
        parser.add_argument('--wifi', dest="wifi", default='duckietown:quackquack',
                            help="""
        Can specify one or more networks: "network:password,network:password,..."

                                    """)

        parser.add_argument('--ethz-username', default=None)
        parser.add_argument('--ethz-password', default=None)

        parsed = parser.parse_args(args=args)

        global SD_CARD_DEVICE
        SD_CARD_DEVICE = parsed.device

        if parsed.reset_cache:
            dtslogger.info('Removing cache')
            if os.path.exists(DUCKIETOWN_TMP):
                shutil.rmtree(DUCKIETOWN_TMP)

        msg = """

## Tips and tricks

### Multiple networks

    dts init_sd_card2 --wifi  network1:password1,network2:password2 --country US



### Steps

Without arguments the script performs the steps:

    flash
    expand
    mount
    setup
    unmount

You can use --steps to run only some of those:

    dts init_sd_card2 --steps expand,mount



    """
        print(msg)

        if 'DOCKER_HOST' in os.environ:
            msg = 'Removing DOCKER_HOST from os.environ.'
            dtslogger.info(msg)
            os.environ.pop('DOCKER_HOST')

        check_docker_environment()
        check_good_platform()
        check_dependencies()

        dtslogger.setLevel(logging.DEBUG)

        steps = parsed.steps.split(',')
        step2function = {
            'flash': step_flash,
            'expand': step_expand,
            'mount': step_mount,
            'setup': step_setup,
            'unmount': step_unmount
        }

        for step_name in steps:
            if step_name not in step2function:
                msg = 'Cannot find step %r in %s' % (step_name, list(step2function))
                raise InvalidUserInput(msg)

            step2function[step_name](shell, parsed)


def step_mount(shell, parsed):
    def refresh():
        cmd = ['sudo', 'udevadm', 'trigger']
        _run_cmd(cmd)
        time.sleep(4)

    if not os.path.exists(TMP_HYPRIOT_MOUNTPOINT):
        refresh()
        cmd = ['udisksctl', 'mount', '-b', DISK_HYPRIOTOS]
        _run_cmd(cmd)
    if not os.path.exists(TMP_ROOT_MOUNTPOINT):
        refresh()
        cmd = ['udisksctl', 'mount', '-b', DISK_ROOT]
        _run_cmd(cmd)


def sync_data():
    # dtslogger.info('Now calling sync() - actually writing data to disk.')
    cmd = ['sync']
    _run_cmd(cmd)


def step_unmount(shell, parsed):
    sync_data()
    cmd = ['udisksctl', 'unmount', '-b', DISK_HYPRIOTOS]
    _run_cmd(cmd)
    cmd = ['udisksctl', 'unmount', '-b', DISK_ROOT]
    _run_cmd(cmd)


def check_good_platform():
    p = platform.system().lower()

    if 'darwin' in p:
        msg = 'This procedure cannot be run on Mac. You need an Ubuntu machine.'
        raise Exception(msg)


def step_flash(shell, parsed):
    deps = ['wget', 'tar', 'udisksctl', 'docker', 'base64', 'gzip', 'udevadm', 'lsblk']
    for dep in deps:
        check_program_dependency(dep)

    # Ask for a device  if not set already:
    global SD_CARD_DEVICE
    if SD_CARD_DEVICE == '':
        msg = 'Please type the device with your SD card. Please be careful to pick the right device and \
to include \'/dev/\'. Here\'s a list of the devices on your system:'
        dtslogger.info(msg)

        script_file = get_resource('list_disks.sh')
        script_cmd = '/bin/bash %s' % script_file
        env = get_environment_clean()
        ret = subprocess.call(script_cmd, shell=True, env=env,
                              stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout)

        SD_CARD_DEVICE = raw_input("Type the name of your device (include the \'/dev\' part):")


    # Check if the device exists
    if not os.path.exists(SD_CARD_DEVICE):
        msg = 'Device %s was not found on your system. Maybe you mistyped something.' % SD_CARD_DEVICE
        raise Exception(msg)

    script_file = get_resource('init_sd_card2.sh')
    script_cmd = '/bin/bash %s' % script_file
    env = get_environment_clean()
    env['INIT_SD_CARD_DEV'] = SD_CARD_DEVICE
    ret = subprocess.call(script_cmd, shell=True, env=env,
                          stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout)
    if ret == 0:
        dtslogger.info('Done!')
    else:
        msg = ('An error occurred while initializing the SD card, please check and try again (%s).' % ret)
        raise Exception(msg)


def get_environment_clean():
    env = {}

    # add other environment
    env.update(os.environ)

    # remove DOCKER_HOST if present
    if 'DOCKER_HOST' in env:
        r = env['DOCKER_HOST']
        msg = 'I will IGNORE the DOCKER_HOST variable that is currently set to %r' % r
        dtslogger.warning(msg)
        env.pop('DOCKER_HOST')
    return env


def step_expand(shell, parsed):
    check_program_dependency('parted')
    check_program_dependency('resize2fs')
    check_program_dependency('df')
    check_program_dependency('umount')

    global SD_CARD_DEVICE

    if not os.path.exists(SD_CARD_DEVICE):
        msg = 'This only works assuming device == %s' % SD_CARD_DEVICE
        raise Exception(msg)
    else:
        msg = 'Found device %s.' % SD_CARD_DEVICE
        dtslogger.info(msg)

    # Some devices get only a number added to the disk name, other get p + a number
    if os.path.exists(SD_CARD_DEVICE+'1'):
        DEVp1 = SD_CARD_DEVICE + '1'
        DEVp2 = SD_CARD_DEVICE + '2'
    elif os.path.exists(SD_CARD_DEVICE+'p1'):
        DEVp1 = SD_CARD_DEVICE + 'p1'
        DEVp2 = SD_CARD_DEVICE + 'p2'
    else:
        msg = 'The second partition of device %s could not be found.' % SD_CARD_DEVICE
        raise Exception(msg)

    # Unmount the devices and check if this worked, otherwise parted will fail
    p = subprocess.Popen(['df', '-h'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ret, err = p.communicate()
    if DEVp1 in ret:
        cmd = ['sudo', 'umount', DEVp1]
        _run_cmd(cmd)
    if DEVp2 in ret:
        cmd = ['sudo', 'umount', DEVp2]
        _run_cmd(cmd)

    p = subprocess.Popen(['df', '-h'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ret, err = p.communicate()
    if DEVp1 in ret or DEVp2 in ret:
        msg = 'Automatic unmounting of %s and %s was unsuccessful. Please do it manually and run again.' % (DEVp1, DEVp2)
        raise Exception(msg)

    # Do the expansion
    dtslogger.info('Current status:')
    cmd = ['sudo', 'lsblk', SD_CARD_DEVICE]
    _run_cmd(cmd)
    cmd = ['sudo', 'parted', '-s', SD_CARD_DEVICE, 'resizepart', '2', '100%']
    _run_cmd(cmd)
    cmd = ['sudo', 'e2fsck', '-f', DEVp2]
    _run_cmd(cmd)
    cmd = ['sudo', 'resize2fs', DEVp2]
    _run_cmd(cmd)
    dtslogger.info('Updated status:')
    cmd = ['sudo', 'lsblk', SD_CARD_DEVICE]
    _run_cmd(cmd)


def step_setup(shell, parsed):
    token = shell.get_dt1_token()
    if not os.path.exists(DUCKIETOWN_TMP):
        os.makedirs(DUCKIETOWN_TMP)

    # check_has_space(where=DUCKIETOWN_TMP, min_available_gb=20.0)

    try:
        check_valid_hostname(parsed.hostname)
    except ValueError as e:
        msg = 'The string %r is not a valid hostname: %s.' % (parsed.hostname, e)
        raise Exception(msg)

    if not os.path.exists(TMP_ROOT_MOUNTPOINT):
        msg = 'Disk not mounted: %s' % TMP_ROOT_MOUNTPOINT
        raise Exception(msg)

    if not os.path.exists(TMP_HYPRIOT_MOUNTPOINT):
        msg = 'Disk not mounted: %s' % TMP_HYPRIOT_MOUNTPOINT
        raise Exception(msg)

    ssh_key_pri = get_resource('DT18_key_00')
    ssh_key_pub = get_resource('DT18_key_00.pub')
    user_data_file = get_resource('USER_DATA.in.yaml')

    user_data = yaml.load(open(user_data_file).read())

    def add_file(path, content, permissions="0755"):
        d = dict(content=content, path=path, permissions=permissions)

        dtslogger.info('Adding file %s' % path)
        # dtslogger.info('Adding file %s with content:\n---------\n%s\n----------' % (path, content))
        user_data['write_files'].append(d)

    def add_file_local(path, local, permissions="0755"):
        if not os.path.exists(local):
            msg = 'Could not find %s' % local
            raise Exception(msg)
        content = open(local).read()
        add_file(path, content, permissions)

    user_data['hostname'] = parsed.hostname
    user_data['users'][0]['name'] = parsed.linux_username
    user_data['users'][0]['plain_text_passwd'] = parsed.linux_password

    user_home_path = '/home/{0}/'.format(parsed.linux_username)

    add_file_local(path=os.path.join(user_home_path, '.ssh/authorized_keys'),
                   local=ssh_key_pub)

    cmd = 'date -s "%s"' % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    user_data['runcmd'].append(cmd)

    user_data['runcmd'].append("chown -R 1000:1000 {home}".format(home=user_home_path))

    add_run_cmd(user_data, 'dd if=/dev/zero of=/swap0 bs=1M count=1024')
    add_run_cmd(user_data, 'mkswap /swap0')
    add_run_cmd(user_data, 'echo "/swap0 swap swap" >> /etc/fstab')
    add_run_cmd(user_data, 'chmod 0600 /swap0')
    add_run_cmd(user_data, 'swapon -a')

    add_run_cmd(user_data, 'raspi-config nonint do_camera 1')
    add_run_cmd(user_data, 'raspi-config nonint do_i2c 1')
    # raspi-config nonint do_wifi_country %s"

    # https://www.raspberrypi.org/forums/viewtopic.php?t=21632
    # sudo
    # sudo mkswap /swap0
    # sudo echo "/swap0 swap swap" >> /etc/fstab
    # sudo chmod 0600 /swap0
    # sudo swapon -a
    # DT shell config

    dtshell_config = dict(token_dt1=token)
    add_file(path=os.path.join(user_home_path, '.dt-shell/config'),
             content=json.dumps(dtshell_config))
    add_file(path=os.path.join('/secrets/tokens/dt1'),
             content=token)

    configure_ssh(parsed, ssh_key_pri, ssh_key_pub)
    configure_networks(parsed, add_file)

    user_data['runcmd'].append('cat /sys/class/net/eth0/address > /data/eth0-mac')
    user_data['runcmd'].append('cat /sys/class/net/wlan0/address > /data/wlan0-mac')

    configure_images(parsed, user_data, add_file_local, add_file)

    user_data_yaml = '#cloud-config\n' + yaml.dump(user_data, default_flow_style=False)

    validate_user_data(user_data_yaml)

    write_to_hypriot('user-data', user_data_yaml)

    write_to_hypriot('config.txt', '''
hdmi_force_hotplug=1
enable_uart=0

# camera settings, see http://elinux.org/RPiconfig#Camera
start_x=1
disable_camera_led=1
gpu_mem=16

# Enable audio (added by raspberrypi-sys-mods)
dtparam=audio=on

dtparam=i2c1=on
dtparam=i2c_arm=on

            ''')
    dtslogger.info('setup step concluded')


def friendly_size(b):
    gbs = b / (1024.0 * 1024.0 * 1024.0)
    return '%.3f GB' % gbs


def friendly_size_file(fn):
    s = os.stat(fn).st_size
    return friendly_size(s)


def configure_images(parsed, user_data, add_file_local, add_file):
    import psutil
    # read and validate duckiebot-compose
    stacks_to_load = parsed.stacks_to_load.split(',')
    stacks_to_run = parsed.stacks_to_run.split(',')
    dtslogger.info('Stacks to load: %s' % stacks_to_load)
    dtslogger.info('Stacks to run: %s' % stacks_to_run)
    for _ in stacks_to_run:
        if _ not in stacks_to_load:
            msg = 'If you want to run %r you need to load it as well.' % (_)
            raise Exception(msg)

    for cf in stacks_to_load:
        # local path
        lpath = get_resource(os.path.join('stacks', cf + '.yaml'))
        # path on PI
        rpath = '/var/local/%s.yaml' % cf

        if which('docker-compose') is None:
            msg = 'Could not find docker-compose. Cannot validate file.'
            dtslogger.error(msg)
        else:
            _run_cmd(['docker-compose', '-f', lpath, 'config', '--quiet'])

        add_file_local(path=rpath, local=lpath)

    stack2yaml = get_stack2yaml(stacks_to_load, get_resource('stacks'))
    if not stack2yaml:
        msg = 'Not even one stack specified'
        raise Exception(msg)

    stack2info = save_images(stack2yaml, compress=parsed.compress)

    buffer_bytes = 100 * 1024 * 1024
    stacks_written = []
    stack2archive_rpath = {}
    dtslogger.debug(stack2info)

    for stack, stack_info in stack2info.items():
        tgz = stack_info.archive
        size = os.stat(tgz).st_size
        dtslogger.info('Considering copying %s of size %s' % (tgz, friendly_size_file(tgz)))

        rpath = os.path.join('var', 'local', os.path.basename(tgz))
        destination = os.path.join(TMP_ROOT_MOUNTPOINT, rpath)
        available = psutil.disk_usage(TMP_ROOT_MOUNTPOINT).free
        dtslogger.info('available %s' % friendly_size(available))
        if available < size + buffer_bytes:
            msg = 'You have %s available on %s but need %s for %s' % (
                friendly_size(available), TMP_ROOT_MOUNTPOINT, friendly_size_file(tgz), tgz)
            dtslogger.info(msg)
            continue

        dtslogger.info('OK, copying, and loading it on first boot.')
        if os.path.exists(destination):
            msg = 'Skipping copying image that already exist at %s.' % destination
            dtslogger.info(msg)
        else:
            if which('rsync'):
                cmd = ['sudo', 'rsync', '-avP', tgz, destination]
            else:
                cmd = ['sudo', 'cp', tgz, destination]
            _run_cmd(cmd)
            sync_data()

        stack2archive_rpath[stack] = os.path.join('/', rpath)

        stacks_written.append(stack)

    import docker
    client = docker.from_env()

    stacks_not_to_run = [_ for _ in stacks_to_load if _ not in stacks_to_run]

    order = stacks_to_run + stacks_not_to_run

    for cf in order:

        if cf in stacks_written:

            log_current_phase(user_data, PHASE_LOADING,
                              "Stack %s: Loading containers" % cf)

            cmd = 'docker load --input %s && rm %s' % (stack2archive_rpath[cf], stack2archive_rpath[cf])
            add_run_cmd(user_data, cmd)

            add_file(stack2archive_rpath[cf]+'.labels.json',
                     json.dumps(stack2info[cf].image_name2id, indent=4))
            # cmd = ['docker', 'load', '--input', stack2archive_rpath[cf]]
            # add_run_cmd(user_data, cmd)
            # cmd = ['rm', stack2archive_rpath[cf]]
            # add_run_cmd(user_data, cmd)

            for image_name, image_id in stack2info[cf].image_name2id.items():
                image = client.images.get(image_name)
                image_id = str(image.id)
                dtslogger.info('id for %s: %s' % (image_name, image_id))
                cmd = ['docker', 'tag', image_id, image_name]
                print(cmd)
                add_run_cmd(user_data, cmd)

            if cf in stacks_to_run:
                msg = 'Adding the stack %r as default running' % cf
                dtslogger.info(msg)

                log_current_phase(user_data, PHASE_LOADING, "Stack %s: docker-compose up" % (cf))
                cmd = ['docker-compose', '--file', '/var/local/%s.yaml' % cf, '-p', cf, 'up', '-d']
                add_run_cmd(user_data, cmd)
                # XXX
                cmd = ['docker-compose', '-p', cf, '--file', '/var/local/%s.yaml' % cf, 'up', '-d']
                user_data['bootcmd'].append(cmd)  # every boot

    log_current_phase(user_data, PHASE_DONE, "All stacks up")


def configure_networks(parsed, add_file):
    # TODO: make configurable
    DUCKSSID = parsed.hostname + '-wifi'
    DUCKPASS = 'quackquack'
    add_file(path="/var/local/wificfg.json",
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
    """.format(DUCKSSID=DUCKSSID, DUCKPASS=DUCKPASS))
    wpa_supplicant = """

ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country={country}

    """.format(country=parsed.country)
    networks = interpret_wifi_string(parsed.wifi)
    for connection in networks:
        wpa_supplicant += """
network={{
  id_str="{cname}"
  ssid="{WIFISSID}"
  psk="{WIFIPASS}"
  key_mgmt=WPA-PSK
}}
                """.format(WIFISSID=connection.ssid,
                           cname=connection.name, WIFIPASS=connection.password)

    if parsed.ethz_username:
        if parsed.ethz_password is None:
            msg = 'You should provide a password for ETH account using --ethz-password.'
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

    """.format(username=parsed.ethz_username, password=parsed.ethz_password)

    add_file(path="/etc/wpa_supplicant/wpa_supplicant.conf",
             content=wpa_supplicant)


def configure_ssh(parsed, ssh_key_pri, ssh_key_pub):
    ssh_dir = os.path.expanduser('~/.ssh')
    if not os.path.exists(ssh_dir):
        os.makedirs(ssh_dir)

    ssh_key_pri_copied = os.path.join(ssh_dir, 'DT18_key_00')
    ssh_key_pub_copied = os.path.join(ssh_dir, 'DT18_key_00.pub')

    if not os.path.exists(ssh_key_pri_copied):
        shutil.copy(ssh_key_pri, ssh_key_pri_copied)
    if not os.path.exists(ssh_key_pub_copied):
        shutil.copy(ssh_key_pub, ssh_key_pub_copied)

    ssh_config = os.path.join(ssh_dir, 'config')
    if not os.path.exists(ssh_config):
        msg = ('Could not find ssh config file %s' % ssh_config)
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

    """.format(HOSTNAME=parsed.hostname, IDENTITY=ssh_key_pri_copied, DTS_USERNAME=parsed.linux_username)

    if bit not in current:
        dtslogger.info('Updating ~/.ssh/config with: ' + bit)
        with open(ssh_config, 'a') as f:
            f.write(bit)
    else:
        dtslogger.info('Configuration already found in ~/.ssh/config')


def _run_cmd(cmd):
    dtslogger.debug('$ %s' % cmd)
    subprocess.check_call(cmd)


def check_program_dependency(exe):
    p = which(exe)
    if p is None:
        msg = 'Could not find program %r' % exe
        raise Exception(msg)
    dtslogger.debug('Found %r at %s' % (exe, p))


def check_dependencies():
    try:
        import psutil
    except ImportError as e:
        msg = 'This program requires psutil: %s' % e
        msg += '\n\tapt install python-psutil'
        msg += '\n\tpip install --user psutil'
        raise Exception(msg)


def get_resource(filename):
    script_files = os.path.dirname(os.path.realpath(__file__))

    script_file = join(script_files, filename)

    if not os.path.exists(script_file):
        msg = 'Could not find script %s' % script_file
        raise Exception(msg)
    return script_file


def check_valid_hostname(hostname):
    import re
    # https://stackoverflow.com/questions/2532053/validate-a-hostname-string
    if len(hostname) > 253:
        raise ValueError('Hostname too long')

    allowed = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)
    if not allowed.match(hostname):
        msg = 'Invalid chars in %r' % hostname
        raise ValueError(msg)

    if '-' in hostname:
        msg = 'Cannot use the hostname %r. It cannot contain "-" because of a ROS limitation. ' % hostname
        raise ValueError(msg)

    if len(hostname) < 3:
        msg = 'This hostname is too short. Choose something more descriptive.'
        raise ValueError(msg)


Wifi = namedtuple('Wifi', 'ssid password name')


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
        msg = 'Disk not mounted: %s' % TMP_HYPRIOT_MOUNTPOINT
        raise Exception(msg)
    x = os.path.join(TMP_HYPRIOT_MOUNTPOINT, rpath)
    d = os.path.dirname(x)
    if not os.path.exists(d):
        os.makedirs(d)
    with open(x, 'w') as f:
        f.write(contents)
    dtslogger.info('Written to %s' % x)


def interpret_wifi_string(s):
    results = []
    for i, connection in enumerate(s.split(',')):
        tokens = connection.split(':')
        if len(tokens) != 2:
            msg = 'Invalid wifi string %r' % s
            raise Exception(msg)
        wifissid, wifipass = tokens
        wifissid = wifissid.strip()
        wifipass = wifipass.strip()
        name = 'network%d' % (i + 1)
        results.append(Wifi(wifissid, wifipass, name))
    return results


StackInfo = namedtuple('StackInfo', 'archive image_name2id hname')


def save_images(stack2yaml, compress):
    """
        returns stack2info
    """
    cache_dir = DOCKER_IMAGES_CACHE_DIR
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    import docker
    client = docker.from_env()

    stack2info = {}

    for cf, config in stack2yaml.items():
        image_name2id = {}
        for service, service_config in config['services'].items():
            image_name = service_config['image']
            dtslogger.info('Pulling %s' % image_name)
            cmd = ['docker', 'pull', image_name]
            _run_cmd(cmd)
            image = client.images.get(image_name)
            image_id = str(image.id)
            image_name2id[image_name] = image_id

        hname = get_md5("-".join(sorted(list(image_name2id.values()))))[:8]

        if compress:
            destination = os.path.join(cache_dir, cf + '-' + hname + '.tar.gz')
        else:
            destination = os.path.join(cache_dir, cf + '-' + hname + '.tar')

        destination0 = os.path.join(cache_dir, cf + '-' + hname + '.tar')

        stack2info[cf] = StackInfo(archive=destination, image_name2id=image_name2id,
                                   hname=hname)

        if os.path.exists(destination):
            msg = 'Using cached file %s' % destination
            dtslogger.info(msg)
            continue

        dtslogger.info('Saving to %s' % destination0)
        cmd = ['docker', 'save', '-o', destination0] + list(image_name2id.values())
        _run_cmd(cmd)
        if compress:
            cmd = ['gzip', '-f', destination0]
            _run_cmd(cmd)

            assert not os.path.exists(destination0)
            assert os.path.exists(destination)
        else:
            assert destination == destination0

        msg = 'Saved archive %s of size %s' % (destination, friendly_size_file(destination))
        dtslogger.info(msg)

    assert len(stack2info) == len(stack2yaml)
    return stack2info


def log_current_phase(user_data, phase, msg):
    j = json.dumps(dict(phase=phase, msg=msg))
    # cmd = ['bash', '-c', "echo '%s' > /data/phase.json" % j]
    cmd = 'echo %s >> /data/boot-log.txt' % j
    user_data['runcmd'].append(cmd)


def add_run_cmd(user_data, cmd):
    cmd_pre = 'echo %s > /data/command.json' % json.dumps(dict(cmd=cmd, msg='running command'))
    cmd_post = 'echo %s > /data/command.json' % json.dumps(dict(cmd=cmd, msg='finished command'))
    user_data['runcmd'].append(cmd_pre)
    user_data['runcmd'].append(cmd)
    user_data['runcmd'].append(cmd_post)


def get_stack2yaml(stacks, base):
    names = os.listdir(base)
    all_stacks = [os.path.splitext(_)[0] for _ in names if _.endswith("yaml")]
    dtslogger.info('The stacks that are available are: %s' % ", ".join(all_stacks))
    dtslogger.info('You asked to use %s' % stacks)
    use = []
    for s in stacks:
        if s not in all_stacks:
            msg = 'Cannot find stack %r in %s' % (s, all_stacks)
            raise Exception(msg)
        use.append(s)

    stacks2yaml = OrderedDict()
    for sn in use:
        lpath = join(base, sn + '.yaml')
        if not os.path.exists(lpath):
            raise Exception(lpath)

        stacks2yaml[sn] = yaml.load(open(lpath).read())
    return stacks2yaml


def validate_user_data(user_data_yaml):
    if 'VARIABLE' in user_data_yaml:
        msg = 'Invalid user_data_yaml:\n' + user_data_yaml
        msg += '\n\nThe above contains VARIABLE'
        raise Exception(msg)

    try:
        import requests
    except ImportError:
        msg = 'Skipping validation because "requests" not installed.'
        dtslogger.warning(msg)
    else:
        url = 'https://validate.core-os.net/validate'
        r = requests.put(url, data=user_data_yaml)
        info = json.loads(r.content)
        result = info['result']
        nerrors = 0
        for x in result:
            kind = x['kind']
            line = x['line']
            message = x['message']
            m = 'Invalid at line %s: %s' % (line, message)
            m += '| %s' % user_data_yaml.split('\n')[line - 1]

            if kind == 'error':
                dtslogger.error(m)
                nerrors += 1
            else:
                ignore = ['bootcmd', 'package_upgrade', 'runcmd', 'ssh_pwauth', 'sudo', 'chpasswd', 'lock_passwd',
                          'plain_text_passwd']
                show = False
                for i in ignore:
                    if 'unrecognized key "%s"' % i in m:
                        break
                else:
                    show = True
                if show:
                    dtslogger.warning(m)
        if nerrors:
            msg = 'There are %d errors: exiting' % nerrors
            raise Exception(msg)


class NotEnoughSpace(Exception):
    pass


def check_has_space(where, min_available_gb):
    try:
        import psutil
    except ImportError:
        msg = 'Skipping disk check because psutil not installed.'
        dtslogger.info(msg)
    else:
        disk = psutil.disk_usage(where)
        disk_available_gb = disk.free / (1024 * 1024 * 1024.0)

        if disk_available_gb < min_available_gb:
            msg = 'This procedure requires that you have at least %f GB of memory.' % min_available_gb
            msg += '\nYou only have %.2f GB available on %s.' % (disk_available_gb, where)
            dtslogger.error(msg)
            raise NotEnoughSpace(msg)
        else:
            msg = 'You have %.2f GB available on %s. ' % (disk_available_gb, where)
            dtslogger.info(msg)


def get_md5(contents):
    m = hashlib.md5()
    m.update(contents)
    s = m.hexdigest()
    return s
