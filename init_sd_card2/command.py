from __future__ import print_function

import argparse
import getpass
import json
import os
import platform
import shutil
import subprocess
import sys
from collections import namedtuple, OrderedDict
from os.path import join, realpath, dirname

import yaml
from dt_shell import dtslogger, DTCommandAbs
from dt_shell.env_checks import check_docker_environment

USER = getpass.getuser()
TMP_ROOT_MOUNTPOINT = "/media/{USER}/root".format(USER=USER)
TMP_HYPRIOT_MOUNTPOINT = "/media/{USER}/HypriotOS".format(USER=USER)

DISK_HYPRIOTOS = '/dev/disk/by-label/HypriotOS'
DISK_ROOT = '/dev/disk/by-label/root'


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        parser = argparse.ArgumentParser()
        parser.add_argument('--hostname', default='duckiebot')
        parser.add_argument('--linux-username', default='duckie')
        parser.add_argument('--linux-password', default='quackquack')
        parser.add_argument('--wifi', dest="wifi", default='duckietown:quackquack',
                            help="""
Can specify one or more networks: "network:password,network:password,..."
                            
                            """)

        parser.add_argument('--ethz-username', default=None)
        parser.add_argument('--ethz-password', default=None)
        parser.add_argument('--country', default="US",
                            help="2-letter country code (US, CA, CH, etc.)")
        parser.add_argument('--stacks', default="DT18_00_basic,DT18_01_health_stats",
                            help="which stacks to run")
        #
        # DT18_00_basic.yaml
        # DT18_01_health_stats.yaml
        # DT18_03_roscore.yaml
        # DT18_04_camera.yaml
        # DT18_99_swarm.yaml
        parser.add_argument('--expand', action="store_true", default=False,
                            help="Expand partition table")
        parser.add_argument('--no-flash', dest='no_flash', action="store_true", default=False,
                            help="Do not flash, only update")

        parsed = parser.parse_args(args=args)

        check_docker_environment()

        script_files = dirname(realpath(__file__))

        stacks_to_use = parsed.stacks.split(',')
        stack2yaml = get_stack2yaml(stacks_to_use, join(script_files, 'stacks'))
        preload_images = get_mentioned_images(stack2yaml)

        image2tgz = download_images(preload_images)
        dtslogger.info("loading %s" % image2tgz)

        if not is_valid_hostname(parsed.hostname):
            msg = 'This is not a valid hostname: %r.' % parsed.hostname
            raise Exception(msg)

        if '-' in parsed.hostname:
            msg = 'Cannot use the hostname %r. It cannot contain "-" because of a ROS limitation. ' % parsed.hostname
            raise Exception(msg)

        if len(parsed.hostname) < 3:
            msg = 'This hostname is too short. Choose something more descriptive.'
            raise Exception(msg)

        MIN_AVAILABLE_GB = 1.0
        try:
            import psutil
        except ImportError:
            msg = 'Skipping disk check because psutil not installed.'
            dtslogger.info(msg)
        else:
            disk = psutil.disk_usage(os.getcwd())
            disk_available_gb = disk.free / (1024 * 1024 * 1024.0)

            if disk_available_gb < MIN_AVAILABLE_GB:
                msg = 'This procedure requires that you have at least %f GB of memory.' % MIN_AVAILABLE_GB
                msg += '\nYou only have %f GB available.' % disk_available_gb
                raise Exception(msg)
            else:

                msg = 'You have %f GB available.' % disk_available_gb
                dtslogger.info(msg)

        p = platform.system().lower()

        if 'darwin' in p:
            msg = 'This procedure cannot be run on Mac. You need an Ubuntu machine.'
            raise Exception(msg)

        script_file = join(script_files, 'init_sd_card2.sh')

        if not os.path.exists(script_file):
            msg = 'Could not find script %s' % script_file
            raise Exception(msg)

        ssh_key_pri = join(script_files, 'DT18_key_00')
        ssh_key_pub = join(script_files, 'DT18_key_00.pub')

        for f in [ssh_key_pri, ssh_key_pub]:
            if not os.path.exists(f):
                msg = 'Could not find file %s' % f
                raise Exception(msg)

        script_cmd = '/bin/bash %s' % script_file
        token = shell.get_dt1_token()
        env = dict()

        user_data_file = join(script_files, 'USER_DATA.in.yaml')
        if not os.path.exists(user_data_file):
            msg = 'Could not find %s' % user_data_file
            raise Exception(msg)

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

        # read and validate duckiebot-compose
        cfs = parsed.stacks.split(',')
        dtslogger.info('Will run the stacks %s' % cfs)
        for cf in cfs:
            lpath = join(script_files, 'stacks', cf + '.yaml')
            if not os.path.exists(lpath):
                raise Exception(lpath)

            from whichcraft import which
            if which('docker-compose') is None:
                msg = 'Could not find docker-compose. Cannot validate file.'
                dtslogger.error(msg)
            else:
                ret = subprocess.check_call(['docker-compose', '-f', lpath, 'config', '--quiet'], )
                if ret > 0:
                    msg = 'Invalid compose file: %s' % lpath
                    raise Exception(msg)

            rpath = '/var/local/%s.yaml' % cf
            add_file_local(path=rpath, local=lpath)
            cmd = ['docker-compose', '--file', rpath, '-p', cf, 'up', '-d']

            user_data['runcmd'].append(cmd)  # first boot
            user_data['bootcmd'].append(cmd)  # every boot

        user_data['runcmd'].append("chown -R 1000:1000 {home}".format(home=user_home_path))

        dtshell_config = {
            'token_dt1': token
        }

        add_file(path=os.path.join(user_home_path, '.dt-shell/config'),
                 content=json.dumps(dtshell_config))

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

        if parsed.expand:
            partition_table = join(script_files, 'partition-table.bin')
            if not os.path.exists(partition_table):
                msg = 'Cannot find partition table %s' % partition_table
                raise Exception(msg)
            dtslogger.info('Expanding partition to 32 GB')
            env['PARTITION_TABLE'] = partition_table

        else:
            dtslogger.info('Not expanding partition')

        # add other environment
        env.update(os.environ)

        # remove DOCKER_HOST if present
        if 'DOCKER_HOST' in env:
            r = env['DOCKER_HOST']
            msg = 'I will IGNORE the DOCKER_HOST variable that is currently set to %r' % r
            dtslogger.warning(msg)
            env.pop('DOCKER_HOST')

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

        if not bit in current:
            dtslogger.info('Updating ~/.ssh/config with: ' + bit)
            with open(ssh_config, 'a') as f:
                f.write(bit)
        else:
            dtslogger.info('Configuration already found in ~/.ssh/config')

        if not parsed.no_flash:

            ret = subprocess.call(script_cmd, shell=True, env=env,
                                  stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout)
            if ret == 0:
                dtslogger.info('Done!')
            else:
                msg = ('An error occurred while initializing the SD card, please check and try again (%s).' % ret)
                raise Exception(msg)



        user_data_yaml = '#cloud-config\n' + yaml.dump(user_data, default_flow_style=False)
        if 'VARIABLE' in user_data_yaml:
            msg = 'Invalid user_data_yaml:\n' + user_data_yaml
            msg += '\n\nThe above contains VARIABLE'
            raise Exception(msg)
        validate_user_data(user_data_yaml)
        write_to_root('/user-data', user_data_yaml)

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




        unmount_disks()

