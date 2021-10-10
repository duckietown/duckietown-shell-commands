import argparse

from dt_shell import DTCommandAbs, DTShell, dtslogger


class DTCommand(DTCommandAbs):

    help = "Restarts a Virtual Robot"

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot virtual restart"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument("robot", nargs=1, help="Name of the Robot to restart")
        # parse arguments
        parsed = parser.parse_args(args)
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        # stop
        found = shell.include.duckiebot.virtual.stop.command(shell, [parsed.robot])
        if not found:
            return False
        # start
        dtslogger.info(f"Starting up virtual robot '{parsed.robot}'...")
        shell.include.duckiebot.virtual.start.command(shell, [parsed.robot])
        return True
