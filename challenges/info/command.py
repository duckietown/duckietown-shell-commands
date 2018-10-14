# import termcolor
import termcolor
from dt_shell import DTCommandAbs

from dt_shell.remote import get_dtserver_user_info, get_duckietown_server_url


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        token = shell.get_dt1_token()

        info = get_dtserver_user_info(token)

        # NOT_PROVIDED = termcolor.colored('missing', 'red')

        print('')
        print('You are succesfully authenticated:')
        print('')
        print('   name: %s' % info['name'])
        print('')
        print('  login: %s' % info['user_login'])
        print('')
        print('    uid: %s' % info['uid'])

        server = get_duckietown_server_url()

        url = server + '/humans/users/%s' % info['uid']
        msg = '''
You can find the list of your submissions at the page:

    {url}        
        
'''.format(url=href(url))

        print(msg)
        # print(' github: %s' % (info['github_username'] or NOT_PROVIDED))


def href(x):
    return termcolor.colored(x, 'blue', attrs=['underline'])
