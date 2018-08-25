from dt_shell import DTCommandAbs
from dt_shell.remote import dtserver_retire


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):

        token = shell.get_dt1_token()

        for a in args:
            submission_id = int(a)
            info = dtserver_retire(token, submission_id)

            if not info['ok']:
                msg = info['error']
                raise Exception(msg)  # XXX
            # submission_id = info['submission_id']
            print('Successfully retired submission %s' % submission_id)
