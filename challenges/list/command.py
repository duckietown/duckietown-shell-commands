from dt_shell import DTCommandAbs
from dt_shell.constants import DTShellConstants

from dt_shell.remote import dtserver_get_user_submissions


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        k = DTShellConstants.DT1_TOKEN_CONFIG_KEY
        if k not in shell.config:
            msg = 'Please set up a token for this.'
            raise Exception(msg)

        token = shell.config[k]

        submissions = dtserver_get_user_submissions(token)

        def key(x):
            return submissions[x]['date_submitted']

        for submission_id in sorted(submissions, key=key):
            submission = submissions[submission_id]

            def d(dt):
                return dt.isoformat()

            print('%4d  %20s %10s   %20s   %s' % (submission['submission_id'],
                                              d(submission['date_submitted']),
                                              submission['status'],
                                              d(submission['last_status_change']),
                                              submission['parameters']))
