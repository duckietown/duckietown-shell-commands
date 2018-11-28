import argparse
import time

from dt_shell import DTCommandAbs, dtslogger

from utils.docker_utils import push_image_to_duckiebot, run_image_on_duckiebot, run_image_on_localhost, record_bag, \
    start_slimremote_duckiebot_container, start_rqt_image_view

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

        # TODO: copy calibration files into container appropriately

        slimremote_conatiner = start_slimremote_duckiebot_container(parsed.hostname)
        start_rqt_image_view(parsed.hostname)

        bag_container = record_bag(parsed.hostname)

        if parsed.remotely:
            evaluate_remotely(parsed.hostname, parsed.image)
        else:
            evaluate_locally(parsed.hostname, parsed.image)

        bag_container.stop()
        slimremote_conatiner.stop()


# Runs everything on the Duckiebot

def evaluate_locally(duckiebot_name, image_name):
    dtslogger.info("Running %s on %s" % (image_name, duckiebot_name))
    push_image_to_duckiebot(image_name, duckiebot_name)
    evaluation_container = run_image_on_duckiebot(image_name, duckiebot_name)
    dtslogger.info("Letting %s run for 30s..." % image_name)
    time.sleep(30)
    evaluation_container.stop()


# Sends actions over the local network

def evaluate_remotely(duckiebot_name, image_name):
    dtslogger.info("Running %s on localhost" % image_name)
    evaluation_container = run_image_on_localhost(image_name, duckiebot_name)
    dtslogger.info("Letting %s run for 30s..." % image_name)
    time.sleep(30)
    evaluation_container.stop()
