from dt_authentication import DuckietownToken
from dt_shell import DTCommandAbs, DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        token: str = shell.profile.secrets.dt_token
        # show token info
        uid = DuckietownToken.from_string(token).uid
        shell.sprint("Correctly identified as uid = %s" % uid)
