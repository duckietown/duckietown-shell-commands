from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.assets_utils import get_asset_dir
from utils.docker_utils import get_remote_client
from utils.table_utils import format_matrix, fill_cell

import os
import yaml
import argparse
import glob
from pathlib import Path

SUPPORTED_TYPES = ['auto', 'duckiebot', 'duckiedrone', 'watchtower']
DOCKER_LABEL_DOMAIN = "org.duckietown.label"


class DTCommand(DTCommandAbs):

    help = 'Lists all the modules running on a robot'

    def _get_parser(shell: DTShell):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('-H', '--hostname', required=True,
                            help="Hostname of the targer device")
        parser.add_argument('-t', '--type', default='auto', choices=SUPPORTED_TYPES,
                            help="Robot type")
        parser.add_argument('-c', '--configuration', default='advanced',
                            help="Configuration to load")
        # ---
        return parser

    @staticmethod
    def command(shell: DTShell, args):
        parser = DTCommand._get_parser(shell)
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        if parsed.type == 'auto':
            from utils.avahi_utils import wait_for_service
            # retrieve robot type from device
            dtslogger.info(f'Waiting for device "{parsed.hostname}"...')
            hostname = parsed.hostname.replace('.local', '')
            _, _, data = wait_for_service('DT::ROBOT_TYPE', hostname)
            robot_type = data['type']
        else:
            robot_type = parsed.type
        # retrieve all known modules
        dtslogger.info('Loading modules...')
        modules = _load_all_modules(robot_type)
        # retrieve robot configurations
        dtslogger.info('Loading configurations...')
        configs = _load_all_configurations(robot_type)
        if parsed.configuration and parsed.configuration not in configs:
            raise ValueError(f'Configuration "{parsed.configuration}" not found for robot type "{robot_type}"!')
        # read given configuration
        configuration = yaml.load(open(configs[parsed.configuration]).read(), Loader=yaml.FullLoader)
        # get list of modules running on the device
        modules_running = _get_running_modules(parsed.hostname)
        # prepare table
        header = ['Status', 'Running', '#', 'Image', 'Official']
        data = []
        for module, module_info in configuration['modules'].items():
            module_type = module_info['type']
            # case 1: no instance of the module running
            if module_type not in modules_running:
                status = 'Ok' if ('required' not in module_info or not module_info['required']) else 'Missing'
                status = _format('status', status, 'Status')
                running = _format(bool, False, 'Running')
                image = 'ND'
                auth = _format(bool, False, 'Official')
                row = [module, status, running, 0, image, auth]
                data.append(row)
                continue
            # case 2: one or more instances of the module running
            instances = modules_running[module_type]
            for i in range(len(instances)):
                status = 'Ok' if (('unique' not in module_info) or (module_info['unique'] and len(instances) == 1)) else 'Conflict'
                status = _format('status', status, 'Status')
                instance = instances[i]
                running = _format(bool, True, 'Running')
                image = instance['image']
                auth = _format(bool, instance['authoritative'], 'Official')
                row = [module, status, running, i+1, image, auth]
                data.append(row)
        # print table
        print('\n')
        print(format_matrix(
            header,
            data,
            '{:^{}}', '{:<{}}', '{:<{}}', '\n', ' | '
        ))

    @staticmethod
    def complete(shell, word, line):
        parser = DTCommand._get_parser(shell)
        return list(vars(parser)['_option_string_actions'].keys())



def _load_all_modules(robot_type):
    stacks_location = os.path.join(get_asset_dir('dt-docker-stacks'), 'stacks', robot_type)
    stacks = {
        Path(f).stem : f for f in \
        glob.glob(os.path.join(stacks_location, '*.yaml')) + \
        glob.glob(os.path.join(stacks_location, '*.yml'))
    }
    modules = dict()
    for stack_name, stack_file in stacks.items():
        stack_content = yaml.load(open(stack_file).read(), Loader=yaml.FullLoader)
        for module, module_info in stack_content['services'].items():
            modules[module] = {
                'stack': stack_name,
                'default_image': module_info['image']
            }
    # ---
    return modules

def _load_all_configurations(robot_type):
    configs_location = os.path.join(get_asset_dir('dt-docker-stacks'), 'configurations', robot_type)
    configs = {
        Path(f).stem : f for f in \
        glob.glob(os.path.join(configs_location, '*.yaml')) + \
        glob.glob(os.path.join(configs_location, '*.yml'))
    }
    # ---
    return configs

def _get_running_modules(hostname):
    # open Docker client
    client = get_remote_client(hostname)
    auth_label = f'{DOCKER_LABEL_DOMAIN}.authoritative'
    module_type_label = f'{DOCKER_LABEL_DOMAIN}.module.type'
    # get all running containers
    containers = client.containers.list()
    modules = dict()
    for container in containers:
        image = container.attrs['Config']['Image']
        name = container.attrs['Name']
        labels = container.attrs['Config']['Labels']
        module = labels[module_type_label] if module_type_label in labels else None
        is_authoritative = (auth_label in labels) and (labels[auth_label] == '1')
        if not module:
            continue
        if module not in modules:
            modules[module] = []
        modules[module].append({
            'type': module,
            'image': image,
            'name': name,
            'authoritative': is_authoritative
        })
    # ---
    return modules

def _format(type, value, header):
    if type == bool:
        text = 'Yes' if value else 'No'
        fg = 'white'
        bg = 'green' if value else None
    if type == 'status':
        text = value
        fg = 'white'
        bg = 'green' if value == 'Ok' else 'red'
    return fill_cell(text, len(header), fg, bg)
