from dt_shell import dtslogger

import json
import os
import subprocess
import time
import glob
import collections
import re
import yaml
import itertools

from utils.duckietown_utils import get_distro_version

from disk_image.create.constants import \
    PARTITION_MOUNTPOINT, \
    FILE_PLACEHOLDER_SIGNATURE, \
    DOCKER_IMAGE_TEMPLATE, \
    MODULES_TO_LOAD, \
    CLI_TOOLS_NEEDED
from utils.cli_utils import ProgressBar, check_program_dependency


class VirtualSDCard:

    def __init__(self, disk_file, partition_table, loopdev=None):
        self._loopdev = loopdev
        self._disk_file = disk_file
        self._partition_table = partition_table

    @property
    def loopdev(self):
        return self._loopdev

    def set_loopdev(self, loopdev):
        self._loopdev = loopdev

    def partition_device(self, partition):
        return f"{self._loopdev}p{self._partition_table[partition]}"

    def is_mounted(self):
        return self._loopdev is not None

    def mount(self):
        # refresh devices module
        run_cmd(['sudo', 'udevadm', 'trigger'])
        # look for a free loop device
        lodevs = subprocess.check_output(['sudo', 'losetup', '-f']).decode('utf-8').split('\n')
        lodevs = list(filter(len, lodevs))
        if len(lodevs) <= 0:
            dtslogger.error(
                'No free loop devices found. Cannot use virtual image. '
                'Free at least one loop device and retry.'
            )
            exit(3)
        # make sure there is not a conflict with other partitions
        for partition in self._partition_table.keys():
            if os.path.exists(self._disk_by_label(partition)):
                partitions_list = ', '.join(sorted(self._partition_table.keys()))
                dtslogger.error(
                    f'At least one partition with a conflicting name (e.g., {partitions_list}) '
                    f'was found in the system. Detach them before continuing.'
                )
                exit(4)
        # mount loop device
        lodev = subprocess.check_output(
            ["sudo", "losetup", "--show", "-fPL", self._disk_file]
        ).decode('utf-8').strip()
        # refresh devices module
        run_cmd(['sudo', 'udevadm', 'trigger'])
        # once mounted, keep track of the loopdev in use
        self._loopdev = lodev

    def umount(self, quiet=False):
        # mount loop device
        if not quiet:
            dtslogger.info(f"Closing disk {self._disk_file}...")
        try:
            # free loop devices
            output = subprocess.check_output(["sudo", "losetup", "--json"]).decode('utf-8')
            devices = json.loads(output)
            for dev in devices['loopdevices']:
                if not ('(deleted)' in dev['back-file']
                        or dev['back-file'].split(' ')[0] == self._disk_file):
                    continue
                if not quiet:
                    dtslogger.info(f"Unmounting {self._disk_file} from {dev['name']}...")
                run_cmd(['sudo', 'losetup', '-d', dev['name']])
        except Exception as e:
            if not quiet:
                raise e
        if not quiet:
            dtslogger.info("Done!")
        # refresh devices module
        run_cmd(['sudo', 'udevadm', 'trigger'])

    def mount_partition(self, partition):
        dtslogger.info(f'Mounting partition "{partition}"...')
        # refresh devices module
        max_retries = 3
        for i in range(max_retries):
            if os.path.exists(PARTITION_MOUNTPOINT(partition)):
                break
            # refresh kernel module
            run_cmd(['sudo', 'udevadm', 'trigger'])
            # wait for changes to take effect
            if i > 0:
                dtslogger.info('Waiting for the device module to pick up the changes')
                time.sleep(2)
            # mount partition
            if not os.path.exists(PARTITION_MOUNTPOINT(partition)):
                wait_for_disk(self._disk_by_label(partition), timeout=20)
                try:
                    run_cmd(["udisksctl", "mount", "-b", self._disk_by_label(partition)])
                    break
                except BaseException as e:
                    if i == max_retries - 1:
                        raise e
                    dtslogger.info(
                        f'We had issues mounting partition "{partition}". Retrying soon.')
                time.sleep(2)
        # ---
        assert os.path.exists(PARTITION_MOUNTPOINT(partition))
        dtslogger.info(f'Partition "{partition}" successfully mounted!')

    def umount_partition(self, partition):
        dtslogger.info(f'Unmounting partition "{partition}"...')
        # refresh devices module
        run_cmd(['sudo', 'udevadm', 'trigger'])
        # unmount partition
        if os.path.exists(PARTITION_MOUNTPOINT(partition)):
            # try to unmount
            for i in range(3):
                if not os.path.exists(PARTITION_MOUNTPOINT(partition)):
                    break
                # request unmount
                run_cmd(
                    ["udisksctl", "unmount", "-b", self._disk_by_label(partition)],
                    get_output=True
                )
                # wait for changes to take effect
                if i > 0:
                    dtslogger.info(f'Waiting for {self._disk_by_label(partition)} to unmount')
                    time.sleep(2)
        # ---
        dtslogger.info(f'Partition "{partition}" successfully unmounted!')

    def get_disk_identifier(self):
        dtslogger.info(f'Reading Disk Identifier for {self._loopdev}...')
        p = re.compile(".*Disk identifier: 0x([0-9a-z]*).*")
        fdisk_out = run_cmd(["sudo", "fdisk", "-l", self._loopdev], get_output=True)
        m = p.search(fdisk_out)
        disk_identifier = m.group(1)
        dtslogger.info(f'Disk Identifier[{self._loopdev}]: {disk_identifier}')
        return disk_identifier

    def set_disk_identifier(self, disk_identifier):
        dtslogger.info(f'Re-applying disk identifier ({disk_identifier}) -> [{self._loopdev}]')
        cmd = ["sudo", "fdisk", self._loopdev]
        dtslogger.debug("$ %s" % cmd)
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE)
        time.sleep(1)
        p.communicate(("x\ni\n0x%s\nr\nw" % disk_identifier).encode("ascii"))
        dtslogger.info('Done!')

    def disk_image_sha(self):
        return run_cmd(['sha256sum', self._disk_file], get_output=True).split(' ')[0]

    @staticmethod
    def find_loopdev(disk_file, quiet=False):
        # mount loop device
        if not quiet:
            dtslogger.info(f"Looking for loop devices associated to disk image {disk_file}...")
        try:
            # iterate over loop devices
            lodevices = json.loads(run_cmd(["sudo", "losetup", "--json"], get_output=True))
            for dev in lodevices['loopdevices']:
                if dev['back-file'].split(' ')[0] == disk_file:
                    if not quiet:
                        dtslogger.info(f"Found {dev['name']}!")
                    # found a loop device connected to the given image
                    return dev['name']
            if not quiet:
                dtslogger.info("None found!")
        except Exception as e:
            if not quiet:
                raise e
        return None

    def _disk_by_label(self, partition):
        if self._loopdev:
            if partition not in self._partition_table:
                raise KeyError(f"Partition '{partition}' not found in the partition table")
            return f"{self._loopdev}p{self._partition_table[partition]}"
        return f"/dev/disk/by-label/{partition}"


