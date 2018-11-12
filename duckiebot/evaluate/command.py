import argparse

from dt_shell import DTCommandAbs

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

        group.add_argument('--no-cache', action='store_true', default=False,
                           help="")

        group.add_argument('--no-build', action='store_true', default=False,
                           help="")
        group.add_argument('--no-pull', action='store_true', default=False,
                           help="")
        group.add_argument('--image', help="Evaluator image to run",
                           default='duckietown/dt-challenges-evaluator:v3')
        group.add_argument('--shell', action='store_true', default=False,
                           help="Runs a shell in the container")
        group.add_argument('--output', help="", default='output')

        group.add_argument('-C', dest='change', default=None)

        parsed = parser.parse_args(args)

#Starts a local GUI tools container
