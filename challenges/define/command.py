import argparse
import datetime
import os

import yaml
from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import get_dockerhub_username
from dt_shell.remote import dtserver_challenge_define
from dt_shell.utils import indent
from duckietown_challenges.challenge import SUBMISSION_CONTAINER_TAG


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        try:
            from duckietown_challenges.challenge import ChallengeDescription
        except ImportError as e:
            msg = 'You need to install or update duckietown-challenges:\n%s' % e
            raise Exception(msg)

        token = shell.get_dt1_token()

        parser = argparse.ArgumentParser()
        parser.add_argument('--config', required=True,
                            help="YAML configuration file")

        parser.add_argument('--build', default=None, help="try `evaluator:.`")
        parser.add_argument('--no-cache', default=False, action='store_true')
        parser.add_argument('--no-push', default=False, action='store_true')

        parsed = parser.parse_args(args)

        no_cache = parsed.no_cache
        no_push = parsed.no_push

        fn = os.path.join(parsed.config)
        if not os.path.exists(fn):
            msg = 'File %s does not exist.' % fn
            raise Exception(msg)

        # basename = os.path.basename(os.path.splitext(fn)[0])
        contents = open(fn).read()
        data = yaml.load(contents)

        if 'description' in data:
            if data['description'] is None:
                fnd = os.path.join(os.path.dirname(fn), 'challenge.description.md')
                if os.path.exists(fnd):
                    desc = open(fnd).read()
                    data['description'] = desc
                    msg = 'Read description from %s' % fnd
                    dtslogger.info(msg)

        challenge = ChallengeDescription.from_yaml(data)

        import docker
        client = docker.from_env()

        if parsed.build:
            builds = parsed.build.split(',')
            for build in builds:
                service_to_build, dirname = build.split(':')
                msg = 'building for service %s in dir %s (no-cache: %s)' % (service_to_build, dirname, no_cache)
                dtslogger.info(msg)

                image, tag, repo_only, tag_only = build_image(client, dirname, challenge.name, no_cache)

                image_digest = image.id  # sha256:...
                dtslogger.info('image digest: %s' % image_digest)

                if not no_push:
                    dtslogger.info('Pushing %s' % tag)
                    for line in client.images.push(repo_only, tag_only, stream=True):
                        print(line)
                else:
                    dtslogger.info('skipping push')

                nchanged = 0
                for step in challenge.steps.values():
                    services = step.evaluation_parameters.services
                    for service_name, service in services.items():
                        if service_name == service_to_build:
                            dtslogger.info('Using %s = %s' % (service_name, tag))
                            service.image = tag
                            service.image_digest = image_digest
                            nchanged += 1
                if nchanged == 0:
                    msg = 'Could not find service %s' % service_to_build
                    raise Exception(msg)

        for step in challenge.steps.values():
            for service_name, service in step.evaluation_parameters.services.items():
                if service.image == SUBMISSION_CONTAINER_TAG:
                    continue
                if service.image_digest is None:
                    msg = 'Finding digest for image %s' % service.image
                    dtslogger.info(msg)
                    image = client.images.get(service.image)
                    digest = image.id
                    service.image_digest = digest
                    dtslogger.info('Found: %s' % digest)

        data2 = yaml.dump(challenge.as_dict())

        res = dtserver_challenge_define(token, data2)
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


def build_image(client, path, challenge_name, no_cache=False):
    d = datetime.datetime.now()
    username = get_dockerhub_username()
    tag_only = tag_from_date(d)
    repo_only = '%s/%s-evaluator' % (username, challenge_name)
    tag = '%s:%s' % (repo_only, tag_only)
    _ = client.images.build(path=path, nocache=no_cache, tag=tag)
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