def check_cli_tools():
    for cli_tool in CLI_TOOLS_NEEDED:
        check_program_dependency(cli_tool)


def pull_docker_image(client, image):
    repository, tag = image.split(':')
    pbar = ProgressBar()
    total_layers = set()
    completed_layers = set()
    dtslogger.info(f'Pulling image {image}...')
    for step in client.api.pull(repository, tag, stream=True, decode=True):
        if 'status' not in step or 'id' not in step:
            continue
        total_layers.add(step['id'])
        if step['status'] in ['Download complete', 'Pull complete']:
            completed_layers.add(step['id'])
        # compute progress
        if len(total_layers) > 0:
            progress = int(100 * len(completed_layers) / len(total_layers))
            pbar.update(progress)
    pbar.update(100)
    dtslogger.info(f'Image pulled: {image}')


def disk_template_partitions(disk_template_dir):
    return list(filter(
        lambda d: os.path.isdir(os.path.join(disk_template_dir, d)),
        os.listdir(disk_template_dir)
    ))


def disk_template_objects(disk_template_dir, partition, filter_type):
    partition_template_dir = os.path.join(disk_template_dir, partition)
    # check if we know about this partition
    if not os.path.isdir(partition_template_dir):
        raise ValueError(f'Partition "{partition}" not found in disk template.')
    # define filtering functions
    filter_lambdas = {
        'file': os.path.isfile,
        'directory': os.path.isdir
    }
    if filter_type not in filter_lambdas:
        raise ValueError('The argument filter_type can have values from ["file", "directory"].')
    filter_lambda = filter_lambdas[filter_type]
    # run glob, this returns absolute path of every file and dir under the partition template dir
    glob_star = glob.glob(os.path.join(partition_template_dir, '**'), recursive=True)
    return [
        {
            'origin': f,
            'destination': os.path.join(
                PARTITION_MOUNTPOINT(partition),
                os.path.relpath(f, partition_template_dir)
            ),
            'relative': '/' + os.path.relpath(f, partition_template_dir)
        }
        for f in glob_star if filter_lambda(f)
    ]


