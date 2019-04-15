import argparse

from dt_shell import DTCommandAbs, DTShell, UserError
from duckietown_challenges.rest import ServerIsDown

usage = """

To retire the submission ID, use:

    dts challenges retire --submission ID


"""


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args):
        prog = 'dts challenges retire'

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('--submission', required=True, type=int)
        parsed = parser.parse_args(args)

        token = shell.get_dt1_token()

        submission_id = parsed.submission
        from duckietown_challenges.rest_methods import dtserver_retire

        try:
            submission_id = dtserver_retire(token, submission_id)

            shell.sprint('Successfully retired submission %s' % submission_id)
        except ServerIsDown as e:
            msg = 'The server is temporarily down. Please try again later.'
            msg += '\n\n' + str(e)
            raise UserError(msg)
