from __future__ import print_function

import argparse
import os
import platform
import shutil
import subprocess
import sys
from os.path import join, realpath, dirname
from string import Template

from dt_shell import dtslogger, DTCommandAbs


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        parser = argparse.ArgumentParser()
        parser.add_argument('--hostname', default='duckiebot')
        parser.add_argument('--linux-username', default='duckie')
        parser.add_argument('--linux-password', default='quackquack')
        parser.add_argument('--wifi-ssid', dest="wifissid", default='duckietown')
        parser.add_argument('--wifi-password', dest="wifipass", default='quackquack')
        parsed = parser.parse_args(args=args)

        if not is_valid_hostname(parsed.hostname):
            msg = 'This is not a valid hostname: %r.' % parsed.hostname
            raise Exception(msg)

        if '-' in parsed.hostname:
            msg = 'Cannot use the hostname %r. It cannot contain "-" because of a ROS limitation. ' % parsed.hostname
            raise Exception(msg)

        if len(parsed.hostname) < 3:
            msg = 'This hostname is too short. Choose something more descriptive.'
            raise Exception(msg)

        MIN_AVAILABLE_GB = 0.0
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

        p = platform.system().lower()

        if 'darwin' in p:
            msg = 'This procedure cannot be run on Mac. You need an Ubuntu machine.'
            raise Exception(msg)

        this = dirname(realpath(__file__))
        script_files = realpath(join(this, '..', 'init_sd_card.scripts'))

        script_file = join(script_files, 'init_sd_card.sh')

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

        env['DUCKIE_TOKEN'] = token
        env['IDENTITY_FILE'] = ssh_key_pub

        env['WIFISSID'] = parsed.wifissid
        env['WIFIPASS'] = parsed.wifipass
        env['HOST_NAME'] = parsed.hostname
        env['DTS_USERNAME'] = parsed.linux_username
        env['PASSWORD'] = parsed.linux_password

        # add other environment
        env.update(os.environ)

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

        bit0 = """

# --- init_sd_card generated ---

# Use the key for all hosts
IdentityFile $IDENTITY

Host $HOSTNAME
    User $DTS_USERNAME
    Hostname $HOSTNAME.local
    IdentityFile $IDENTITY
    StrictHostKeyChecking no
# ------------------------------        
        
"""

        subs = dict(HOSTNAME=parsed.hostname, IDENTITY=ssh_key_pri_copied, DTS_USERNAME=parsed.linux_username)

        bit = Template(bit0).substitute(**subs)

        if not bit in current:
            dtslogger.info('Updating ~/.ssh/config with: ' + bit)
            with open(ssh_config, 'a') as f:
                f.write(bit)
        else:
            dtslogger.info('Configuration already found in ~/.ssh/config')

        ret = subprocess.call(script_cmd, shell=True, env=env,
                              stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout)
        if ret == 0:
            dtslogger.info('Done!')
        else:
            msg = ('An error occurred while initializing the SD card, please check and try again (%s).' % ret)
            raise Exception(msg)


def is_valid_hostname(hostname):
    import re
    # https://stackoverflow.com/questions/2532053/validate-a-hostname-string

    if len(hostname) > 253:
        return False

    allowed = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)
    return allowed.match(hostname)
