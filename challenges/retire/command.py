import argparse

from dt_shell import DTCommandAbs
from dt_shell.constants import DTShellConstants
from dt_shell.remote import dtserver_retire


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        k = DTShellConstants.DT1_TOKEN_CONFIG_KEY
        if k not in shell.config:
            msg = 'Please set up a token for this.'
            raise Exception(msg)

        token = shell.config[k]

        for a in args:
            submission_id = int(a)
            info = dtserver_retire(token, submission_id)

            if not info['ok']:
                msg = info['error']
                raise Exception(msg)  # XXX
            # submission_id = info['submission_id']
            print('Successfully retired submission %s' % submission_id)
