import yaml
import requests
from dt_shell import dtslogger

ARCHITECTURE_API_MODULE_DESCRIPTOR_URL = \
    'http://{machine}/architecture/module/info/{module}'
ARCHITECTURE_DATA_MODULE_DESCRIPTOR = \
    'https://raw.githubusercontent.com/duckietown/dt-architecture-data/{ver}/modules/{module}.yaml'


def get_module_configuration(module_name, shell, parsed):
    module_configuration = {}
    # 1. try to get the configuration from the architecture API running on the destination
    module_descriptor_api_url = ARCHITECTURE_API_MODULE_DESCRIPTOR_URL.format(
        machine=parsed.machine if not parsed.machine.startswith('unix://') else 'localhost',
        module=module_name
    )
    try:
        response = requests.get(module_descriptor_api_url)
        module_descriptor = response.json()
        module_configuration = module_descriptor['configuration']
        dtslogger.info(
            "The Architecture API provided a module configuration for {:s}.".format(module_name)
        )
    except (KeyError, ValueError, TypeError, Exception):
        dtslogger.warn(
            "We couldn't get a module configuration from the Architecture API. "
            "Falling back to GitHub repository."
        )
    # 2. fallback to reading the module configuration from github
    module_descriptor_file_url = ARCHITECTURE_DATA_MODULE_DESCRIPTOR.format(
        ver=shell.get_commands_version(),
        module=module_name
    )
    try:
        response = requests.get(module_descriptor_file_url)
        module_descriptor = yaml.load(response.text, Loader=yaml.FullLoader)
        module_configuration = module_descriptor['configuration']
        dtslogger.info(
            "A module configuration for {:s} was fetched from GitHub".format(module_name)
        )
    except (KeyError, ValueError, TypeError, Exception):
        dtslogger.warn(
            "We couldn't find a module configuration on the dt-architecture-data repository. "
            "Using default configuration instead."
        )
    # parse configuration
    return _parse_module_configuration(module_configuration)


def _parse_module_configuration(module_configuration):
    # if we have a module configuration, turn it into CLI arguments
    configuration_args = []
    # - volumes
    if 'volumes' in module_configuration:
        for volume in module_configuration['volumes']:
            configuration_args.append('--volume='+volume)
    # - devices
    if 'devices' in module_configuration:
        for device in module_configuration['devices']:
            configuration_args.append('--device='+device)
    # - ports
    if 'ports' in module_configuration:
        for port in module_configuration['ports']:
            configuration_args.append('-p='+port)
    # - restart policy
    if 'restart' in module_configuration:
        configuration_args.append('--restart=' + module_configuration['restart'])
    # - privileged
    if 'privileged' in module_configuration and module_configuration['privileged']:
        configuration_args.append('--privileged')
    # - network_mode
    if 'network_mode' in module_configuration:
        configuration_args.append('--network=' + module_configuration['network_mode'])
    # ---
    dtslogger.debug(
        'The module configuration is providing the configuration:\n\t' +
        '\n\t'.join(configuration_args) if len(configuration_args)
        else '(empty)'
    )
    # ---
    return configuration_args
