from dt_shell import DTCommandAbs


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        if shell.commands_path_leave_alone:
            msg = 'Will not update the commands because the path was set explicitly.'
            shell.sprint(msg)
        else:
            shell.update_commands()