def is_valid_hostname(hostname):
    import re
    # https://stackoverflow.com/questions/2532053/validate-a-hostname-string
    if len(hostname) > 253:
        return False
    allowed = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)
    return allowed.match(hostname)


Wifi = namedtuple('Wifi', 'ssid password name')


def write_to_root(rpath, contents):
    if not os.path.exists(TMP_ROOT_MOUNTPOINT):
        msg = 'Disk not mounted: %s' % TMP_ROOT_MOUNTPOINT
        raise Exception(msg)
    x = os.path.join(TMP_ROOT_MOUNTPOINT, rpath)
    d = os.path.dirname(x)
    if not os.path.exists(d):
        os.makedirs(d)
    with open(x, 'w') as f:
        f.write(contents)

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
            subprocess.check_call(['gzip', '--best', '-o', destination1, destination0])
            os.unlink(destination0)
            os.rename(destination1, destination)

    return image2tmpfilename


def get_stack2yaml(stacks, base):
    names = os.listdir(base)
    all_stacks = [os.path.splitext(_)[0] for _ in names if _.endswith("yaml")]
    dtslogger.info('The stacks that are available are: %s' % ",".join(all_stacks))
    use = []
    for s in stacks:
        if not s in all_stacks:
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
                dtslogger.warning(m)
        if nerrors:
            msg = 'There are %d errors: exiting' % nerrors
            raise Exception(msg)



def unmount_disks():
    # TODO: sync
    cmd = ['udisksctl', 'unmount', '-b', DISK_HYPRIOTOS]
    subprocess.check_call(cmd)
    cmd = ['udisksctl', 'unmount', '-b', DISK_ROOT]
    subprocess.check_call(cmd)
