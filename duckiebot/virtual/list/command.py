import argparse
import glob
import os

import docker
from dt_shell import DTCommandAbs, DTShell

from utils.duckietown_utils import \
    USER_DATA_DIR
from utils.table_utils import format_matrix, fill_cell

DISK_NAME = "root"
VIRTUAL_FLEET_DIR = os.path.join(USER_DATA_DIR, "virtual_robots")


class DTCommand(DTCommandAbs):

    help = "Lists all previously created Virtual Duckiebots"

    @staticmethod
    def command(shell: DTShell, args):
        # open connection to docker
        local_docker = docker.from_env()
        # find all robots on disk
        robots = glob.glob(os.path.join(VIRTUAL_FLEET_DIR, "*"))
        # make a table
        header = ["Type", "Model", "Status"]
        data = []
        for robot_dir in sorted(robots):
            robot_config_dir = os.path.join(robot_dir, DISK_NAME, "data", "config")
            name = os.path.basename(robot_dir)
            # read robot type
            robot_type_fpath = os.path.join(robot_config_dir, "robot_type")
            with open(robot_type_fpath, "rt") as fin:
                robot_type = fin.read().strip()
            # read robot configuration
            robot_configuration_fpath = os.path.join(robot_config_dir, "robot_configuration")
            with open(robot_configuration_fpath, "rt") as fin:
                robot_configuration = fin.read().strip()
            # check whether the robot is up
            try:
                container = local_docker.containers.get(f"dts-virtual-{name}")
                status = container.status.lower()
            except docker.errors.NotFound:
                status = "down"
            # color status
            color = "grey"
            if status == "running":
                color = "green"
            elif status == "paused":
                color = "blue"
            status = fill_cell(status.title(), 12, "white", color)
            # add to table
            data.append([name, robot_type, robot_configuration, status])
        # render table
        print(format_matrix(header, data, "{:^{}}", "{:<{}}", "{:>{}}", "\n", " | "))
