from dt_shell import __version__, DTCommandAbs, DTShell


class DTCommand(DTCommandAbs):
    help = "Prints out the version of the shell and returns."

    @staticmethod
    def command(shell: DTShell, args):
        print("dts version %s" % __version__)
