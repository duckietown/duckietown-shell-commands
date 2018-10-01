from dt_shell import DTCommandAbs
from dt_shell.remote import dtserver_retire, make_server_request


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        token = shell.get_dt1_token()

        for a in args:
            submission_id = int(a)
            submission_id = dtserver_reset_submission(token, submission_id)

            print('Successfully reset submission %s' % submission_id)


def dtserver_reset_submission(token, submission_id):
    endpoint = '/reset-submission'
    method = 'POST'
    data = {'submission_id': submission_id}
    return make_server_request(token, endpoint, data=data, method=method)
