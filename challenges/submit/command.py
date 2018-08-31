import argparse
import datetime
import os
import subprocess

from dt_shell import DTCommandAbs
from dt_shell.env_checks import get_dockerhub_username
from dt_shell.remote import dtserver_submit
from duckietown_challenges.local_config import read_challenge_info


def tag_from_date(d):
    # YYYY-MM-DDTHH:MM:SS[.mmmmmm][+HH:MM].
    s = d.isoformat()

    s = s.replace(':', '_')
    s = s.replace('T', '_')
    s = s.replace('-', '_')
    s = s[:s.index('.')]
    return s


def build(username, challenge, do_push=True, no_cache=False):
    tag = tag_from_date(datetime.datetime.now())
    df = 'Dockerfile'
    image = '%s/%s:%s' % (username, challenge, tag)

    if not os.path.exists(df):
        msg = 'I expected to find the file "%s".' % df
        raise Exception(msg)

    # try:
    #     from duckietown_challenges import CHALLENGE_SOLUTION
    # except ImportError as e:
    #     msg = 'Need to install the duckietown-challenges package: %s' % e
    #     raise Exception(msg)  # XXX

    cmd = ['docker', 'build', '.',
           '-t', image,
           '-f', df,
           # '--build-arg', 'CHALLENGE_SOLUTION=%s' % CHALLENGE_SOLUTION,
           ]

    if no_cache:
        cmd.append('--no-cache')
    print(cmd)
    p = subprocess.Popen(cmd)
    p.communicate()
    if p.returncode != 0:
        msg = 'Could not run docker build.'
        raise Exception(msg)

    if do_push:
        cmd = ['docker', 'push', image]
        p = subprocess.Popen(cmd)
        p.communicate()
        p.communicate()

        if p.returncode != 0:
            msg = 'Could not run docker push.'
            raise Exception(msg)

    return image


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        token = shell.get_dt1_token()

        parser = argparse.ArgumentParser()
        parser.add_argument('--no-push', dest='no_push', action='store_true', default=False,
                            help="Disable pushing of container")
        parser.add_argument('--no-submit', dest='no_submit', action='store_true', default=False,
                            help="Disable submission (only build and push)")
        parser.add_argument('--no-cache', dest='no_cache', action='store_true', default=False)
        parsed = parser.parse_args(args)

        do_push = not parsed.no_push

        username = get_dockerhub_username(shell)

        ci = read_challenge_info('.')
        challenge = ci.challenge_name

        hashname = build(username, challenge, do_push, no_cache=parsed.no_cache)

        data = {'hash': hashname}

        if not parsed.no_submit:
            submission_id = dtserver_submit(token, challenge, data)
            print('Successfully created submission %s' % submission_id)
