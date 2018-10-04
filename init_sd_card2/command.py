from __future__ import print_function

import argparse
import getpass
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
from dt_shell import dtslogger, DTCommandAbs
from dt_shell.env_checks import check_docker_environment
from whichcraft import which

USER = getpass.getuser()
TMP_ROOT_MOUNTPOINT = "/media/{USER}/root".format(USER=USER)
TMP_HYPRIOT_MOUNTPOINT = "/media/{USER}/HypriotOS".format(USER=USER)

DISK_HYPRIOTOS = '/dev/disk/by-label/HypriotOS'
DISK_ROOT = '/dev/disk/by-label/root'


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

        parser.add_argument('--stacks', default="DT18_00_basic,DT18_01_health_stats",
                            help="which stacks to run")

        parser.add_argument('--country', default="US",
                            help="2-letter country code (US, CA, CH, etc.)")
        parser.add_argument('--wifi', dest="wifi", default='duckietown:quackquack',
                            help="""
        Can specify one or more networks: "network:password,network:password,..."

                                    """)

        parser.add_argument('--ethz-username', default=None)
        parser.add_argument('--ethz-password', default=None)

        parsed = parser.parse_args(args=args)

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


def step_unmount(shell, parsed):
    cmd = ['sync']
    _run_cmd(cmd)

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
    deps = ['wget', 'tar', 'udisksctl', 'docker', 'base64', 'gzip', 'udevadm']
    for dep in deps:
        check_program_dependency(dep)
    script_file = get_resource('init_sd_card2.sh')
    script_cmd = '/bin/bash %s' % script_file
    env = get_environment_clean()
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
    DEV = '/dev/mmcblk0'
    DEVp2 = DEV + 'p2'
    if not os.path.exists(DEV):
        msg = 'This only works assuming device == %s' % DEV
        raise Exception(msg)
    else:
        msg = 'Found device %s.' % DEV
        dtslogger.info(msg)

    dtslogger.info('Current status:')
    cmd = ['sudo', 'lsblk', DEV]
    _run_cmd(cmd)
    cmd = ['sudo', 'parted', '-s', DEV, 'resizepart', '2', '100%']
    _run_cmd(cmd)
    cmd = ['sudo', 'e2fsck', '-f', DEVp2]
    _run_cmd(cmd)
    cmd = ['sudo', 'resize2fs', DEVp2]
    _run_cmd(cmd)
    dtslogger.info('Updated status:')
    cmd = ['sudo', 'lsblk', DEV]
    _run_cmd(cmd)


