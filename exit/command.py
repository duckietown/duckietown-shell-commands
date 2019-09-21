from dt_shell import DTCommandAbs, DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        print("Bye bye!")
        exit()
