
import termcolor
from dt_shell import DTCommandAbs
from duckietown_challenges import get_duckietown_server_url


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        from duckietown_challenges.rest_methods import get_dtserver_user_info


        token = shell.get_dt1_token()

        info = get_dtserver_user_info(token)

        NOT_PROVIDED = termcolor.colored('missing', 'red')

        if 'profile' in info:
            profile = href(info.get('profile'))
        else:
            profile = NOT_PROVIDED

        user_login = info.get('user_login', NOT_PROVIDED)
        display_name = info.get('name', NOT_PROVIDED)
        uid = info.get('uid', NOT_PROVIDED)

        s = '''
        
You are succesfully authenticated:

         ID: {uid}
       name: {display_name}    
      login: {user_login}
    profile: {profile}
        
'''.format(uid=bold(uid),
           user_login=bold(user_login),
           display_name=bold(display_name), profile=profile).strip()

        server = get_duckietown_server_url()

        url = server + '/humans/users/%s' % info['uid']

        s += '''

You can find the list of your submissions at the page:

    {url}        

        '''.format(url=href(url))

        if hasattr(shell, 'sprint'):
            shell.sprint(s)
        else:
            print(s)

        # print(' github: %s' % (info['github_username'] or NOT_PROVIDED))


def href(x):
    return termcolor.colored(x, 'blue', attrs=['underline'])


def bold(x):
    return termcolor.colored(x, attrs=['bold'])
