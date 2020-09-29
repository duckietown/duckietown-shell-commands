import os
import json
import time
import argparse
import logging
from collections import defaultdict
from dt_shell import DTCommandAbs, dtslogger

from utils.table_utils import format_matrix, fill_cell
from utils.duckietown_utils import get_robot_types

REFRESH_HZ = 1.0

usage = """

## Basic usage

    Discovers Duckietown robots in the local network.

    To find out more, use `dts fleet discover -h`.

        $ dts fleet discover [options]

"""


class DiscoverListener:

    services = defaultdict(dict)
    supported_services = [
        "DT::ONLINE",
        "DT::PRESENCE",
        "DT::ROBOT_TYPE",
        "DT::ROBOT_CONFIGURATION",
        "DT::DASHBOARD",
    ]

    def __init__(self, args):
        self.args = args

    def process_service_name(self, name):
        name = name.replace("._duckietown._tcp.local.", "")
        service_parts = name.split("::")
        if len(service_parts) != 3 or service_parts[0] != "DT":
            return None, None
        name = "{}::{}".format(service_parts[0], service_parts[1])
        server = service_parts[2]
        return name, server

    def remove_service(self, zeroconf, type, name):
        dtslogger.debug("SERVICE_REM: %s (%s)" % (str(name), str(type)))
        name, server = self.process_service_name(name)
        if not name:
            return
        del self.services[name][server]

    def add_service(self, zeroconf, type, sname):
        dtslogger.debug("SERVICE_ADD: %s (%s)" % (str(sname), str(type)))
        name, server = self.process_service_name(sname)
        if not name:
            return
        dtslogger.debug("SERVICE_ADD: %s (%s)" % (str(name), str(server)))
        info = zeroconf.get_service_info(type, sname)
        if info is None:
            return
        dtslogger.debug("SERVICE_ADD: %s" % (str(info)))
        txt = json.loads(list(info.properties.keys())[0].decode("utf-8")) if len(info.properties) else dict()
        self.services[name][server] = {"port": info.port, "txt": txt}

    def update_service(self, *args, **kwargs):
        pass

    def print(self):
        # clear terminal
        os.system("cls" if os.name == "nt" else "clear")
        # get all discovered hostnames
        hostnames = set()
        for service in self.supported_services:
            hostnames.update(self.services[service])
        # create hostname -> robot_type map
        hostname_to_type = defaultdict(lambda: "ND")
        for device_hostname in self.services["DT::ROBOT_TYPE"]:
            dev = self.services["DT::ROBOT_TYPE"][device_hostname]
            if len(dev["txt"]) and "type" in dev["txt"]:
                try:
                    hostname_to_type[device_hostname] = dev["txt"]["type"]
                except:
                    pass
        # create hostname -> robot_configuration map
        hostname_to_config = defaultdict(lambda: "ND")
        for device_hostname in self.services["DT::ROBOT_CONFIGURATION"]:
            dev = self.services["DT::ROBOT_CONFIGURATION"][device_hostname]
            if len(dev["txt"]) and "configuration" in dev["txt"]:
                try:
                    hostname_to_config[device_hostname] = dev["txt"]["configuration"]
                except:
                    pass
        # prepare table
        columns = [
            "Status",  # Loading [yellow], Ready [green]
            "Internet",  # No [grey], Yes [green]
            "Dashboard",  # Down [grey], Up [green]
            "Busy",  # No [grey], Yes [green]
        ]
        columns = list(map(lambda c: " %s " % c, columns))
        header = ["Type", "Model"] + columns + ["Hostname"]
        data = []

        for device_hostname in list(sorted(hostnames)):
            # filter by robot type
            robot_type = hostname_to_type[device_hostname]
            robot_configuration = hostname_to_config[device_hostname]
            if self.args.filter_type and robot_type != self.args.filter_type:
                continue
            # prepare status list
            statuses = []
            for column in columns:
                text, color, bg_color = column_to_text_and_color(column, device_hostname, self.services)
                column_txt = fill_cell(text, len(column), color, bg_color)
                statuses.append(column_txt)
            # prepare row
            row = (
                [device_hostname, robot_type, robot_configuration]
                + statuses
                + [str(device_hostname) + ".local"]
            )
            data.append(row)

        # print table
        print("NOTE: Only devices flashed using duckietown-shell-commands v4.1.0+ are supported.\n")
        print(format_matrix(header, data, "{:^{}}", "{:<{}}", "{:>{}}", "\n", " | "))


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell, args):
        prog = "dts fleet discover"

        # try to import zeroconf
        try:
            from zeroconf import ServiceBrowser, Zeroconf
        except ImportError:
            dtslogger.error("{} requires zeroconf. Use pip to install it.")
            return

        # parse arguments
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument(
            "--type",
            dest="filter_type",
            default=None,
            choices=get_robot_types(),
            help="Filter devices by type",
        )

        parsed = parser.parse_args(args)

        # perform discover
        zeroconf = Zeroconf()
        listener = DiscoverListener(args=parsed)
        ServiceBrowser(zeroconf, "_duckietown._tcp.local.", listener)

        while True:
            if dtslogger.level > logging.DEBUG:
                listener.print()
            time.sleep(1.0 / REFRESH_HZ)


def column_to_text_and_color(column, hostname, services):
    column = column.strip()
    text, color, bg_color = "ND", "white", "grey"
    #  -> Status
    if column == "Status":
        if hostname in services["DT::PRESENCE"]:
            text, color, bg_color = "Ready", "white", "green"
        if hostname in services["DT::DEVICE-INIT"]:
            text, color, bg_color = "Loading", "white", "yellow"
    #  -> Dashboard
    if column == "Dashboard":
        text, color, bg_color = "Down", "white", "grey"
        if hostname in services["DT::DASHBOARD"]:
            text, color, bg_color = "Up", "white", "green"
    #  -> Internet
    if column == "Internet":
        text, color, bg_color = "No", "white", "grey"
        if hostname in services["DT::ONLINE"]:
            text, color, bg_color = "Yes", "white", "green"
    #  -> Busy
    if column == "Busy":
        text, color, bg_color = "No", "white", "grey"
        if hostname in services["DT::BUSY"]:
            text, color, bg_color = "Yes", "white", "green"
    # ----------
    return text, color, bg_color
