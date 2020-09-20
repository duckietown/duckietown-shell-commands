import argparse

from challenges.challenges_cmd_utils import check_duckietown_challenges_version, wrap_server_operations
from dt_shell import DTCommandAbs, DTShell

usage = """

To follow the fate of the submission, use:

    %(prog)s --submission ID


"""


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts challenges follow"
        check_duckietown_challenges_version()
        from duckietown_challenges import follow_submission

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument("--submission", required=True, type=int)
        parsed = parser.parse_args(args)

        token = shell.get_dt1_token()

        submission_id = parsed.submission

        with wrap_server_operations():
            follow_submission(shell, token, submission_id)
