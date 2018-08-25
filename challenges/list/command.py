from dt_shell import DTCommandAbs

from dt_shell.remote import dtserver_get_user_submissions


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        token = shell.get_dt1_token()

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
