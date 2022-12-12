from dt_shell import DTCommandAbs, dtslogger


__all__ = ["DTCommand"]

from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        if shell.local_commands_info.leave_alone:
            dtslogger.warn("Will not update the commands because the path was set explicitly.")
        else:
            shell.check_commands_update()
