import argparse

from dt_shell import DTCommandAbs
from dt_shell.remote import make_server_request


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
            raise Exception(msg)

        if parsed.submission is not None:
            submission_id = dtserver_reset_submission(token,
                                                      submission_id=parsed.submission,
                                                      step_name=parsed.step)
            print('Successfully reset %s' % submission_id)
        elif parsed.job is not None:
            job_id = dtserver_reset_job(token, job_id=parsed.job)
            print('Successfully reset %s' % job_id)
        else:
            assert False


def dtserver_reset_submission(token, submission_id, step_name):
    endpoint = '/reset-submission'
    method = 'POST'
    data = {'submission_id': submission_id, 'step_name': step_name}
    return make_server_request(token, endpoint, data=data, method=method)


def dtserver_reset_job(token, job_id):
    endpoint = '/reset-job'
    method = 'POST'
    data = {'job_id': job_id}
    return make_server_request(token, endpoint, data=data, method=method)
