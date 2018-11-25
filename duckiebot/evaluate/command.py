import argparse

from dt_shell import DTCommandAbs

from utils.docker_utils import push_image_to_duckiebot

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

        if (parsed.remotely):
            evaluate_remotely(parsed.hostname, parsed.image)
        else:
            evaluate_locally(parsed.hostname, parsed.image)


# Runs everything on the Duckiebot

def evaluate_locally(hostname, image_name):
    push_image_to_duckiebot('duckietown/%s' % image_name, hostname)
    # TODO: finish


# Sends actions over the local network

def evaluate_remotely(hostname, image_name):
    pass  # TODO: finish