def find_placeholders_on_disk(disk_image):
    matches = run_cmd(
        ['strings', '-t', 'd', disk_image, '|', 'grep', f'"{FILE_PLACEHOLDER_SIGNATURE}"'],
        get_output=True, shell=True
    ).splitlines()
    # parse matches
    matches = map(lambda m: m.split(' ')[::-1], matches)
    matches = list(map(lambda m: (m[0], int(m[1])), matches))
    placeholders = dict(matches)
    # make sure matches are unique
    if len(placeholders) != len(matches):
        pholders = map(lambda m: m[0], matches)
        for pholder, count in collections.Counter(pholders).items():
            if count > 1:
                raise ValueError(
                    f'The string "{pholder}" is not unique in the disk image {disk_image}, '
                    f'{count} instances were found!'
                )
    # ---
    return placeholders


def get_file_first_line(filepath):
    with open(filepath, 'rt') as f:
        line = f.readline()
    return line


def get_file_length(filepath):
    stat_out = run_cmd(['stat', '--format', '%s,%b,%B', filepath], get_output=True)
    real_size, num_blocks, block_size = stat_out.strip().split(',')
    return int(real_size), int(num_blocks) * int(block_size)


def run_cmd(cmd, get_output=False, shell=False, env=None):
    dtslogger.debug("$ %s" % cmd)
    # turn [cmd] into "cmd" if shell is set to True
    if isinstance(cmd, list) and shell:
        cmd = ' '.join(cmd)
    # ---
    if get_output:
        return subprocess.check_output(cmd, shell=shell, env=env).decode('utf-8')
    else:
        subprocess.check_call(cmd, shell=shell, env=env)


def run_cmd_in_root(cmd, *args, **kwargs):
    cmd = ' '.join(cmd) if isinstance(cmd, list) else cmd
    return run_cmd([
        'sudo', 'chroot', '--userspec=0:0', PARTITION_MOUNTPOINT('root'),
        '/bin/bash -c '
        '"{}"'.format(cmd)
    ], *args, **kwargs, shell=True)


def wait_for_disk(disk, timeout):
    stime = time.time()
    while (time.time() - stime < timeout) and (not os.path.exists(disk)):
        time.sleep(1.0)


def validator_autoboot_stack(shell, local_path, remote_path, data=None):
    # get version
    distro = get_distro_version(shell)
    modules = {
        DOCKER_IMAGE_TEMPLATE(
            owner=module['owner'], module=module['module'], version=distro,
            tag=module['tag'] if 'tag' in module else None
        ) for module in MODULES_TO_LOAD
    }
    # load stack content
    content = yaml.load(open(local_path, 'rt'), yaml.SafeLoader)
    for srv_name, srv_info in content['services'].items():
        srv_image = srv_info['image']
        p1, p2, *_ = srv_image.split('/') + [None]
        owners = [p1] if p2 else ['', 'library/']
        image_full = p2 or p1
        image, tag, *_ = image_full.split(':') + [None]
        images = [f"{image}:{tag}"] if tag else ['', ':latest']
        candidates = set(map(lambda p: '/'.join(p), itertools.product(owners, images)))
        if len(candidates.intersection(modules)) > 0:
            continue
        # no images found
        msg = f"The autoboot stack '{remote_path}' requires the " \
              f"Docker image '{srv_image}' for the service '{srv_name}' but " \
              f"no candidates were found in the list of modules to load."
        dtslogger.error(msg)
        raise ValueError(msg)


def validator_yaml_syntax(shell, local_path, remote_path, data=None):
    # simply load the YAML file
    try:
        yaml.load(open(local_path, 'rt'), yaml.SafeLoader)
    except yaml.YAMLError as e:
        msg = f"The file {remote_path} is not a valid YAML file. Reason: {str(e)}"
        dtslogger.error(msg)
        raise ValueError(msg)