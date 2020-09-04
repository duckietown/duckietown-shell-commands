import argparse

from dt_shell import DTCommandAbs

usage = """

    ## Basic usage

        Downloads the logs from a host.

            $ dts logs download HOSTNAME

    """

from dt_shell import DTShell


class DTCommand(DTCommandAbs):

    prog = "dts duckiebot evaluate"
    parser = argparse.ArgumentParser(prog=prog, usage=usage)

    parser.add_argument(
        "hostname",
        default=None,
        help="Name of the host where logs should be fetched",
    )

    @staticmethod
    def command(shell: DTShell, args):
        parsed = DTCommand.parser.parse_args(args)
