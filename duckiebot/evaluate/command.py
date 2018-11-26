import argparse
import time

from dt_shell import DTCommandAbs, dtslogger

from utils.docker_utils import push_image_to_duckiebot, run_image_on_duckiebot, run_image_on_localhost

usage = """

## Basic usage

    Evaluates the current submission on the Duckiebot:

        $ dts duckiebot evaluate

"""


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        prog = 'dts duckiebot evaluate'
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        group = parser.add_argument_group('Basic')

        parser.add_argument('hostname', default=None,
                            help="Name of the Duckiebot on which to perform evaluation")

        group.add_argument('--image', help="Image to evaluate",
                           default="duckietown/dt-challenges-evaluator:v3")

        group.add_argument('--remotely', action='store_true', default=False,
                           help="Run the image on the laptop without pushing to Duckiebot")

        parsed = parser.parse_args(args)

        # TODO: start recording a bag
        # TODO: start slimremote client on duckiebot
        # TODO: start start slimremote listener/converter
        # TODO: copy calibration files into container appropriately

        if parsed.remotely:
            evaluate_remotely(parsed.hostname, parsed.image)
        else:
            evaluate_locally(parsed.hostname, parsed.image)


# Runs everything on the Duckiebot

def evaluate_locally(duckiebot_name, image_name):
    dtslogger.info("Running %s on %s" %(image_name, duckiebot_name))
    push_image_to_duckiebot(image_name, duckiebot_name)
    container = run_image_on_duckiebot(image_name, duckiebot_name)
    dtslogger.info("Letting %s run for 30s..." % image_name)
    time.sleep(30)
    container.stop()


# Sends actions over the local network

def evaluate_remotely(duckiebot_name, image_name):
    dtslogger.info("Running %s on localhost" % image_name)
    container = run_image_on_localhost(image_name, duckiebot_name)
    time.sleep(30)
    container.stop()
