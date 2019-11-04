from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.assets_utils import get_asset_dir
from utils.docker_utils import get_remote_client, DEFAULT_DOCKER_TCP_PORT
from utils.table_utils import format_matrix, fill_cell
from utils.duckietown_utils import get_robot_types
from utils.cli_utils import start_command_in_subprocess, get_clean_env
from init_sd_card.command import \
    MINIMAL_STACKS_TO_LOAD, \
    DEFAULT_STACKS_TO_LOAD, \
    DEFAULT_STACKS_TO_RUN, \
    AIDO_STACKS_TO_LOAD

import os
import yaml
import argparse
import glob
import time
import requests
from shutil import which
from pathlib import Path
from docker.errors import APIError


DEFAULT_REMOTE_USERNAME = 'duckie'
LOADER_DIR = '/data/loader'
LOADER_CONFIG_DIRS = ['images_to_load', 'stacks_to_load', 'stacks_to_run']
BINARIES_DEPS = ['ssh', 'scp', 'docker-compose']
DASHBOARD_WAIT_TIMEOUT_SECS = 60

class DTCommand(DTCommandAbs):

    help = 'Resets a Duckiebot to a clean status'

    def _get_parser(shell: DTShell):
        supported_robot_types = ['auto'] + get_robot_types()
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            '-y', '--non-interactive',
            dest='no_confirm',
            default=False,
            action="store_true",
            help="Non-interactive mode, the command will not ask for confirmation"
        ),
        parser.add_argument(
            '-H', '--hostname',
            required=True,
            help="Hostname of the targer device"
        )
        parser.add_argument(
            '-t', '--type',
            default='auto',
            choices=supported_robot_types,
            help="Robot type"
        )
        parser.add_argument(
            '-u', '--username',
            default=DEFAULT_REMOTE_USERNAME,
            help="Username used to connect to the remote target device"
        )
        parser.add_argument(
            "--stacks-load",
            dest="stacks_to_load",
            default=DEFAULT_STACKS_TO_LOAD,
            help="Which stacks to load",
        )
        parser.add_argument(
            "--stacks-run",
            dest="stacks_to_run",
            default=DEFAULT_STACKS_TO_RUN,
            help="Which stacks to RUN by default",
        )
        parser.add_argument(
            "--aido",
            dest="aido",
            default=False,
            action="store_true",
            help="Only load what is necessary for an AI-DO submission",
        )
        # ---
        return parser

    @staticmethod
    def command(shell: DTShell, args):
        parser = DTCommand._get_parser(shell)
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        # if aido is set overwrite the stacks
        if parsed.aido:
            dtslogger.info('Configuring an AIDO device.')
            parsed.stacks_to_load = AIDO_STACKS_TO_LOAD
            parsed.stacks_to_run = parsed.stacks_to_load
        # get robot_type
        robot_name = parsed.hostname.replace('.local', '')
        if parsed.type == 'auto':
            from utils.avahi_utils import wait_for_service
            # retrieve robot type from device
            dtslogger.info(f'Waiting for device "{parsed.hostname}"...')
            hostname = parsed.hostname.replace('.local', '')
            _, _, data = wait_for_service('DT::ROBOT_TYPE', hostname)
            robot_type = data['type']
            dtslogger.info(f'Device type is "{robot_type}".')
        else:
            dtslogger.info(f'Device type forced to "{parsed.type}".')
            robot_type = parsed.type
        # retrieve stacks
        dtslogger.info('Loading stacks...')
        stacks = _get_stacks_list(robot_type)
        # read and validate docker-compose stacks
        stacks_to_load = list(filter(lambda s: len(s) > 0, parsed.stacks_to_load.split(",")))
        stacks_to_run = list(filter(lambda s: len(s) > 0, parsed.stacks_to_run.split(",")))
        for stack in stacks_to_load + stacks_to_run + MINIMAL_STACKS_TO_LOAD:
            if stack not in stacks:
                dtslogger.error(f'The stack {stack} was not found in the assets directory.')
                return
        dtslogger.info("Stacks to load: %s" % stacks_to_load)
        dtslogger.info("Stacks to run: %s" % stacks_to_run)
        # get info about docker
        docker = get_remote_client(parsed.hostname)
        docker_info = docker.info()
        dtslogger.info(f"""
The current status of the Docker environment on {robot_name} is:
    - Images: {docker_info['Images']};
    - Containers: {docker_info['Containers']};
        - Running: {docker_info['ContainersRunning']};
        - Paused: {docker_info['ContainersPaused']};
        - Stopped: {docker_info['ContainersStopped']};
    - Volumes: {len(docker.volumes.list())};
    - Networks: {len(docker.networks.list())};

We will remove EVERYTHING.
        """)
        if not parsed.no_confirm:
            r = input('Do you want to proceed? y/n [n]: ')
            if r.strip() not in ['y', 'Y', 'yes', 'YES', 'yup', 'YUP']:
                dtslogger.info('Aborting.')
                return
        # ---
        # 0.1. Try to connect to the target via SSH
        try:
            start_command_in_subprocess([
                'ssh',
                '-oStrictHostKeyChecking=no',
                f'{parsed.username}@{parsed.hostname}',
                    'exit'
            ], shell=False, nostdout=True)
        except:
            dtslogger.error(
f"""
An error occurred while trying to connect to the target {parsed.hostname} via SSH.
Make sure you can connect to the target device via SSH with no password.
Retry once you can successfully run the following command in your terminal:

    ssh {parsed.username}@{parsed.hostname}

            """)
            return
        # 0.2 Look for dependencies
        for bin in BINARIES_DEPS:
            if not which(bin):
                dtslogger.error(f'The command {bin} was not found. Make sure it is available on your system before trying again.')
                return
        # 1. STOP all containers
        dtslogger.info(f'Stopping all containers on {parsed.hostname}...')
        for container in docker.containers.list():
            dtslogger.info(f'\t> Stopping {container.name}...')
            container.stop()
        # 2. REMOVE all containers
        dtslogger.info(f'Removing all containers on {parsed.hostname}...')
        docker.containers.prune()
        # 2.1. Make sure there are no running containers
        assert len(docker.containers.list(all=True)) == 0
        # 3. REMOVE all images
        dtslogger.info(f'Removing all images on {parsed.hostname}...')
        removed = 1
        while removed > 0:
            removed = 0
            for image in docker.images.list():
                docker.images.remove(image=image.id, force=True, noprune=False)
                image_name = image.tags[0] if len(image.tags) else image.id
                dtslogger.info(f'\t> Removed {image_name}...')
                removed += 1
        docker.images.prune()
        # 3.1. Make sure there are no images left
        assert len(docker.images.list(all=True)) == 0
        # 4. REMOVE all volumes
        dtslogger.info(f'Removing all volumes on {parsed.hostname}...')
        docker.volumes.prune()
        # 4.1. Make sure there are no volumes left
        assert len(docker.volumes.list()) == 0
        # 5. REMOVE all networks
        dtslogger.info(f'Removing all networks on {parsed.hostname}...')
        docker.networks.prune()
        # 6. Remove stacks/images-to-load/run from /data/loader
        dtslogger.info(f'Removing old Docker stacks from {parsed.hostname}...')
        for dir in LOADER_CONFIG_DIRS:
            start_command_in_subprocess([
                'ssh',
                '-oStrictHostKeyChecking=no',
                f'{parsed.username}@{parsed.hostname}',
                    'sudo', 'rm', '-rf', f'{LOADER_DIR}/{dir}/*'
            ], shell=False, nostdout=True)
        # 6.1 Fix permissions
        start_command_in_subprocess([
            'ssh',
            '-oStrictHostKeyChecking=no',
            f'{parsed.username}@{parsed.hostname}',
                'sudo', 'chown', '-R', parsed.username, f'{LOADER_DIR}/*'
        ], shell=False, nostdout=True)
        # 7. Copy new stacks/images-to-load/run to /data/loader
        dtslogger.info(f'Copying new Docker stacks to {parsed.hostname}...')
        stacks_location = {
            'stacks_to_load': set(stacks_to_load),
            'stacks_to_run': set(stacks_to_run + MINIMAL_STACKS_TO_LOAD)
        }
        for stacks_loc, stacks_lst in stacks_location.items():
            for stack in stacks_lst:
                lpath = stacks[stack]
                rpath = f'{LOADER_DIR}/{stacks_loc}/{stack}.yaml'
                start_command_in_subprocess([
                    'scp',
                    '-oStrictHostKeyChecking=no',
                        lpath,
                        f'{parsed.username}@{parsed.hostname}:{rpath}'
                ], shell=False, nostdout=True)
        # 8. Run minimal configuration
        dtslogger.info(f'Running device-loader on {parsed.hostname}...')
        env = get_clean_env().update({
            'DOCKER_CLIENT_TIMEOUT': 120,
            'COMPOSE_HTTP_TIMEOUT': 120
        })
        for stack in MINIMAL_STACKS_TO_LOAD:
            lpath = stacks[stack]
            start_command_in_subprocess([
                'docker-compose',
                '-H', f'{parsed.hostname}:{DEFAULT_DOCKER_TCP_PORT}',
                    "--file",
                    lpath,
                    "-p",
                    stack,
                    "up",
                    "-d"
            ], env=env, shell=False, retry=3)
        # 8. Wait for the dashboard to be up
        dtslogger.info(f'Waiting for {parsed.hostname} to be ready...')
        dashboard_up = False
        stime = time.time()
        while (not dashboard_up) and (time.time() - stime < DASHBOARD_WAIT_TIMEOUT_SECS):
            dashboard_url = f'http://{parsed.hostname}:80'
            try:
                response = requests.get(dashboard_url, timeout=4)
                dashboard_up = response.status_code == 200
            except:
                time.sleep(4)
        if dashboard_up:
            dtslogger.info(
f"""
The device {parsed.hostname} is now initializing...
Open the browser and visit the following URL to monitor this process and configure the device.

    http://{parsed.hostname}/

Done!
""")
        else:
            dtslogger.warning(
f"""We cannot confirm that the device is ready.
If you cannot reach the Dashboard at http://{parsed.hostname}/ within the next few minutes, retry a factory reset.
""")


    @staticmethod
    def complete(shell, word, line):
        parser = DTCommand._get_parser(shell)
        return list(vars(parser)['_option_string_actions'].keys())



def _get_stacks_list(robot_type):
    stacks_location = os.path.join(get_asset_dir('dt-docker-stacks'), 'stacks', robot_type)
    stacks = {
        Path(f).stem : f for f in \
        glob.glob(os.path.join(stacks_location, '*.yaml')) + \
        glob.glob(os.path.join(stacks_location, '*.yml'))
    }
    # ---
    return stacks