def step_setup(shell, parsed):
    token = shell.get_dt1_token()
    check_has_space(where=os.getcwd(), min_available_gb=1.0)

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

        dtslogger.info('Adding file %s with content:\n---------\n%s\n----------' % (path, content))
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

    user_data['runcmd'].append("chown -R 1000:1000 {home}".format(home=user_home_path))

    # DT shell config
    dtshell_config = dict(token_dt1=token)
    add_file(path=os.path.join(user_home_path, '.dt-shell/config'),
             content=json.dumps(dtshell_config))

    configure_ssh(parsed, ssh_key_pri, ssh_key_pub)
    configure_networks(parsed, add_file)
    configure_images(parsed, user_data, add_file_local)

    user_data_yaml = '#cloud-config\n' + yaml.dump(user_data, default_flow_style=False)

    validate_user_data(user_data_yaml)
    write_to_root('user-data', user_data_yaml)

    write_to_hypriot('config_txt', '''
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


def configure_images(parsed, user_data, add_file_local):
    import psutil
    # read and validate duckiebot-compose
    stacks_to_use = parsed.stacks.split(',')
    dtslogger.info('Will run the stacks %s' % stacks_to_use)
    stack2yaml = get_stack2yaml(stacks_to_use, get_resource('stacks'))
    preload_images = get_mentioned_images(stack2yaml)

    image2tgz = download_images(preload_images)
    dtslogger.info("loading %s" % image2tgz)

    buffer_bytes = 100 * 1024 * 1024
    written = []
    # write images until we have space
    for image_name, tgz in image2tgz.items():
        size = os.stat(tgz).st_size
        print('%s: %s bytes' % (tgz, size))

        rpath = os.path.join('var', 'local', os.path.basename(tgz))
        destination = os.path.join(TMP_ROOT_MOUNTPOINT, rpath)
        available = psutil.disk_usage(TMP_ROOT_MOUNTPOINT).free
        if available < size + buffer_bytes:
            msg = 'You have %s available but need %s for %s' % (
                friendly_size(available), friendly_size(size), image_name)
            dtslogger.warning(msg)
            break

        cmd = ['sudo', 'cp', tgz, destination]
        _run_cmd(cmd)

        user_data['runcmd'].append(['docker', 'load', '--input', os.path.join('/', rpath)])
        written.append(image_name)

    for cf in stacks_to_use:
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

        needed = stack2yaml[cf]['services']
        missing = []
        for x in needed:
            if x in written:
                msg = 'For stack %r: container %r could be written.' % (cf, x)
                dtslogger.info(msg)
            else:
                msg = 'For stack %r: container %r could NOT be written.' % (cf, x)
                dtslogger.warning(msg)
                missing.append(x)

        if missing:
            msg = 'I am skipping activating the stack %r because I could not copy %r' % (cf, missing)
            dtslogger.error(msg)
        else:
            msg = 'Adding the stack %r as default running' % cf
            dtslogger.info(msg)
            cmd = ['docker-compose', '--file', rpath, '-p', cf, 'up', '-d']

            user_data['runcmd'].append(cmd)  # first boot
            user_data['bootcmd'].append(cmd)  # every boot


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

import tempfile


def write_to_root(rpath, contents):
    if not os.path.exists(TMP_ROOT_MOUNTPOINT):
        msg = 'Disk not mounted: %s' % TMP_ROOT_MOUNTPOINT
        raise Exception(msg)
    # for some reason it is mounted as root

    dest = os.path.join(TMP_ROOT_MOUNTPOINT, rpath)
    d = os.path.dirname(dest)
    if not os.path.exists(d):
        # os.makedirs(d)
        cmd = ['sudo', 'mkdirs', d]
        _run_cmd(cmd)
    t = tempfile.mktemp()
    with open(t, 'w') as f:
        f.write(contents)

    cmd = ['sudo', 'cp', t, dest]
    _run_cmd(cmd)
    dtslogger.info('Written to %s' % dest)
    os.unlink(t)


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


def download_images(preload_images, cache_dir='/tmp/duckietown/docker_images'):
    image2tmpfilename = OrderedDict()
    import docker
    client = docker.from_env()
    for name, image_name in preload_images.items():

        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        destination = os.path.join(cache_dir, name + '.tar.gz')
        image2tmpfilename[name] = destination

        if os.path.exists(destination):
            dtslogger.info('already know %s' % destination)
        else:

            repo, tag = image_name.split(':')
            dtslogger.info('pulling %s' % image_name)
            client.images.pull(repository=repo, tag=tag)
            image = client.images.get(image_name)

            dtslogger.info('saving to %s' % destination)
            destination0 = destination + '.tmp'
            with open(destination0, 'wb') as f:
                for chunk in image.save():
                    f.write(chunk)
            destination1 = destination + '.tmp2'

            os.system('gzip --best -c "%s" > "%s"' % (destination0, destination1))
            # subprocess.check_call(['gzip', '--best', '-o', destination1, destination0])
            os.unlink(destination0)
            os.rename(destination1, destination)

    return image2tmpfilename


def get_stack2yaml(stacks, base):
    names = os.listdir(base)
    all_stacks = [os.path.splitext(_)[0] for _ in names if _.endswith("yaml")]
    dtslogger.info('The stacks that are available are: %s' % ",".join(all_stacks))
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


def get_mentioned_images(stacks2yaml):
    preload_images = OrderedDict()
    for sn, compose in stacks2yaml.items():
        for name, service in compose['services'].items():
            preload_images[name] = service['image']
    return preload_images


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
                ignore = ['bootcmd', 'package_upgrade', 'runcmd', 'ssh_pwauth', 'sudo', 'chpasswd', 'lock_passwd', 'plain_text_passwd']
                show = False
                for i in ignore:
                    if 'unrecognized key "%s"' in m:
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
