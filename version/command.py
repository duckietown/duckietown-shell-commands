from dt_shell import DTCommandAbs

class DTCommand(DTCommandAbs):

    help = 'Prints out the version of the shell and returns.'

    @staticmethod
    def command(shell, line):
        print "%s: v%s" % (shell.NAME, shell.VERSION)
