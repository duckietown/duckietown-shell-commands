from dt_shell import DTCommandAbs

class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, line):
        print "%s: v%s" % (shell.NAME, shell.VERSION)
