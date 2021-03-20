from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.duckietown_tokens import get_id_from_token


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        # make sure the token is set
        # noinspection PyBroadException
        try:
            token = shell.get_dt1_token()
        except Exception:
            dtslogger.error("You have not set a token for this shell.\n"
                            "You can get a token from the following URL,\n\n"
                            "\thttps://www.duckietown.org/site/your-token   \n\n"
                            "and set it using the following command,\n\n"
                            "\tdts tok set\n")
            return
        # show token info
        uid = get_id_from_token(token)
        shell.sprint("Correctly identified as uid = %s" % uid)
