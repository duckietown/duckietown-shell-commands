import glob
import os
import time
from datetime import datetime

import docker
from dt_shell import DTCommandAbs, DTShell

from utils.duckietown_utils import USER_DATA_DIR
from utils.misc_utils import human_time
from utils.table_utils import fill_cell, format_matrix

DISK_NAME = "root"
VIRTUAL_FLEET_DIR = os.path.join(USER_DATA_DIR, "virtual_robots")
UPTIME_NOT_AVAILABLE = "-"


def _format_uptime(container, now=None):
    attributes = getattr(container, "attrs", {})
    if not isinstance(attributes, dict):
        return UPTIME_NOT_AVAILABLE
    state = attributes.get("State", {})
    if not isinstance(state, dict):
        return UPTIME_NOT_AVAILABLE
    started_at = state.get("StartedAt")
    if not isinstance(started_at, str):
        return UPTIME_NOT_AVAILABLE
    try:
        normalized_started_at = started_at.replace("Z", "+00:00")
        started_datetime = datetime.fromisoformat(normalized_started_at)
        started_timestamp = started_datetime.timestamp()
    except (OSError, OverflowError, ValueError):
        return UPTIME_NOT_AVAILABLE
    current_time = time.time() if now is None else now
    uptime_seconds = max(0, current_time - started_timestamp)
    return human_time(uptime_seconds, compact=True)


class DTCommand(DTCommandAbs):

    help = "Lists all previously created Virtual Duckiebots"

    @staticmethod
    def command(shell: DTShell, args):
        # open connection to docker
        local_docker = docker.from_env()
        # find all robots on disk
        robots = glob.glob(os.path.join(VIRTUAL_FLEET_DIR, "*"))
        # make a table
        header = ["Type", "Model", "Status", "Uptime"]
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
            uptime = UPTIME_NOT_AVAILABLE
            try:
                containers_client = local_docker.containers
                container = containers_client.get(f"dts-virtual-{name}")
                container_status = container.status
                status = container_status.lower()
                if status == "running":
                    uptime = _format_uptime(container)
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
            data.append([name, robot_type, robot_configuration, status, uptime])
        # render table
        print(format_matrix(header, data, "{:^{}}", "{:<{}}", "{:>{}}", "\n", " | "))
