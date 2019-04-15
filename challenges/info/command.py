import argparse

import termcolor
from dt_shell import DTCommandAbs, UserError
from duckietown_challenges import get_duckietown_server_url
from duckietown_challenges.rest import ServerIsDown
from duckietown_challenges.rest_methods import get_registry_info


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        from duckietown_challenges.rest_methods import get_dtserver_user_info


        parser = argparse.ArgumentParser()
        parser.add_argument('--impersonate', type=str, default=None)

        parsed = parser.parse_args(args)

        token = shell.get_dt1_token()

        try:
            info = get_dtserver_user_info(token, impersonate=parsed.impersonate)

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

            shell.sprint(s)
            #
            # ri = get_registry_info(token)
            # shell.sprint('Registry: %s' % ri.registry)

            # print(' github: %s' % (info['github_username'] or NOT_PROVIDED))
        except ServerIsDown as e:
            msg = 'The server is temporarily down. Please try again later.'
            msg +='\n\n' + str(e)
            raise UserError(msg)

def href(x):
    return termcolor.colored(x, 'blue', attrs=['underline'])


def bold(x):
    return termcolor.colored(x, attrs=['bold'])
