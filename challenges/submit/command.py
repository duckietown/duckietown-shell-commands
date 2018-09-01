import argparse
import datetime
import os
import subprocess

from dt_shell import DTCommandAbs
from dt_shell.env_checks import get_dockerhub_username, check_docker_environment
from dt_shell.remote import dtserver_submit



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
            msg += '\nTry to login using "docker login".'
            raise Exception(msg)

    return image


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        check_docker_environment()

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


        # try:
        #     from duckietown_challenges.local_config import read_challenge_info
        # except ImportError as e:
        #     msg = 'Please install or update duckietown_challenges.'
        #     msg += '\n\n pip install -U --user duckietown-challenges '


# FIXME: repeated code - because no robust way to have imports in duckietown-shell-commands


class ChallengeInfoLocal():
    def __init__(self, challenge_name):
        self.challenge_name = challenge_name


def read_challenge_info(dirname):
    bn = 'challenge.yaml'
    fn = os.path.join(dirname, bn)

    data = read_yaml_file(fn)
    try:
        challenge_name = data['challenge']

        return ChallengeInfoLocal(challenge_name)
    except Exception as e:
        msg = 'Could not read file %r: %s' % (fn, e)
        raise Exception(msg)

import os

# noinspection PyUnresolvedReferences
import ruamel.ordereddict as s
from ruamel import yaml


def read_yaml_file(fn):
    assert os.path.exists(fn)

    with open(fn) as f:
        data = f.read()
        return yaml.load(data, Loader=yaml.Loader)

