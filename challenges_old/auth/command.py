import argparse
import json
from typing import List

from dt_shell import DTCommandAbs, DTShell

from challenges.challenges_cmd_utils import check_duckietown_challenges_version, wrap_server_operations


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):

        check_duckietown_challenges_version()

        from duckietown_challenges.rest_methods import dtserver_auth

        token = shell.get_dt1_token()

        parser = argparse.ArgumentParser()
        parser.add_argument("--cmd", required=True)
        parser.add_argument("--impersonate", default=None)

        parsed = parser.parse_args(args)

        cmd = parsed.cmd

        with wrap_server_operations():
            res = dtserver_auth(token=token, cmd=cmd, impersonate=parsed.impersonate)

        results: List[dict] = res["results"]
        shell.sprint(json.dumps(results, indent=2))
        for result in results:
            ok = result["ok"]
            msg = result.get("msg")
            line = result.get("line")
            if msg is None:
                msg = ""
            qr = result.get("query_result")

            shell.sprint("query: %s" % line)
            s = "OK" if ok else "ERR"
            shell.sprint("processed: %s" % s)
            shell.sprint("   result: %s" % qr)
            shell.sprint("message: %s" % msg)
