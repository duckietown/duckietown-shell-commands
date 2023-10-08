import os

from dt_shell import DTShell

DEFAULT_OWNER = "duckietown"
WIRED_ROBOT_TYPES = ["watchtower", "traffic_light", "duckietown"]
USER_DATA_DIR = os.path.expanduser(os.path.join("~", ".duckietown"))


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
        "duckiebot": ["DB18", "DB19", "DB20", "DB21M", "DB21J", "DBR4"],
        "duckiedrone": ["DD18", "DD21"],
        "watchtower": ["WT18", "WT19A", "WT19B", "WT21A", "WT21B"],
        "greenstation": ["GS17"],
        "workstation": ["WS21A", "WS21B", "WS21C"],
        "traffic_light": ["TL18", "TL19", "TL21"],
        "duckietown": ["DT20", "DT21"],
        "duckiecam": ["DC21"],
    }
    if robot_type not in configurations:
        raise ValueError(f"Robot type {robot_type} not recognized!")
    return configurations[robot_type]


def get_distro_version(shell: DTShell) -> str:
    return shell.profile.distro


def get_robot_hardware(robot_configuration):
    configuration_to_hardware = {
        # Duckiebot
        "DB18": ("raspberry_pi", "3B+"),
        "DB19": ("raspberry_pi", "3B+"),
        "DB20": ("raspberry_pi", "4B2G"),
        "DB21M": ("jetson_nano_2gb", "2GB"),
        "DB21J": ("jetson_nano_4gb", "4GB"),
        "DBR4": ("raspberry_pi_64", "4B"),
        # Duckiedrone
        "DD18": ("raspberry_pi", "3B"),
        "DD21": ("raspberry_pi_64", "3B+"),
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
        "TL21": ("raspberry_pi_64", "4B"),
        # Duckietown
        "DT20": ("raspberry_pi", "4B2G"),
        "DT21": ("raspberry_pi_64", "4B2G"),
        # Workstation
        "WS21A": ("raspberry_pi", "4B"),
        "WS21B": ("jetson_nano_2gb", "2GB"),
        "WS21C": ("jetson_nano_4gb", "4GB"),
    }
    # ---
    if robot_configuration not in configuration_to_hardware:
        raise ValueError(f"Robot configuration {robot_configuration} not recognized!")
    return configuration_to_hardware[robot_configuration]
