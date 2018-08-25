import datetime
import os
import subprocess

import yaml
from dt_shell import DTCommandAbs
from dt_shell.constants import DTShellConstants
from dt_shell.remote import dtserver_submit


def tag_from_date(d):
    # YYYY-MM-DDTHH:MM:SS[.mmmmmm][+HH:MM].
    s = d.isoformat()

    s = s.replace(':', '_')
    s = s.replace('T', '_')
    s = s.replace('-', '_')
    s = s[:s.index('.')]
    return s


def build(username, challenge):
    tag = tag_from_date(datetime.datetime.now())
    df = 'Dockerfile'
    image = '%s/%s:%s' % (username, challenge, tag)

    if not os.path.exists(df):
        msg = 'I expected to find the file "%s".' % df
        raise Exception(msg)

    cmd = ['docker', 'build', '.', '-t', image, '-f', df]
    p = subprocess.Popen(cmd)
    p.communicate()

    cmd = ['docker', 'push', image]
    p = subprocess.Popen(cmd)
    p.communicate()

    return image


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        k = DTShellConstants.DT1_TOKEN_CONFIG_KEY
        if k not in shell.config:
            msg = 'Please set up a token for this.'
            raise Exception(msg)

        token = shell.config[k]

        k = DTShellConstants.CONFIG_DOCKER_USERNAME
        if k not in shell.config:
            msg = 'Please set docker username using\n\n dts challenges config --docker-username <USERNAME>'
            raise Exception(msg)

        username = shell.config[k]

        dn = 'challenge.yaml'
        if not os.path.exists(dn):
            msg = 'Could not find the file %r' % dn
            raise Exception(msg)

        try:
            data = yaml.load(open(dn).read())
            challenge = data['challenge']
        except Exception as e:
            msg = 'Could not read file %r: %s' % (dn, e)
            raise Exception(msg)

        hashname = build(username, challenge)

        data = {'hash': hashname}

        info = dtserver_submit(token, challenge, data)
        if not info['ok']:
            msg = info['error']
            raise Exception(msg)  # XXX
        submission_id = info['submission_id']
        print('Successfully created submission %s' % submission_id)
