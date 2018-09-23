import argparse
import datetime
import sys

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import get_dockerhub_username
from dt_shell.remote import dtserver_update_challenge


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        token = shell.get_dt1_token()

        parser = argparse.ArgumentParser()
        parser.add_argument('--no-cache', default=False, dest='no_cache', action='store_true')
        parser.add_argument('--no-push', default=False, dest='no_push', action='store_true')
        parsed = parser.parse_args(args)

        username = get_dockerhub_username(shell)
        ci = read_challenge_info('.')
        challenge_name = ci.challenge_name

        import docker

        date_tag = tag_from_date(datetime.datetime.now())
        repository = '%s/%s-evaluator' % (username, challenge_name)
        tag = '%s:%s' % (repository, date_tag)

        df = 'Dockerfile'
        if not os.path.exists(df):
            msg = 'I expected to find the file "%s".' % df
            raise Exception(msg)

        client = docker.from_env()
        dtslogger.info('Building image...')
        image, logs = client.images.build(path='.', tag=tag, nocache=parsed.no_cache)
        dtslogger.info('...done.')
        sha = image.id  # sha256:XXX
        complete = '%s@%s' % (tag, sha)

        # complete = '%s@%s' % (repository, sha)

        dtslogger.info('The complete image is %s' % complete)

        if not parsed.no_push:
            dtslogger.info('Pushing image...')
            for line in client.images.push(repository=repository, tag=date_tag, stream=True):  # , tag=tag)

                line = line.replace('\n', ' ')
                sys.stderr.write('docker: ' + str(line).strip()[:80] + ' ' + '\r')

            dtslogger.info('...done')

        challenge_parameters = {
            'protocol': 'p1',
            # 'container': complete,
            'container': tag,
        }
        dtserver_update_challenge(token, challenge_name, challenge_parameters)


def tag_from_date(d):
    # YYYY-MM-DDTHH:MM:SS[.mmmmmm][+HH:MM].
    s = d.isoformat()

    s = s.replace(':', '_')
    s = s.replace('T', '_')
    s = s.replace('-', '_')
    s = s[:s.index('.')]
    return s


# FIXME: repeated code - because no robust way to have imports in duckietown-shell-commands


def find_conf_file(d, fn0):
    print d, fn0
    fn = os.path.join(d, fn0)
    if os.path.exists(fn):
        return fn
    else:
        d0 = os.path.dirname(d)
        if not d0 or d0 == '/':
            msg = 'Could not find file %r' % fn0
            raise Exception(msg)
        return find_conf_file(d0, fn0)


class ChallengeInfoLocal:
    def __init__(self, challenge_name):
        self.challenge_name = challenge_name


def read_challenge_info(dirname):
    bn = 'challenge.yaml'
    dirname = os.path.realpath(dirname)
    fn = find_conf_file(dirname, bn)

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
    if not os.path.exists(fn):
        msg = 'File does not exist: %s' % fn
        raise Exception(msg)

    with open(fn) as f:
        data = f.read()

        try:
            return yaml.load(data, Loader=yaml.Loader)
        except Exception as e:
            msg = 'Could not read YAML file %s:\n\n%s' % (fn, e)
            raise Exception(msg)
