import argparse
import asyncio
import json
import logging
import os
import signal
import time
from collections import defaultdict
from threading import Thread
from typing import List, Set, Tuple

from dt_shell import DTCommandAbs, dtslogger
from utils.duckietown_utils import get_robot_types
from utils.table_utils import fill_cell, format_matrix
from utils.udp_responder_utils import UDPScanner, PongPacket

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
        "DT::BOOTING",
        "DT::ROBOT_TYPE",
        "DT::ROBOT_CONFIGURATION",
        "DT::ROBOT_HARDWARE",
    ]

    def __init__(self, args, notes: List[str] = None):
        self.args = args
        self._notes: List[str] = notes or []
        self._external: List[dict] = []

    @staticmethod
    def process_service_name(name):
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

    def add_external(self, name: str, hardware: str, rtype: str, model: str, status: str, hostname: str):
        self._external.append(
            {"name": name, "hardware": hardware, "type": rtype, "model": model, "status": status, "hostname": hostname}
        )

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
        txt_str: str = list(info.properties.keys())[0].decode("utf-8") if len(info.properties) else "{}"
        txt: dict = {}
        if len(txt_str.strip()):
            try:
                txt: dict = json.loads(txt_str)
            except json.JSONDecodeError:
                dtslogger.error(f"An error occurred while decoding the TXT string '{txt_str}'. "
                                f"A JSON string was expected.")
        self.services[name][server] = {"port": info.port, "txt": txt}

    def update_service(self, *args, **kwargs):
        pass

    def print(self):
        # get all discovered hostnames
        devices: Set[str] = set()

        # add externally discovered hostnames
        devices.update([x["name"] for x in self._external])

        for service in self.supported_services:
            hostnames_for_service: List[str] = list(self.services[service])
            devices.update(hostnames_for_service)

        # create device -> robot_type map
        device_to_type = defaultdict(lambda: "ND")
        # - from external (UDP responder scan)
        for x in self._external:
            device_to_type[x["name"]] = x["type"]
        # - from mDNS
        for device in self.services["DT::ROBOT_TYPE"]:
            dev = self.services["DT::ROBOT_TYPE"][device]
            if len(dev["txt"]) and "type" in dev["txt"]:
                try:
                    device_to_type[device] = dev["txt"]["type"]
                except:  # XXX: complain a bit
                    pass

        # create device -> robot_configuration map
        device_to_config = defaultdict(lambda: "ND")
        # - from external (UDP responder scan)
        for x in self._external:
            device_to_config[x["name"]] = x["model"]
        # - from mDNS
        for device in self.services["DT::ROBOT_CONFIGURATION"]:
            dev = self.services["DT::ROBOT_CONFIGURATION"][device]
            if len(dev["txt"]) and "configuration" in dev["txt"]:
                try:
                    device_to_config[device] = dev["txt"]["configuration"]
                except:
                    pass

        # create device -> robot_hardware map
        device_to_hardware = defaultdict(lambda: "physical")
        # - from external (UDP responder scan)
        for x in self._external:
            device_to_hardware[x["name"]] = x["hardware"]
        # - from mDNS
        for device in self.services["DT::ROBOT_HARDWARE"]:
            dev = self.services["DT::ROBOT_HARDWARE"][device]
            if len(dev["txt"]) and "hardware" in dev["txt"]:
                try:
                    device_to_hardware[device] = dev["txt"]["hardware"]
                except:
                    pass

        # create device -> hostname map
        device_to_hostname = defaultdict(lambda: "ND")
        # - from external (UDP responder scan)
        for x in self._external:
            device_to_hostname[x["name"]] = x["hostname"]
        # - from mDNS
        for device in devices:
            # only overwrite an IP address if we have talked to this device via mDNS
            if device in self.services["DT::ROBOT_TYPE"]:
                device_to_hostname[device] = f"{device}.local"

        # prepare table
        columns = [
            "Status",  # Booting [yellow], Ready [green]
            # TODO: Internet check is kind of unstable at this time, disabling it
            # "Internet",  # No [grey], Yes [green]
            # TODO: People get confused when this is down but the dashboard is up, disabling
            # "Dashboard",  # Down [grey], Up [green]
            # TODO: Busy is not used at this time, disabling it
            # "Busy",  # No [grey], Yes [green]
        ]
        columns = list(map(lambda c: " %s " % c, columns))
        header = ["Hardware", "Type", "Model"] + columns + ["Hostname"]
        data = []

        for device in list(sorted(devices)):
            # filter by robot type
            robot_type = device_to_type[device]
            robot_configuration = device_to_config[device]
            robot_hardware = device_to_hardware[device]
            robot_hostname = device_to_hostname[device]
            if self.args.filter_type and robot_type != self.args.filter_type:
                continue
            # prepare status list
            statuses = []
            for column in columns:
                text, color, bg_color = column_to_text_and_color(column, device, self.services)
                column_txt = fill_cell(text, len(column), color, bg_color)
                statuses.append(column_txt)
            # prepare row
            row = (
                [device, robot_hardware, robot_type, robot_configuration]
                + statuses
                + [robot_hostname]
            )
            data.append(row)

        # clear terminal
        os.system("cls" if os.name == "nt" else "clear")

        # print table
        if self._notes:
            print("NOTES: " + "\n       ".join(self._notes) + "\n")
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
        parser.add_argument(
            "--brute",
            default=False,
            action="store_true",
            help="Discover devices on all network interfaces (gateway only by default)",
        )
        parser.add_argument(
            "--no-mdns",
            default=False,
            action="store_true",
            help="Do not use mDNS to discover devices",
        )

        parsed = parser.parse_args(args)

        # notes
        notes = []

        if parsed.no_mdns:
            notes.append("mDNS discovery is disabled. Device discovery will be slower.")

        # perform discover
        zeroconf = Zeroconf()
        listener = DiscoverListener(args=parsed, notes=notes)

        if not parsed.no_mdns:
            # FIXME: @afdaniele - wrong type - listener supposed to be ServiceListener
            #        should DiscoverListener be a subclass of ServiceListener
            ServiceBrowser(zeroconf, "_duckietown._tcp.local.", listener)

        def add_external(addr: Tuple[str, int], pong: PongPacket):
            listener.add_external(pong.name, pong.hardware, pong.type, pong.configuration, "ND", addr[0])

        scanner = UDPScanner(parsed.brute)
        t = Thread(target=asyncio.run, args=(scanner.scan(callback=add_external),))
        t.start()

        shutdown: bool = False

        def signal_handler(_, __):
            nonlocal shutdown
            shutdown = True
            scanner.stop()

        signal.signal(signal.SIGINT, signal_handler)

        while not shutdown:
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
        if hostname in services["DT::BOOTING"]:
            text, color, bg_color = "Booting", "white", "yellow"
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
