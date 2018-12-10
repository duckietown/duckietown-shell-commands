from __future__ import print_function

import argparse
import time

from dt_shell import DTCommandAbs, dtslogger

from utils.docker_utils import start_rqt_image_view, start_picamera


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        prog = 'dts duckiebot camera DUCKIEBOT_NAME'
        usage = """
Stream camera images: 

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('hostname', default=None, help='Name of the Duckiebot')
        parsed_args = parser.parse_args(args)

        start_picamera(duckiebot_name=parsed_args.hostname)
        dtslogger.info("Waiting a few seconds for Duckiebot camera container to warm up...")
        time.sleep(3)
        start_rqt_image_view(duckiebot_name=parsed_args.hostname)
