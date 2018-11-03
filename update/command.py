from dt_shell import DTCommandAbs, dtslogger

from update import duckietown_shell_commands_version


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        if shell.commands_path_leave_alone:
            dtslogger.warn('Will not update the commands because the path was set explicitly.')
        else:
            if shell.update_commands():
                dtslogger.info('Duckietown Shell commands updated to v{}'.format(duckietown_shell_commands_version))
            else:
                dtslogger.error('Update was not successful!')
