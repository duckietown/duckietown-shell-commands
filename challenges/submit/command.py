import argparse
import datetime
import json
import subprocess
import traceback

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import get_dockerhub_username, check_docker_environment
from dt_shell.remote import dtserver_submit, get_duckietown_server_url


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
    image = '%s/%s:%s' % (username.lower(), challenge.lower() + '-submission', tag)

    if not os.path.exists(df):
        msg = 'I expected to find the file "%s".' % df
        raise Exception(msg)

    cmd = ['docker', 'build',
           '-t', image,
           '-f', df,
           '.',
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

            msg += '\n\nI tried to push the tag\n\n   %s' % image

            msg += '\n\nYou told me your DockerHub username is "%s"' % username

            msg += '\n\nEither the username is wrong or you need to login using "docker login".'

            msg += '\n\nTo change the username use\n\n    dts challenges config config --docker-username USERNAME'
            raise Exception(msg)

    return image


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        check_docker_environment()

        token = shell.get_dt1_token()

        prog = 'dts challenges submit'
        usage = """
        

Submission:

    %(prog)s --challenge NAME



## Building options

Rebuilds ignoring Docker cache

    %(prog)s --no-cache



## Attaching user data
    
Submission with an identifying label:

    %(prog)s --user-label  "My submission"    
    
Submission with an arbitrary JSON payload:

    %(prog)s --user-meta  '{"param1": 123}'   
        

        
        
"""
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        group = parser.add_argument_group("Submission identification")
        parser.add_argument('--challenge',
                            help="Specify challenge name.", default=None)
        group.add_argument('--user-label', dest='message', action="store", nargs='+', default=None, type=str,
                           help="Submission message")
        group.add_argument('--user-meta', dest='metadata', action='store', nargs='+', default=None,
                           help="Custom JSON structure to attach to the submission")

        group = parser.add_argument_group("Building settings.")
        group.add_argument('--no-push', dest='no_push', action='store_true', default=False,
                           help="Disable pushing of container")
        group.add_argument('--no-submit', dest='no_submit', action='store_true', default=False,
                           help="Disable submission (only build and push)")
        group.add_argument('--no-cache', dest='no_cache', action='store_true', default=False)

        group.add_argument('-C', dest='cwd', default=None, help='Base directory')

        parsed = parser.parse_args(args)

        do_push = not parsed.no_push

        if parsed.cwd is not None:
            dtslogger.info('Changing to directory %s' % parsed.cwd)
            os.chdir(parsed.cwd)

        if not os.path.exists('submission.yaml'):
            msg = 'Expected a submission.yaml file in %s.' % (os.path.realpath(os.getcwd()))
            raise Exception(msg)

        sub_info = read_submission_info('.')

        if parsed.message:
            sub_info.user_label = parsed.message
        if parsed.metadata:
            sub_info.user_payload = json.loads(parsed.metadata)
        if parsed.challenge:
            sub_info.challenge_name = parsed.challenge

        username = get_dockerhub_username(shell)

        hashname = build(username, sub_info.challenge_name, do_push, no_cache=parsed.no_cache)

        data = {'hash': hashname,
                'user_label': sub_info.user_label,
                'user_payload': sub_info.user_payload,
                'protocols': sub_info.protocols}

        if not parsed.no_submit:
            submission_id = dtserver_submit(token, sub_info.challenge_name, data)
            print('Successfully created submission %s' % submission_id)
            print('')
            url = get_duckietown_server_url() + '/humans/submissions/%s' % submission_id
            print('You can track the progress at: %s' % url)

            print('')
            print('You can also use the command:')
            print('')
            print('   dts challenges follow --submission %s' % submission_id)


class CouldNotReadInfo(Exception):
    pass


class SubmissionInfo(object):
    def __init__(self, challenge_name, user_label, user_payload, protocols):
        self.challenge_name = challenge_name
        self.user_label = user_label
        self.user_payload = user_payload
        self.protocols = protocols


def read_submission_info(dirname):
    bn = 'submission.yaml'
    fn = os.path.join(dirname, bn)

    try:
        data = read_yaml_file(fn)
    except Exception as e:
        raise CouldNotReadInfo(traceback.format_exc(e))
    try:
        known = ['challenge', 'protocol', 'user-label', 'user-payload']
        challenge_name = data.pop('challenge')
        protocols = data.pop('protocol')
        if isinstance(protocols, (str, unicode)):
            protocols = [protocols]
        user_label = data.pop('user-label', None)
        user_payload = data.pop('user-payload', None)
        if data:
            msg = 'Unknown keys: %s' % list(data)
            msg += '\n\nI expect only the keys %s' % known
            raise Exception(msg)
        return SubmissionInfo(challenge_name, user_label, user_payload, protocols)
    except Exception as e:
        msg = 'Could not read file %r: %s' % (fn, e)
        raise CouldNotReadInfo(msg)


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
