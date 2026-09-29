import argparse

from dt_shell import DTCommandAbs, DTShell, dtslogger

from .common import stream_startup_logs


class DTCommand(DTCommandAbs):
    help = "Streams a DT robot's startup logs"

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot startup_logs"
        parser = argparse.ArgumentParser(prog=prog)
        parser.add_argument(
            "robot", nargs=1, help="Robot hostname or IPv4 address to inspect (short name, .local name, or FQDN)"
        )
        parsed = parser.parse_args(args)
        robot_name = parsed.robot[0]
        dtslogger.info(f"Streaming startup logs for '{robot_name}'...")
        try:
            stream_startup_logs(robot_name)
        except KeyboardInterrupt:
            dtslogger.info("Stopped streaming startup logs.")
        except Exception as error:
            dtslogger.error(str(error))
