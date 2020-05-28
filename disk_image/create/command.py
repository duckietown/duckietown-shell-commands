from dt_shell import DTCommandAbs, dtslogger, DTShell, __version__ as shell_version

import argparse
import pathlib
import getpass
import json
import os
import shutil
import subprocess
import time
import glob
import docker
import collections
import re
import socket
from datetime import datetime

from utils.cli_utils import ProgressBar, ask_confirmation, check_program_dependency


PARTITION_MOUNTPOINT = lambda partition: f"/media/{getpass.getuser()}/{partition}"
DISK_DEVICE = lambda device, partition_id: f"{device}p{partition_id}"
DISK_BY_LABEL = lambda partition: f"/dev/disk/by-label/{partition}"
DISK_IMAGE_PARTITION_TABLE = {
    'HypriotOS': 1,
    'root': 2
}
ROOT_PARTITION = 'root'
DISK_IMAGE_SIZE_GB = 8
DISK_IMAGE_FORMAT_VERSION = "1"
FILE_PLACEHOLDER_SIGNATURE = "DT_DUCKIETOWN_PLACEHOLDER_"
TMP_WORKDIR = "/tmp/duckietown/dts/disk_image"
DISK_IMAGE_STATS_LOCATION = 'data/stats/disk_image/build.json'
DEVICE_ARCH = 'arm32v7'
DOCKER_IMAGE_TEMPLATE = lambda owner, module, tag=None, version=None: \
    f'{owner}/{module}:' + ((f'{version}-%s' % DEVICE_ARCH) if tag is None else tag)
HYPRIOTOS_VERSION = "1.11.1"
HYPRIOTOS_DISK_IMAGE_NAME = f"hypriotos-rpi-v{HYPRIOTOS_VERSION}"
INPUT_DISK_IMAGE_URL = f"https://github.com/hypriot/image-builder-rpi/releases/download/" \
                       f"v{HYPRIOTOS_VERSION}/{HYPRIOTOS_DISK_IMAGE_NAME}.img.zip"

MODULES_TO_LOAD = [
    {
        'owner': 'portainer',
        'module': 'portainer',
        'tag': 'linux-arm'
    },
    {
        'owner': 'duckietown',
        'module': 'dt-device-health'
    },
    {
        'owner': 'duckietown',
        'module': 'dt-device-online'
    },
    {
        'owner': 'duckietown',
        'module': 'dt-files-api'
    },
    {
        'owner': 'duckietown',
        'module': 'dt-duckiebot-dashboard'
    },
    {
        'owner': 'duckietown',
        'module': 'dt-duckiebot-interface'
    },
    {
        'owner': 'duckietown',
        'module': 'dt-car-interface'
    },
    {
        'owner': 'duckietown',
        'module': 'dt-rosbridge-websocket'
    },
    {
        'owner': 'duckietown',
        'module': 'dt-core'
    }
]

SUPPORTED_STEPS = [
    'download', 'create', 'mount', 'resize', 'setup', 'docker', 'finalize', 'unmount', 'compress'
]

CLI_TOOLS_NEEDED = [
    'wget', 'unzip', 'sudo', 'cp', 'sha256sum', 'strings', 'grep', 'stat', 'udevadm', 'udisksctl',
    'losetup', 'parted', 'e2fsck', 'resize2fs', 'truncate'
]


