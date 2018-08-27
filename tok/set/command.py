from __future__ import print_function

from dt_shell import DTCommandAbs
from dt_shell.duckietown_tokens import get_id_from_token, InvalidToken

token_dt1_config_key = 'token_dt1'


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        msg = """
Please enter your Duckietown token.

It looks something like this:

    dt1-7vEuJsaxeXXXXX-43dzqWFnWd8KBa1yev1g3UKnzVxZkkTbfSJnxzuJjWaANeMf4y6XSXBWTpJ7vWXXXX
    
To find your token, first login to duckietown.org, and open the page:

    https://www.duckietown.org/site/your-token


Enter token: """
        if args:
            val_in = args[0]
        else:
            val_in = raw_input(msg)

        s = val_in.strip()
        try:
            uid = get_id_from_token(s)
            if uid == -1:
                msg = 'This is the sample token. Please use your own token.'
                raise ValueError(msg)
            print('Correctly identified as uid = %s' % uid)
        except InvalidToken as e:
            msg = 'The string %r does not look like a valid token:\n%s' % (s, e)
            print(msg)
            return

        shell.config[token_dt1_config_key] = s
        shell.save_config()
