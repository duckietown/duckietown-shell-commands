import argparse

from challenges.challenges_cmd_utils import check_duckietown_challenges_version, wrap_server_operations
from dt_shell import DTCommandAbs

usage = """

To retire the submission ID, use:

    dts challenges retire --submission ID


"""

from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        check_duckietown_challenges_version()

        prog = "dts challenges retire"

        from duckietown_challenges.rest_methods import dtserver_retire

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument("--submission", required=True, type=int)
        parsed = parser.parse_args(args)

        token = shell.get_dt1_token()

        submission_id = parsed.submission

        with wrap_server_operations():
            submission_id = dtserver_retire(token, submission_id)

        shell.sprint("Successfully retired submission %s" % submission_id)
