import termcolor
from dt_shell import DTCommandAbs
from dt_shell.constants import DTShellConstants

from dt_shell.remote import get_dtserver_user_info


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        token = shell.get_dt1_token()

        info = get_dtserver_user_info(token)

        NOT_PROVIDED = termcolor.colored('missing', 'red')

        print('You are succesfully authenticated.\n')
        print('   name: %s' % info['name'])
        print('  login: %s' % info['user_login'])
        # print(' github: %s' % (info['github_username'] or NOT_PROVIDED))
