from dt_shell import DTCommandAbs, dtslogger, DTShell

from .raspberry_pi.private_command import DTCommand as RaspberryPiCommand
from .jetson_nano.private_command import DTCommand as JetsonNanoCommand

DEFAULT_DEVICE = "raspberry_pi"

DEVICE_TO_COMMAND = {"raspberry_pi": RaspberryPiCommand, "jetson_nano": JetsonNanoCommand}


class DTCommand(DTCommandAbs):

    help = "Create disk image for a Duckietown device"

    @staticmethod
    def command(shell: DTShell, args):
        device = DEFAULT_DEVICE
        if len(args) > 0 and not args[0].startswith("-"):
            device = args[0]
            args = args[1:]
        # check device
        if device not in DEVICE_TO_COMMAND:
            dtslogger.error(
                "Unknown device '{}'. Valid choices are {}.".format(device, list(DEVICE_TO_COMMAND.keys()))
            )
            exit(1)
        # run command
        DEVICE_TO_COMMAND[device].command(shell, args)

    @staticmethod
    def complete(shell, word, line):
        return DEVICE_TO_COMMAND.keys()