class DTCommand(DTCommandAbs):

    help = 'Prepares an .img disk file for a Raspberry Pi'

    @staticmethod
    def command(shell: DTShell, args):
        parser = argparse.ArgumentParser()
        # define parser arguments
        parser.add_argument(
            "--steps",
            type=str,
            default=','.join(SUPPORTED_STEPS),
            help="List of steps to perform (comma-separated)",
        )
        parser.add_argument(
            "-o",
            "--output",
            type=str,
            default=None,
            help="The destination directory for the output file"
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
        # check given steps
        parsed.steps = parsed.steps.split(',')
        non_supported_steps = set(parsed.steps).difference(set(SUPPORTED_STEPS))
        if len(non_supported_steps):
            dtslogger.error(f'These steps are not supported: {non_supported_steps}')
            return
        # check dependencies
        _check_cli_tools()
        # check if the output directory exists, create it if it does not
        if parsed.output is None:
            parsed.output = os.getcwd()
        if not os.path.exists(parsed.output):
            os.makedirs(parsed.output)
        # define output file template
        in_file_path = lambda ex: os.path.join(parsed.workdir, f'{HYPRIOTOS_DISK_IMAGE_NAME}.{ex}')
        input_image_name = pathlib.Path(in_file_path('img')).stem
        out_file_path = lambda ex: os.path.join(parsed.output, f'dt-{input_image_name}.{ex}')
        # get version
        major_version = shell.get_commands_version().split('-')[0]
        # this will hold the link to the loop device
        loopdev = None
        # this is the surgey plan that will be performed by the init_sd_card command
        surgery_plan = []
        # this holds the stats that will be stored in /data/stats/disk_image/build.json
        stats = {
            'steps': {
                step: bool(step in parsed.steps) for step in SUPPORTED_STEPS
            },
            'version': DISK_IMAGE_FORMAT_VERSION,
            'input_name': input_image_name,
            'input_url': INPUT_DISK_IMAGE_URL,
            'base_type': 'HypriotOS',
            'base_version': HYPRIOTOS_VERSION,
            'environment': {
                'hostname': socket.gethostname(),
                'user': getpass.getuser(),
                'shell_version': shell_version,
                'commands_version': shell.get_commands_version()
            },
            'modules': [
                DOCKER_IMAGE_TEMPLATE(
                    owner=module['owner'], module=module['module'], version=major_version,
                    tag=module['tag'] if 'tag' in module else None
                )
                for module in MODULES_TO_LOAD
            ],
            'template': {
                'directories': [],
                'files': []
            },
            'disk_size_gb': DISK_IMAGE_SIZE_GB,
            'stamp': time.time(),
            'stamp_human': datetime.now().isoformat()
        }
        #
        # STEPS:
        # ------>
        # Step: download
        if 'download' in parsed.steps:
            dtslogger.info('Step BEGIN: download')
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
            # download zip (if necessary)
            dtslogger.info('Looking for ZIP image file...')
            if not os.path.isfile(in_file_path('zip')):
                dtslogger.info('Downloading ZIP image...')
                _run_cmd(['wget', '--no-verbose', '--show-progress', '--continue',
                          '--output-document', in_file_path('zip'), INPUT_DISK_IMAGE_URL])
            else:
                dtslogger.info(f"Reusing cached ZIP image file [{in_file_path('zip')}].")
            # unzip (if necessary)
            if not os.path.isfile(in_file_path('img')):
                dtslogger.info('Extracting ZIP image...')
                _run_cmd(['unzip', in_file_path('zip'), '-d', parsed.workdir])
            else:
                dtslogger.info(f"Reusing cached DISK image file [{in_file_path('img')}].")
            # ---
            dtslogger.info('Step END: download\n')
        # Step: download
        # <------
        #
        # STEPS:
        # ------>
        # Step: create
        if 'create' in parsed.steps:
            dtslogger.info('Step BEGIN: create')
            # check if the destination image already exists
            if os.path.exists(out_file_path('img')):
                msg = f"The destination file {out_file_path('img')} already exists. " \
                      f"If you proceed, the file will be overwritten."
                granted = ask_confirmation(msg)
                if not granted:
                    dtslogger.info('Aborting.')
                    return
            # create empty disk image
            dtslogger.info(f"Creating empty disk image [{out_file_path('img')}]")
            _run_cmd([
                'dd', 'if=/dev/zero', f"of={out_file_path('img')}", 'bs=100M',
                f'count={10 * DISK_IMAGE_SIZE_GB}'
            ])
            dtslogger.info("Empty disk image created!")
            # make copy
            dtslogger.info(f"Copying [{in_file_path('img')}] -> [{out_file_path('img')}]")
            _run_cmd([
                'dd', f"if={in_file_path('img')}", f"of={out_file_path('img')}", 'conv=notrunc'
            ])
            dtslogger.info('Step END: create\n')
        # Step: create
        # <------
        #
        # ------>
        # Step: mount
        if 'mount' in parsed.steps:
            dtslogger.info('Step BEGIN: mount')
            # check if the destination image is already mounted
            loopdev = _find_virtual_sd_card(out_file_path('img'))
            if loopdev:
                dtslogger.warn(
                    f"The destination file {out_file_path('img')} already exists "
                    f"and is mounted to {loopdev}, skipping the 'mount' step."
                )
            else:
                # mount disk image
                dtslogger.info(f"Mounting {out_file_path('img')}...")
                loopdev = _mount_virtual_sd_card(out_file_path('img'))
                dtslogger.info(f"Disk {out_file_path('img')} successfully mounted on {loopdev}")
            dtslogger.info('Step END: mount\n')
        # Step: mount
        # <------
        #
        # ------>
        # Step: resize
        if 'resize' in parsed.steps:
            dtslogger.info('Step BEGIN: resize')
            # make sure that the disk is mounted
            if loopdev is None:
                dtslogger.error(f"The disk {out_file_path('img')} is not mounted.")
                return
            # get root partition id
            root_partition_id = DISK_IMAGE_PARTITION_TABLE[ROOT_PARTITION]
            root_device = DISK_DEVICE(loopdev, root_partition_id)
            # get original disk identifier
            disk_identifier = _get_device_disk_identifier(loopdev)
            # resize root partition to take the entire disk
            cmd = ["sudo", "parted", "-s", loopdev, "resizepart", "2", "100%"]
            _run_cmd(cmd)
            # fix file system
            cmd = ["sudo", "e2fsck", "-f", root_device]
            _run_cmd(cmd)
            # resize file system
            cmd = ["sudo", "resize2fs", root_device]
            _run_cmd(cmd)
            dtslogger.info('Waiting 5 seconds for changes to take effect...')
            time.sleep(5)
            # make sure that the changes had an effect
            assert _get_device_disk_identifier(loopdev) != disk_identifier
            # restore disk identifier
            _set_device_disk_identifier(loopdev, disk_identifier)
            assert _get_device_disk_identifier(loopdev) == disk_identifier
            # ---
            dtslogger.info('Step END: resize\n')
        # Step: resize
        # <------
        #
        # ------>
        # Step: setup
        if 'setup' in parsed.steps:
            dtslogger.info('Step BEGIN: setup')
            # from this point on, if anything weird happens, unmount the disk
            try:
                # make sure that the disk is mounted
                if loopdev is None:
                    dtslogger.error(f"The disk {out_file_path('img')} is not mounted.")
                    return
                # find partitions to update
                partitions = _get_disk_template_partitions()
                # put template objects inside the stats object
                for partition in partitions:
                    stats['template']['directories'] = list(map(
                        lambda u: u['relative'], _get_disk_template_objects(partition, 'directory')
                    ))
                    stats['template']['files'] = list(map(
                        lambda u: u['relative'], _get_disk_template_objects(partition, 'file')
                    ))
                # make sure that all the partitions are there
                for partition in partitions:
                    # check if the partition defined in the disk_template dir exists
                    if partition not in DISK_IMAGE_PARTITION_TABLE:
                        raise ValueError(f'Partition {partition} not declared in partition table')
                    # check if the corresponding disk device exists
                    partition_disk = DISK_DEVICE(
                        device=loopdev, partition_id=DISK_IMAGE_PARTITION_TABLE[partition]
                    )
                    if not os.path.exists(partition_disk):
                        raise ValueError(f'Disk device {partition_disk} not found')
                    # mount device
                    _mount_partition(partition)
                    # from this point on, if anything weird happens, unmount the disk
                    try:
                        dtslogger.info(f'Updating partition "{partition}":')
                        # create directory structure from disk template
                        for update in _get_disk_template_objects(partition, 'directory'):
                            dtslogger.info(f"- Creating directory [{update['relative']}]")
                            # create destination
                            _run_cmd(['sudo', 'mkdir', '-p', update['destination']])
                        # apply changes from disk_template
                        for update in _get_disk_template_objects(partition, 'file'):
                            effect = 'MODIFY' if os.path.exists(update['destination']) else 'NEW'
                            dtslogger.info(f"- Updating file ({effect}) [{update['relative']}]")
                            # copy new file
                            _run_cmd(['sudo', 'cp', update['origin'], update['destination']])
                            # get first line of file
                            file_first_line = _get_file_first_line(update['destination'])
                            # only files containing a known placeholder will be part of the surgery
                            if file_first_line.startswith(FILE_PLACEHOLDER_SIGNATURE):
                                placeholder = file_first_line[len(FILE_PLACEHOLDER_SIGNATURE):]
                                # get stats about file
                                real_bytes, max_bytes = _get_file_length(update['destination'])
                                # saturate file so that it occupies the entire pagefile
                                _run_cmd(['sudo', 'truncate', f'--size={max_bytes}',
                                          update['destination']])
                                # store preliminary info about the surgery
                                surgery_plan.append({
                                    'partition': partition,
                                    'partition_id': DISK_IMAGE_PARTITION_TABLE[partition],
                                    'path': update['relative'],
                                    'placeholder': placeholder,
                                    'offset_bytes': None,
                                    'used_bytes': real_bytes,
                                    'length_bytes': max_bytes
                                })
                        # store stats before closing the [root] partition
                        if partition == ROOT_PARTITION:
                            stats_filepath = os.path.join(
                                PARTITION_MOUNTPOINT(partition), DISK_IMAGE_STATS_LOCATION
                            )
                            with open(out_file_path('stats'), 'wt') as fout:
                                json.dump(stats, fout, indent=4, sort_keys=True)
                            _run_cmd(['sudo', 'cp', out_file_path('stats'), stats_filepath])
                        # ---
                        dtslogger.info(f'Partition {partition} updated!')
                    except Exception as e:
                        _umount_partition(partition)
                        raise e
                    # umount partition
                    _umount_partition(partition)
                # ---
            except Exception as e:
                _umount_virtual_sd_card(out_file_path('img'))
                raise e
            # finalize surgery plan
            dtslogger.info('Locating files for surgery in disk image...')
            placeholders = _find_placeholders_on_disk(out_file_path('img'))
            for i in range(len(surgery_plan)):
                full_placeholder = f"{FILE_PLACEHOLDER_SIGNATURE}{surgery_plan[i]['placeholder']}"
                # check if the placeholder was found
                if full_placeholder not in placeholders:
                    raise ValueError(f"The string \"{full_placeholder}\" "
                                     f"was not found in the disk image {out_file_path('img')}")
                # update surgery plan
                surgery_plan[i]['offset_bytes'] = placeholders[full_placeholder]
            dtslogger.info('All files located successfully!')
            dtslogger.info('Step END: setup\n')
        # Step: setup
        # <------
        #
        # ------>
        # Step: docker
        if 'docker' in parsed.steps:
            dtslogger.info('Step BEGIN: docker')
            # from this point on, if anything weird happens, unmount the disk
            try:
                # make sure that the disk is mounted
                if loopdev is None:
                    dtslogger.error(f"The disk {out_file_path('img')} is not mounted.")
                    return
                # check if the corresponding disk device exists
                partition_disk = DISK_DEVICE(
                    device=loopdev, partition_id=DISK_IMAGE_PARTITION_TABLE[ROOT_PARTITION]
                )
                if not os.path.exists(partition_disk):
                    raise ValueError(f'Disk device {partition_disk} not found')
                # mount device
                _mount_partition(ROOT_PARTITION)
                # get local docker client
                local_docker = docker.from_env()
                # pull dind image
                _pull_docker_image(local_docker, 'docker:dind')
                # run auxiliary Docker engine
                remote_docker_dir = os.path.join(
                    PARTITION_MOUNTPOINT(ROOT_PARTITION), 'var', 'lib', 'docker'
                )
                remote_docker_engine_container = local_docker.containers.run(
                    image='docker:dind',
                    detach=True,
                    auto_remove=True,
                    publish_all_ports=True,
                    privileged=True,
                    name='dts-disk-image-aux-docker',
                    volumes={
                        remote_docker_dir: {
                            'bind': '/var/lib/docker',
                            'mode': 'rw'
                        }
                    },
                    entrypoint=['dockerd', '--host=tcp://0.0.0.0:2375']
                )
                time.sleep(2)
                # get IP address of the container
                container_info = local_docker.api.inspect_container('dts-disk-image-aux-docker')
                container_ip = container_info['NetworkSettings']['IPAddress']
                # create remote docker client
                time.sleep(2)
                remote_docker = docker.DockerClient(base_url=f"tcp://{container_ip}:2375")
                # from this point on, if anything weird happens, stop container and unmount disk
                try:
                    dtslogger.info('Transferring Docker images...')
                    # pull images inside the disk image
                    for module in MODULES_TO_LOAD:
                        image = DOCKER_IMAGE_TEMPLATE(
                            owner=module['owner'], module=module['module'], version=major_version,
                            tag=module['tag'] if 'tag' in module else None
                        )
                        _pull_docker_image(remote_docker, image)
                    # ---
                    dtslogger.info('Docker images successfully transferred!')
                except Exception as e:
                    # unmount disk
                    _umount_virtual_sd_card(out_file_path('img'))
                    raise e
                finally:
                    # stop container
                    remote_docker_engine_container.stop()
                    # unmount partition
                    _umount_partition(ROOT_PARTITION)
                # ---
            except Exception as e:
                # unmount disk
                _umount_virtual_sd_card(out_file_path('img'))
                raise e
            dtslogger.info('Step END: docker\n')
        # Step: docker
        # <------
        #
        # ------>
        # Step: finalize
        if 'finalize' in parsed.steps:
            dtslogger.info('Step BEGIN: finalize')
            # compute image sha256
            dtslogger.info(f"Computing SHA256 checksum of {out_file_path('img')}...")
            disk_image_sha256 = _get_disk_image_sha(out_file_path('img'))
            dtslogger.info(f"SHA256: {disk_image_sha256}")
            # store surgery plan and other info
            dtslogger.info(f"Storing metadata in {out_file_path('json')}...")
            metadata = {
                'version': DISK_IMAGE_FORMAT_VERSION,
                'disk_image': os.path.basename(out_file_path('img')),
                'sha256': disk_image_sha256,
                'surgery_plan': surgery_plan
            }
            with open(out_file_path('json'), 'wt') as fout:
                json.dump(metadata, fout, indent=4, sort_keys=True)
            dtslogger.info("Done!")
            dtslogger.info('Step END: finalize\n')
        # Step: finalize
        # <------
        #
        # ------>
        # Step: unmount
        if 'unmount' in parsed.steps:
            dtslogger.info('Step BEGIN: unmount')
            _umount_virtual_sd_card(out_file_path('img'))
            dtslogger.info('Step END: unmount\n')
        # Step: unmount
        # <------
        #
        # ------>
        # Step: compress
        if 'compress' in parsed.steps:
            dtslogger.info('Step BEGIN: compress')
            dtslogger.info('Compressing disk image...')
            _run_cmd([
                'zip', '-j', out_file_path('zip'), out_file_path('img'), out_file_path('json')
            ])
            dtslogger.info('Done!')
            dtslogger.info('Step END: compress\n')
        # Step: compress
        # <------

    @staticmethod
    def complete(shell, word, line):
        return []


def _check_cli_tools():
    for cli_tool in CLI_TOOLS_NEEDED:
        check_program_dependency(cli_tool)


def _pull_docker_image(client, image):
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


def _get_device_disk_identifier(device):
    dtslogger.info(f'Reading Disk Identifier for {device}...')
    p = re.compile(".*Disk identifier: 0x([0-9a-z]*).*")
    fdisk_out = _run_cmd(["sudo", "fdisk", "-l", device], get_output=True)
    m = p.search(fdisk_out)
    disk_identifier = m.group(1)
    dtslogger.info(f'Disk Identifier[{device}]: {disk_identifier}')
    return disk_identifier


def _set_device_disk_identifier(device, disk_identifier):
    dtslogger.info(f'Re-applying disk identifier ({disk_identifier}) -> [{device}]')
    cmd = ["sudo", "fdisk", device]
    dtslogger.debug("$ %s" % cmd)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    p.communicate(("x\ni\n0x%s\nr\nw" % disk_identifier).encode("ascii"))
    dtslogger.info('Done!')


def _get_disk_image_sha(disk_image_file):
    return _run_cmd(['sha256sum', disk_image_file], get_output=True).split(' ')[0]


def _get_disk_template_partitions():
    disk_template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'disk_template')
    return list(filter(
        lambda d: os.path.isdir(os.path.join(disk_template_dir, d)),
        os.listdir(disk_template_dir)
    ))


