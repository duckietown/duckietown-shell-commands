import argparse
import json
from typing import List

from dt_shell import DTCommandAbs, UserError, DTShell
from duckietown_challenges.rest import ServerIsDown


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args):
        from duckietown_challenges.rest_methods import dtserver_auth
        token = shell.get_dt1_token()

        parser = argparse.ArgumentParser()
        parser.add_argument('--cmd', required=True)
        parser.add_argument('--impersonate', default=None)

        parsed = parser.parse_args(args)

        cmd = parsed.cmd

        try:
            res = dtserver_auth(token=token, cmd=cmd, impersonate=parsed.impersonate)
        except ServerIsDown:
            msg = 'Server is down - please wait.'
            raise UserError(msg)

        results: List[dict] = res['results']
        shell.sprint(json.dumps(results, indent=2))
        for result in results:
            ok = result['ok']
            msg = result.get('msg')
            line = result.get('line')
            if msg is None:
                msg = ''
            qr = result.get('query_result')

            shell.sprint('query: %s' % line)
            s = 'OK' if ok else "ERR"
            shell.sprint('processed: %s' % s)
            shell.sprint('   result: %s' % qr)
            shell.sprint('message: %s' % msg)
