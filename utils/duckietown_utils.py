import re


WIRED_ROBOT_TYPES = ["watchtower", "traffic_light", "duckietown"]


def get_robot_types():
    return [
        "duckiebot",
        "duckiedrone",
        "watchtower",
        "greenstation",
        "workstation",
        "traffic_light",
        "duckietown",
    ]


def get_robot_configurations(robot_type):
    configurations = {
        "duckiebot": ["DB18", "DB19", "DB20", "DB21M"],
        "duckiedrone": ["DD18"],
        "watchtower": ["WT18", "WT19A", "WT19B", "WT21A", "WT21B"],
        "greenstation": ["GS17"],
        "workstation": ["WS21A", "WS21B", "WS21C"],
        "traffic_light": ["TL18", "TL19"],
        "duckietown": ["DT20"],
    }
    if robot_type not in configurations:
        raise ValueError(f"Robot type {robot_type} not recognized!")
    return configurations[robot_type]


def get_distro_version(shell):
    return next(re.finditer("([a-zA-Z]+)", shell.get_commands_version())).group(1)


def get_robot_hardware(robot_configuration):
    configuration_to_hardware = {
        # Duckiebot
        "DB18": ("raspberry_pi", "3B+"),
        "DB19": ("raspberry_pi", "3B+"),
        "DB20": ("raspberry_pi", "4B2G"),
        "DB21M": ("jetson_nano_2gb", "2GB"),
        # Duckiedrone
        "DD18": ("raspberry_pi", "3B+"),
        # Watchtower
        "WT18": ("raspberry_pi", "4B2G"),
        "WT19A": ("raspberry_pi", "4B2G"),
        "WT19B": ("raspberry_pi", "4B2G"),
        "WT21A": ("raspberry_pi_64", "4B"),
        "WT21B": ("raspberry_pi_64", "4B"),
        # Green Station
        "GS17": ("raspberry_pi", "3B+"),
        # Traffic Light
        "TL18": ("raspberry_pi", "3B+"),
        "TL19": ("raspberry_pi", "3B+"),
        # Duckietown
        "DT20": ("raspberry_pi", "4B2G"),
        # Workstation
        "WS21A": ("raspberry_pi", "4B"),
        "WS21B": ("jetson_nano_2gb", "2GB"),
        "WS21C": ("jetson_nano_4gb", "4GB"),
    }
    # ---
    if robot_configuration not in configuration_to_hardware:
        raise ValueError(f"Robot configuration {robot_configuration} not recognized!")
    return configuration_to_hardware[robot_configuration]