def _get_disk_template_objects(partition, filter_type):
    disk_template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'disk_template')
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


def _find_placeholders_on_disk(disk_image):
    matches = _run_cmd(
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


def _get_file_first_line(filepath):
    with open(filepath, 'rt') as f:
        line = f.readline()
    return line


def _get_file_length(filepath):
    stat_out = _run_cmd(['stat', '--format', '%s,%b,%B', filepath], get_output=True)
    real_size, num_blocks, block_size = stat_out.strip().split(',')
    return int(real_size), int(num_blocks) * int(block_size)


def _mount_partition(partition):
    dtslogger.info(f'Mounting partition "{partition}"...')
    # refresh devices module
    for i in range(3):
        if os.path.exists(DISK_BY_LABEL(partition)):
            break
        # refresh kernel module
        _run_cmd(['sudo', 'udevadm', 'trigger'])
        # wait for changes to take effect
        if i > 0:
            dtslogger.info('Waiting for the device module to pick up the changes')
            time.sleep(2)
    # mount partition
    if not os.path.exists(PARTITION_MOUNTPOINT(partition)):
        _run_cmd(["udisksctl", "mount", "-b", DISK_BY_LABEL(partition)])
    # ---
    assert os.path.exists(PARTITION_MOUNTPOINT(partition))
    dtslogger.info(f'Partition "{partition}" successfully mounted!')


def _umount_partition(partition):
    dtslogger.info(f'Unmounting partition "{partition}"...')
    # refresh devices module
    _run_cmd(['sudo', 'udevadm', 'trigger'])
    # unmount partition
    if os.path.exists(PARTITION_MOUNTPOINT(partition)):
        # try to unmount
        for i in range(3):
            if not os.path.exists(PARTITION_MOUNTPOINT(partition)):
                break
            # request unmount
            _run_cmd(["udisksctl", "unmount", "-b", DISK_BY_LABEL(partition)], get_output=True)
            # wait for changes to take effect
            if i > 0:
                dtslogger.info(f'Waiting for the device {DISK_BY_LABEL(partition)} to unmount')
                time.sleep(2)
    # ---
    dtslogger.info(f'Partition "{partition}" successfully unmounted!')


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


def _find_virtual_sd_card(disk_file, quiet=False):
    # mount loop device
    if not quiet:
        dtslogger.info(f"Looking for loop devices associated to disk image {disk_file}...")
    try:
        # iterate over loop devices
        lodevices = json.loads(_run_cmd(["sudo", "losetup", "--json"], get_output=True))
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


def _mount_virtual_sd_card(disk_file):
    # refresh devices module
    _run_cmd(['sudo', 'udevadm', 'trigger'])
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
    if os.path.exists(DISK_BY_LABEL('HypriotOS')) or os.path.exists(DISK_BY_LABEL('root')):
        dtslogger.error(
            'Another partition with the same names (HypriotOS, root) was found in the system. '
            'Detach them before continuing.'
        )
        exit(4)
    # mount loop device
    lodev = subprocess.check_output(
        ["sudo", "losetup", "--show", "-fPL", disk_file]
    ).decode('utf-8').strip()
    # refresh devices module
    _run_cmd(['sudo', 'udevadm', 'trigger'])
    # ---
    return lodev


def _umount_virtual_sd_card(disk_file, quiet=False):
    # mount loop device
    if not quiet:
        dtslogger.info(f"Closing disk {disk_file}...")
    try:
        # free loop devices
        output = subprocess.check_output(["sudo", "losetup", "--json"]).decode('utf-8')
        devices = json.loads(output)
        for dev in devices['loopdevices']:
            if not ('(deleted)' in dev['back-file']
                    or dev['back-file'].split(' ')[0] == disk_file):
                continue
            if not quiet:
                dtslogger.info(f"Unmounting {disk_file} from {dev['name']}...")
            _run_cmd(['sudo', 'losetup', '-d', dev['name']])
    except Exception as e:
        if not quiet:
            raise e
    if not quiet:
        dtslogger.info("Done!")
    # refresh devices module
    _run_cmd(['sudo', 'udevadm', 'trigger'])
