import os
import sys
import json
import time
import argparse
import math
from termcolor import colored
from collections import defaultdict
from dt_shell import DTCommandAbs, dtslogger

REFRESH_HZ = 1.0

usage = """

## Basic usage

    Discovers Duckietown robots in the local network.

    To find out more, use `dts duckiebot discover -h`.

        $ dts duckiebot discover [options]

"""

class DiscoverListener:

    services = defaultdict(dict)
    supported_services = [
        'DT::ONLINE',
        'DT::PRESENCE'
    ]
    status_order = ['On', 'Online', 'Busy']
    status_to_service = {
        'On' : 'DT::PRESENCE',
        'Online' : 'DT::ONLINE',
        'Busy' : 'DT::BUSY'
    }

    def __init__(self, args):
        self.args = args

    def process_service_name(self, name):
        name = name.replace('._duckietown._tcp.local.', '')
        service_parts = name.split('::')
        if len(service_parts) != 3 or service_parts[0] != 'DT':
            return None, None
        name = '{}::{}'.format(service_parts[0], service_parts[1])
        server = service_parts[2]
        return name, server

    def remove_service(self, zeroconf, type, name):
        name, server = self.process_service_name(name)
        if not name:
            return
        del self.services[name][server]

    def add_service(self, zeroconf, type, sname):
        name, server = self.process_service_name(sname)
        if not name:
            return
        info = zeroconf.get_service_info(type, sname)
        txt = json.loads(list(info.properties.keys())[0].decode('utf-8')) \
            if len(info.properties) \
            else dict()
        self.services[name][server] = {
            'port': info.port,
            'txt': txt
        }

    def print(self):
        # clear terminal
        os.system('cls' if os.name == 'nt' else 'clear')
        # get all discovered hostnames
        hostnames = set()
        for service in self.supported_services:
            hostnames.update(self.services[service])
        # create hostname -> robot_type map
        hostname_to_type = defaultdict(lambda:'ND')
        for device_hostname in self.services['DT::ROBOT_TYPE']:
            dev = self.services['DT::ROBOT_TYPE'][device_hostname]
            if len(dev['txt']) and 'type' in dev['txt']:
                try:
                    hostname_to_type[device_hostname] = dev['txt']['type']
                except:
                    pass
        # prepare table
        header = ['Type'] + ['Status: '+s for s in self.status_order] + ['Hostname']
        data = []
        data_plain = []

        for device_hostname in hostnames:
            # filter by robot type
            robot_type = hostname_to_type[device_hostname]
            if self.args.filter_type and robot_type != self.args.filter_type:
                continue
            # prepare status list
            statuses = []
            statuses_plain = []
            for status in self.status_order:
                service_name = self.status_to_service[status]
                status_header_l = len('Status: ')+len(status)
                service = self.status_to_service[status]
                status_plain_txt = 'No'
                status_txt = fill_cell(status_plain_txt, status_header_l, 'white', 'grey')
                if device_hostname in self.services[service_name]:
                    status_plain_txt = 'Yes'
                    status_txt = fill_cell(status_plain_txt, status_header_l, 'white', 'green')
                statuses.append(status_txt)
                statuses_plain.append(status_plain_txt)

            row = [device_hostname, robot_type] + statuses + [device_hostname+'.local']
            row_plain = [device_hostname, robot_type] + statuses_plain + [device_hostname+'.local']
            data.append(row)
            data_plain.append(row_plain)

        # print table
        print("NOTE: Only devices flashed using duckietown-shell-commands v4.1.0+ are supported.\n")
        print(format_matrix(
            header,
            data,
            '{:^{}}', '{:<{}}', '{:>{}}', '\n', ' | ',
            matrix_plain=data_plain
        ))



class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        prog = 'dts duckiebot discover'

        # try to import zeroconf
        try:
            from zeroconf import ServiceBrowser, Zeroconf
        except ImportError:
            dtslogger.error("{} requires zeroconf. Use pip to install it.")
            return

        # parse arguments
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument('--type', dest="filter_type", default=None,
                            choices=['duckiebot', 'watchtower'],
                            help="Filter devices by type")

        parsed = parser.parse_args(args)

        # perform discover
        zeroconf = Zeroconf()
        listener = DiscoverListener(args=parsed)
        browser = ServiceBrowser(zeroconf, "_duckietown._tcp.local.", listener)

        while True:
            listener.print()
            time.sleep(1.0 / REFRESH_HZ)



def format_matrix(header, matrix, top_format, left_format, cell_format, row_delim, col_delim, matrix_plain=None):
    table = [[''] + header] + matrix
    print_table = table
    if matrix_plain is not None:
        table = [[''] + header] + matrix_plain
    table_format = [['{:^{}}'] + len(header) * [top_format]] \
                 + (len(matrix)+1) * [[left_format] + len(header) * [cell_format]]
    col_widths = [max(len(format.format(cell, 0)) for format, cell in zip(col_format, col))
                  for col_format, col in zip(zip(*table_format), zip(*table))]
    # add header separator
    print_table = [print_table[0], ['-'*l for l in col_widths]] + print_table[1:]
    # print table
    return row_delim.join(
               col_delim.join(
                   format.format(cell, width)
                   for format, cell, width in zip(row_format, row, col_widths))
               for row_format, row in zip(table_format, print_table))


def fill_cell(text, width, foreground, background):
    s1 = math.floor((float(width)-len(text)) / 2.0)
    s2 = math.ceil((float(width)-len(text)) / 2.0)
    s = ' '*s1 + text + ' '*s2
    return colored(s, foreground, 'on_'+background)
