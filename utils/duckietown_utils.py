import re

def get_robot_types():
    return ['duckiebot', 'duckiedrone', 'watchtower', 'greenstation', 'workstation', 'traffic_light']


def get_robot_configurations(robot_type):
    configurations = {
        'duckiebot': [
            'DB18', 'DB19', 'DB20'
        ],
        'duckiedrone': [
            'DD18'
        ],
        'watchtower': [
            'WT18', 'WT19A', 'WT19B'
        ],
        'greenstation': [
            'GS17'
        ],
        'workstation': [
            None
        ],
        'traffic_light': [
            'TL18', 'TL19'
        ]
    }
    if robot_type not in configurations:
        raise ValueError(f'Robot type {robot_type} not recognized!')
    return configurations[robot_type]


def get_major_version(shell):
    return next(re.finditer('([a-zA-Z]+)', shell.get_commands_version())).group(1)
