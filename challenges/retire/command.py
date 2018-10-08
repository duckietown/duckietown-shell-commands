import argparse

from dt_shell import DTCommandAbs
from dt_shell.remote import dtserver_retire

usage = """

To retire the submission ID, use:

    dts challenges retire --submission ID


"""


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        prog = 'dts challenges retire'

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('--submission', required=True, type=int)
        parsed = parser.parse_args(args)

        token = shell.get_dt1_token()

        submission_id = parsed.submission
        submission_id = dtserver_retire(token, submission_id)

        print('Successfully retired submission %s' % submission_id)
