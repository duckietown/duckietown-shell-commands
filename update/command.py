from dt_shell import DTCommandAbs

class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        shell.update_commands()
