import argparse
import datetime
import os

import yaml

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import get_dockerhub_username
from dt_shell.remote import dtserver_challenge_define


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

        parsed = parser.parse_args(args)

        no_cache = False

        fn = os.path.join(parsed.config)
        if not os.path.exists(fn):
            msg = 'File %s does not exist.' % fn
            raise Exception(msg)

        # basename = os.path.basename(os.path.splitext(fn)[0])
        contents = open(fn).read()
        data = yaml.load(contents)

        challenge = ChallengeDescription.from_yaml(data)

        if parsed.build:
            import docker
            client = docker.from_env()
            builds = parsed.build.split(',')
            for build in builds:
                service_to_build, dirname = build.split(':')
                dtslogger.info('building for service %s in dir %s' % (service_to_build, dirname))

                image, tag, repo_only, tag_only = build_image(client, dirname, challenge.name, no_cache)
                dtslogger.info('Pushing %s' % tag)
                for line in client.images.push(repo_only, tag_only, stream=True):
                    print(line)

                nchanged = 0
                for step in challenge.steps.values():
                    services = step.evaluation_parameters.services
                    for service_name, service in services.items():
                        if service_name == service_to_build:
                            dtslogger.info('Using %s = %s' % (service_name, tag))
                            service.image = tag
                            nchanged += 1
                if nchanged == 0:
                    msg = 'Could not find service %s' % service_to_build
                    raise Exception(msg)

        data2 = yaml.dump(challenge.as_dict())

        challenge_id = dtserver_challenge_define(token, data2)
        print('created challenge %s' % challenge_id)


def build_image(client, path, challenge_name, no_cache=False):
    d = datetime.datetime.now()
    username = get_dockerhub_username()
    tag_only = tag_from_date(d)
    repo_only = '%s/%s-evaluator' % (username, challenge_name)
    tag = '%s:%s' % (repo_only, tag_only)
    image = client.images.build(path=path, nocache=no_cache, tag=tag)
    return image, tag, repo_only, tag_only


def tag_from_date(d):
    # YYYY-MM-DDTHH:MM:SS[.mmmmmm][+HH:MM].
    s = d.isoformat()

    s = s.replace(':', '_')
    s = s.replace('T', '_')
    s = s.replace('-', '_')
    s = s[:s.index('.')]
    return s
