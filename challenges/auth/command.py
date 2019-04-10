import argparse

from dt_shell import DTCommandAbs
from duckietown_challenges.rest_methods import dtserver_auth


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        token = shell.get_dt1_token()

        parser = argparse.ArgumentParser()
        parser.add_argument('--cmd', required=True)
        #
        # parser.add_argument('--no-cache', default=False, action='store_true')
        # parser.add_argument('--steps', default=None, help='Which steps (comma separated)')
        # parser.add_argument('--force-invalidate-subs', default=False, action='store_true')
        # parser.add_argument('-C', dest='cwd', default=None, help='Base directory')

        parsed = parser.parse_args(args)

        cmd = parsed.cmd

        res = dtserver_auth(token=token, cmd=cmd)

        print()
        print()
        print()

        results = res['results']
        for result in results:
            ok = result['ok']
            msg = result.get('msg')
            line = result.get('line')
            if msg is None:
                msg = ''
            qr = result.get('query-result', None)

            print('query: %s' % line)
            s = 'OK' if ok else "ERR"
            print('processed: %s' % s)
            if qr is not None:
                print('   result: %s' % qr)
            print('message: %s' % msg)
            #
            # if not ok:
            #     l = termcolor.colored(l, 'red')
            # else:
            #     l = termcolor.colored(l, 'green')

            # print(l)
