import argparse

from dt_shell import DTCommandAbs, UserError
from duckietown_challenges.rest import ServerIsDown


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        token = shell.get_dt1_token()
        parser = argparse.ArgumentParser(prog='dts challenges reset')
        parser.add_argument("--job", default=None, help='Only reset this particular job', type=int)
        parser.add_argument("--submission", default=None, type=int, help='Reset this particular submission')
        parser.add_argument("--step", default=None, help='Only reset this particular step')
        parsed = parser.parse_args(args)

        if parsed.submission is None and parsed.job is None:
            msg = 'You need to specify either --job or --submission.'
            raise UserError(msg)

        try:
            if parsed.submission is not None:
                from duckietown_challenges.rest_methods import dtserver_reset_submission
                submission_id = dtserver_reset_submission(token,
                                                          submission_id=parsed.submission,
                                                          step_name=parsed.step)
                shell.sprint('Successfully reset %s' % submission_id)
            elif parsed.job is not None:
                from duckietown_challenges.rest_methods import dtserver_reset_job
                job_id = dtserver_reset_job(token, job_id=parsed.job)
                shell.sprint('Successfully reset %s' % job_id)
            else:
                assert False

        except ServerIsDown as e:
            msg = 'The server is temporarily down. Please try again later.'
            msg += '\n\n' + str(e)
            raise UserError(msg)
