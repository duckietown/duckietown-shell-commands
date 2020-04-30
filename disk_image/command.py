from dt_shell import DTCommandAbs, dtslogger, DTShell

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
import sys


PARTITION_MOUNTPOINT = lambda partition: f"/media/{getpass.getuser()}/{partition}"

DISK_DEVICE = lambda device, partition_id: f"{device}p{partition_id}"

DISK_BY_LABEL = lambda partition: f"/dev/disk/by-label/{partition}"

DISK_IMAGE_PARTITION_TABLE = {
    'HypriotOS': 1,
    'root': 2
}

ROOT_PARTITION = 'root'

FILE_PLACEHOLDER_SIGNATURE = "DT_DUCKIETOWN_PLACEHOLDER_"

DEVICE_ARCH = 'arm32v7'
DOCKER_IMAGE_TEMPLATE = lambda owner, module, tag=None, version=None: \
    f'{owner}/{module}:' + ((f'{version}-%s' % DEVICE_ARCH) if tag is None else tag)

MODULES_TO_LOAD = [
    {
        'owner': 'portainer',
        'module': 'portainer',
        'tag': 'linux-arm'
    },
    # TODO: there is no daffy version for this, fix!
    # {
    #     'owner': 'duckietown',
    #     'module': 'dt-device-health'
    # },
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

SUPPORTED_STEPS = ['create', 'mount', 'setup', 'docker', 'finalize', 'unmount']

CLI_TOOLS_NEEDED = [
    'sudo', 'cp', 'sha256sum', 'strings', 'grep', 'stat', 'udevadm', 'udisksctl', 'losetup'
]


class DTCommand(DTCommandAbs):

    help = 'Prepares an .img disk file for a Raspberry Pi'

    @staticmethod
    def command(shell: DTShell, args):
        parser = argparse.ArgumentParser()
        # define parser arguments
        parser.add_argument(
            "--steps", type=str,
            default=','.join(SUPPORTED_STEPS),
            help="List of steps to perform (comma-separated)",
        )
        parser.add_argument(
            "-o", "--output", default=None,
            help="The destination directory for the output file"
        )
        parser.add_argument(
            'image',
            help="Input .img disk image file"
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
        # check if the input file exists
        if not os.path.isfile(parsed.image):
            dtslogger.error('The file %s does not exist' % parsed.image)
            return
        # check if the output directory exists, create it if it does not
        if parsed.output is None:
            parsed.output = os.getcwd()
        if not os.path.exists(parsed.output):
            os.makedirs(parsed.output)
        # get image name
        input_image_name = pathlib.Path(parsed.image).stem
        # define output file template
        out_file_path = lambda e: os.path.join(parsed.output, f'dt-{input_image_name}.{e}')
        # this will hold the link to the loop device
        loopdev = None
        surgery_plan = []
        #
        # STEPS:
        # ------>
        # Step: create
        if 'create' in parsed.steps:
            dtslogger.info('Step BEGIN: create')
            # check if the destination image already exists
            if os.path.exists(out_file_path('img')):
                dtslogger.warn(f"The destination file {out_file_path('img')} already exists.")
                dtslogger.warn('If we proceed, the file will be overwritten.')
                r = input('Confirm? [y]')
                if r.strip() not in ['', 'y', 'Y', 'yes', 'YES', 'yup', 'YUP', 'yep', 'YEP']:
                    dtslogger.info('Aborting.')
                    return
            # make copy
            dtslogger.info(f"Copying [{parsed.image}] -> [{out_file_path('img')}]")
            shutil.copyfile(parsed.image, out_file_path('img'))
            dtslogger.info('Disk image created.')
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
                        # apply changes from disk_template
                        for update in _get_disk_template_files(partition):
                            effect = 'MODIFY' if os.path.exists(update['destination']) else 'NEW'
                            dtslogger.info(f"- Updating file ({effect}) [{update['relative']}]")
                            # create destination
                            destination_dir = os.path.dirname(update['destination'])
                            _run_cmd(['sudo', 'mkdir', '-p', destination_dir])
                            # copy new file
                            _run_cmd(['sudo', 'cp', update['origin'], update['destination']])
                            # get first line of file
                            file_first_line = _get_file_first_line(update['destination'])
                            # only files containing a known placeholder will be part of the surgery
                            if file_first_line.startswith(FILE_PLACEHOLDER_SIGNATURE):
                                # get stats about file
                                real_bytes, max_bytes = _get_file_length(update['destination'])
                                # store preliminary info about the surgery
                                surgery_plan.append({
                                    'partition': partition,
                                    'partition_id': DISK_IMAGE_PARTITION_TABLE[partition],
                                    'path': update['relative'],
                                    'placeholder': file_first_line,
                                    'offset_bytes': None,
                                    'used_bytes': real_bytes,
                                    'length_bytes': max_bytes
                                })
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
            dtslogger.info('Step END: setup\n')
        # Step: setup
        # <------
        #
        # ------>
        # Step: docker
        if 'docker' in parsed.steps:
            dtslogger.info('Step BEGIN: docker')
            major_version = shell.get_commands_version().split('-')[0]
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
            # finalize surgery plan
            dtslogger.info('Locating files location in disk image...')
            for i in range(len(surgery_plan)):
                surgery_bit = surgery_plan[i]
                # update surgery plan
                surgery_bit['offset_bytes'] = _get_file_location_on_disk(
                    out_file_path('img'), surgery_bit['placeholder']
                )
                surgery_plan[i] = surgery_bit
            dtslogger.info('All files located successfully!')
            # compute image sha256
            dtslogger.info(f"Computing SHA256 checksum of {out_file_path('img')}...")
            disk_image_sha256 = _get_disk_image_sha(out_file_path('img'))
            dtslogger.info(f"SHA256: {disk_image_sha256}")
            # store surgery plan and other info
            dtslogger.info(f"Storing metadata in {out_file_path('json')}...")
            with open(out_file_path('json'), 'wt') as fout:
                json.dump(
                    {
                        'disk_image': os.path.basename(out_file_path('img')),
                        'sha256': disk_image_sha256,
                        'surgery_plan': surgery_plan
                    },
                    fout,
                    indent=4,
                    sort_keys=True
                )
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

    @staticmethod
    def complete(shell, word, line):
        return []


def _check_cli_tools():
    for cli_tool in CLI_TOOLS_NEEDED:
        if not shutil.which(cli_tool):
            dtslogger.error(f'The cli tool "{cli_tool}" is needed and cannot be found.')
            exit(1)


class ProgressBar:

    def __init__(self):
        self._finished = False

    def update(self, percentage):
        if self._finished:
            return
        # compile progress bar
        pbar = "Progress: ["
        # progress
        pbar += "=" * percentage
        if percentage < 100:
            pbar += ">"
        pbar += " " * (100 - percentage - 1)
        # this ends the progress bar
        pbar += f"] {percentage}%"
        # print
        sys.stdout.write(pbar)
        sys.stdout.flush()
        # return to start of line
        sys.stdout.write("\b" * len(pbar))
        # end progress bar
        if percentage >= 100:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._finished = True


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


def _get_disk_image_sha(disk_image_file):
    return _run_cmd(['sha256sum', disk_image_file], get_output=True).split(' ')[0]


def _get_disk_template_partitions():
    disk_template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'disk_template')
    return list(filter(
        lambda d: os.path.isdir(os.path.join(disk_template_dir, d)),
        os.listdir(disk_template_dir)
    ))


def _get_disk_template_files(partition):
    disk_template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'disk_template')
    partition_template_dir = os.path.join(disk_template_dir, partition)
    # check if we know about this partition
    if not os.path.isdir(partition_template_dir):
        raise ValueError(f'Partition "{partition}" not found in disk template.')
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
        for f in glob_star if os.path.isfile(f)
    ]


def _get_file_location_on_disk(disk_image, placeholder):
    matches = _run_cmd(
        ['strings', '-t', 'd', disk_image, '|', 'grep', f'"{placeholder}"'],
        get_output=True, shell=True
    ).splitlines()
    # the match has to be unique
    if len(matches) == 0:
        raise ValueError(f'The string "{placeholder}" was not found in disk image {disk_image}')
    if len(matches) > 1:
        raise ValueError(
            f'The string "{placeholder}" is not unique in disk image {disk_image}, '
            f'{len(matches)} were found!'
        )
    # single match, nice!
    return int(matches[0].split(' ')[0])


def _get_file_first_line(filepath):
    line = None
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
            if not ('(deleted)' in dev['back-file'] or dev['back-file'].split(' ')[0] == disk_file):
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
