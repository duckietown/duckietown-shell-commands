import builtins
import json
import sys

from dt_authentication import DuckietownToken, InvalidToken
from dt_shell import DTCommandAbs, DTShell, dtslogger


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        try:
            if args:
                token_s = args[0]
            else:
                msg = "Please enter token:\n> "
                token_s = builtins.input(msg)

            dtslogger.debug("Verifying token %r\n" % token_s)

            try:
                token = DuckietownToken.from_string(token_s)
            except InvalidToken:
                msg = "Invalid token format."
                dtslogger.error(msg + "\n")
                sys.exit(3)

            dtslogger.info("Token parsed correctly!")
            payload = json.dumps(token.payload)
            print(f"\nToken content:\n{payload}")
            sys.exit(0)

        except Exception as e:
            dtslogger.error(str(e) + "\n")
            sys.exit(3)
