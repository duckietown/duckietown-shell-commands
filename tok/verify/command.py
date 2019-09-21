from dt_shell import DTCommandAbs, DTShell
from dt_shell.tokens_cli import verify_a_token_main


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):

        if args:
            args0 = args
        else:
            args0 = []  # will enter it

        verify_a_token_main(args0)
