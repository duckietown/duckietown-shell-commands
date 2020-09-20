import re


def get_robot_types():
    return ["duckiebot", "duckiedrone", "watchtower", "greenstation", "workstation", "traffic_light"]


def get_robot_configurations(robot_type):
    configurations = {
        "duckiebot": ["DB18", "DB19", "DB20", "DB-beta"],
        "duckiedrone": ["DD18"],
        "watchtower": ["WT18", "WT19A", "WT19B"],
        "greenstation": ["GS17"],
        "workstation": [None],
        "traffic_light": ["TL18", "TL19"],
    }
    if robot_type not in configurations:
        raise ValueError(f"Robot type {robot_type} not recognized!")
    return configurations[robot_type]


def get_distro_version(shell):
    return next(re.finditer("([a-zA-Z]+)", shell.get_commands_version())).group(1)


def get_robot_hardware(robot_configuration):
    configuration_to_hardware = {
        "DB18": ("raspberry_pi", "3B+"),
        "DB19": ("raspberry_pi", "3B+"),
        "DB20": ("raspberry_pi", "4B2G"),
        "DB-beta": ("jetson_nano", "1"),
        "DD18": ("raspberry_pi", "3B+"),
        "WT18": ("raspberry_pi", "4B2G"),
        "WT19A": ("raspberry_pi", "4B2G"),
        "WT19B": ("raspberry_pi", "4B2G"),
        "GS17": ("raspberry_pi", "3B+"),
        "TL18": ("raspberry_pi", "3B+"),
        "TL19": ("raspberry_pi", "3B+"),
    }
    # ---
    if robot_configuration not in configuration_to_hardware:
        raise ValueError(f"Robot configuration {robot_configuration} not recognized!")
    return configuration_to_hardware[robot_configuration]
