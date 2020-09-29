from dt_shell import DTCommandAbs, dtslogger

# from update import duckietown_shell_commands_version

__all__ = ["DTCommand"]

from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        if shell.local_commands_info.leave_alone:
            dtslogger.warn("Will not update the commands because the path was set explicitly.")
        else:
            if shell.update_commands():
                dtslogger.info("Duckietown Shell commands updated.")
            else:
                dtslogger.error("Update was not successful.")
