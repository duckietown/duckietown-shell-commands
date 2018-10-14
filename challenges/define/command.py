import argparse
import datetime
import os
import subprocess

import yaml

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import get_dockerhub_username
from dt_shell.remote import make_server_request
from dt_shell.utils import indent


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        try:
            from duckietown_challenges.challenge import ChallengeDescription
            from duckietown_challenges.challenge import SUBMISSION_CONTAINER_TAG
        except ImportError as e:
            msg = 'You need to install or update duckietown-challenges:\n%s' % e
            raise Exception(msg)

        token = shell.get_dt1_token()

        parser = argparse.ArgumentParser()
        parser.add_argument('--config', default='challenge.yaml',
                            help="YAML configuration file")

        # parser.add_argument('--build', default=None, help="try `evaluator:.`")
        parser.add_argument('--no-cache', default=False, action='store_true')
        parser.add_argument('--no-push', default=False, action='store_true')
        parser.add_argument('--steps', default=None, help='Which steps (comma separated)')
        parser.add_argument('--force-invalidate-subs', default=False, action='store_true')
        parser.add_argument('-C', dest='cwd', default=None, help='Base directory')

        parsed = parser.parse_args(args)

        if parsed.cwd is not None:
            dtslogger.info('Changing to directory %s' % parsed.cwd)
            os.chdir(parsed.cwd)

        no_cache = parsed.no_cache
        no_push = parsed.no_push

        fn = os.path.join(parsed.config)
        if not os.path.exists(fn):
            msg = 'File %s does not exist.' % fn
            raise Exception(msg)

        # basename = os.path.basename(os.path.splitext(fn)[0])
        contents = open(fn).read()
        data = yaml.load(contents)

        if 'description' not in data or data['description'] is None:
            fnd = os.path.join(os.path.dirname(fn), 'challenge.description.md')
            if os.path.exists(fnd):
                desc = open(fnd).read()
                data['description'] = desc
                msg = 'Read description from %s' % fnd
                dtslogger.info(msg)

        base = os.path.dirname(fn)

        challenge = ChallengeDescription.from_yaml(data)

        import docker
        client = docker.from_env()

        if parsed.steps:
            use_steps = parsed.steps.split(",")
        else:
            use_steps = list(challenge.steps)
        for step_name in use_steps:
            if step_name not in challenge.steps:
                msg = 'Could not find step "%s" in %s.' % (step_name, list(challenge.steps))
                raise Exception(msg)
            step = challenge.steps[step_name]

            services = step.evaluation_parameters.services
            for service_name, service in services.items():
                if service.build:
                    dockerfile = service.build.dockerfile
                    context = os.path.join(base, service.build.context)
                    if not os.path.exists(context):
                        msg = 'Context does not exist %s' % context
                        raise Exception(msg)

                    dockerfile_abs = os.path.join(context, dockerfile)
                    if not os.path.exists(dockerfile_abs):
                        msg = 'Cannot find Dockerfile %s' % dockerfile_abs
                        raise Exception(msg)

                    dtslogger.info('context: %s' % context)
                    args = service.build.args
                    if args:
                        dtslogger.warning('arguments not supported yet: %s' % args)

                    image, tag, repo_only, tag_only = build_image(client, context, challenge.name, service_name, dockerfile_abs,
                                                                  no_cache)

                    service.image = tag

                    if not no_push:
                        cmd = ['docker', 'push', tag]
                        subprocess.check_call(cmd)

                    image = client.images.get(service.image)
                    service.image_digest = image.id

                    # very important: get rid of it!
                    service.build = None
                else:
                    if service.image_digest is None:
                        if service.image == SUBMISSION_CONTAINER_TAG:
                            pass
                        else:
                            msg = 'Finding digest for image %s' % service.image
                            dtslogger.info(msg)
                            image = client.images.get(service.image)
                            service.image_digest = image.id
                            dtslogger.info('Found: %s' % image.id)

        data2 = yaml.dump(challenge.as_dict())

        res = dtserver_challenge_define(token, data2, parsed.force_invalidate_subs)
        challenge_id = res['challenge_id']
        steps_updated = res['steps_updated']

        if steps_updated:
            print('Updated challenge %s' % challenge_id)
            print('The following steps were updated and will be invalidated.')
            for step_name, reason in steps_updated.items():
                print('\n\n' + indent(reason, ' ', step_name + '   '))
        else:
            msg = 'No update needed - the container digests did not change.'
            print(msg)


def dtserver_challenge_define(token, yaml, force_invalidate):
    endpoint = '/challenge-define'
    method = 'POST'
    data = {'yaml': yaml, 'force-invalidate': force_invalidate}
    return make_server_request(token, endpoint, data=data, method=method)


def build_image(client, path, challenge_name, service_name, filename, no_cache=False):
    d = datetime.datetime.now()
    username = get_dockerhub_username()
    tag_only = tag_from_date(d)
    repo_only = '%s/%s-%s' % (username, challenge_name.lower(), service_name.lower())
    tag = '%s:%s' % (repo_only, tag_only)
    cmd = ['docker', 'build', '-t', tag, '-f', filename]
    if no_cache:
        cmd.append('--no-cache')

    cmd.append(path)
    subprocess.check_call(cmd)
    # _ = client.images.build(path=path, nocache=no_cache, tag=tag)
    image = client.images.get(tag)
    return image, tag, repo_only, tag_only


def tag_from_date(d):
    # YYYY-MM-DDTHH:MM:SS[.mmmmmm][+HH:MM].
    s = d.isoformat()

    s = s.replace(':', '_')
    s = s.replace('T', '_')
    s = s.replace('-', '_')
    s = s[:s.index('.')]
    return s
