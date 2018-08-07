from __future__ import print_function

from dt_shell import DTCommandAbs
from dt_shell.tokens_cli import verify_a_token_main


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):

        if args:
            args0 = args
        else:
            args0 = []  # will enter it

        verify_a_token_main(args0)
