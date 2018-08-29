from dt_shell import DTCommandAbs
from dt_shell.remote import dtserver_retire


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):

        token = shell.get_dt1_token()

        for a in args:
            submission_id = int(a)
            submission_id = dtserver_retire(token, submission_id)

            print('Successfully retired submission %s' % submission_id)
