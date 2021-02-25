import argparse

from dt_shell import DTCommandAbs, DTShell

DEFAULT_STACK = "duckietown"


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot update"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument(
            "robot",
            nargs=1,
            help="Name of the Robot to update"
        )
        # parse arguments
        parsed = parser.parse_args(args)
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        # call `stack up` command
        shell.include.stack.up.command(shell, [
            "--machine", parsed.robot,
            "--detach",
            "--pull",
            DEFAULT_STACK
        ])
