from dt_shell import DTCommandAbs, __version__


class DTCommand(DTCommandAbs):
    help = 'Prints out the version of the shell and returns.'

    @staticmethod
    def command(shell, args):
        print("dts version %s" % __version__)
