import termcolor
from dt_shell import DTCommandAbs
from dt_shell.constants import DTShellConstants

from dt_shell.remote import get_dtserver_user_info


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        k = DTShellConstants.DT1_TOKEN_CONFIG_KEY
        if k not in shell.config:
            msg = 'Please set up a token for this.'
            raise Exception(msg)

        token = shell.config[k]

        info = get_dtserver_user_info(token)

        NOT_PROVIDED = termcolor.colored('missing', 'red')

        print('You are succesfully authenticated.\n')
        print('   name: %s' % info['name'])
        print('  login: %s' % info['user_login'])
        print(' github: %s' % (info['github_username'] or NOT_PROVIDED))
