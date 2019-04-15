import argparse
import datetime
import os
import subprocess

import yaml

from challenges.challenges_cmd_utils import wrap_server_operations
from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import get_dockerhub_username
from dt_shell.exceptions import UserError
from dt_shell.utils import indent
from duckietown_challenges import read_yaml_file
from duckietown_challenges.challenge import ChallengeDescription, ChallengesConstants
from duckietown_challenges.cmd_submit_build import BuildResult, get_complete_tag, parse_complete_tag
from duckietown_challenges.rest_methods import get_registry_info, RegistryInfo, dtserver_challenge_define


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):

        token = shell.get_dt1_token()

        parser = argparse.ArgumentParser()
        parser.add_argument('--config', default='challenge.yaml',
                            help="YAML configuration file")

        parser.add_argument('--no-cache', default=False, action='store_true')
        parser.add_argument('--steps', default=None, help='Which steps (comma separated)')
        parser.add_argument('--force-invalidate-subs', default=False, action='store_true')
        parser.add_argument('-C', dest='cwd', default=None, help='Base directory')
        parser.add_argument('--impersonate', type=str, default=None)

        parsed = parser.parse_args(args)
        impersonate = parsed.impersonate

        from dt_shell.env_checks import check_docker_environment
        client = check_docker_environment()
        if client is None:  # To remove when done
            client = check_docker_environment()

        if parsed.cwd is not None:
            dtslogger.info('Changing to directory %s' % parsed.cwd)
            os.chdir(parsed.cwd)

        no_cache = parsed.no_cache

        fn = os.path.join(parsed.config)
        if not os.path.exists(fn):
            msg = 'File %s does not exist.' % fn
            raise UserError(msg)

        data = read_yaml_file(fn)

        if 'description' not in data or data['description'] is None:
            fnd = os.path.join(os.path.dirname(fn), 'challenge.description.md')
            if os.path.exists(fnd):
                desc = open(fnd).read()
                data['description'] = desc
                msg = 'Read description from %s' % fnd
                dtslogger.info(msg)

        base = os.path.dirname(fn)

        challenge = ChallengeDescription.from_yaml(data)

        with wrap_server_operations():
            go(token, impersonate, parsed, challenge, base, client, no_cache)


def go(token, impersonate, parsed, challenge, base, client, no_cache):
    ri = get_registry_info(token=token, impersonate=impersonate)

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

                br = \
                    build_image(client, context, challenge.name, step_name,
                                service_name, dockerfile_abs,
                                no_cache, registry_info=ri)
                complete = get_complete_tag(br)
                service.image = complete

                # very important: get rid of it!
                service.build = None
            else:
                if service.image == ChallengesConstants.SUBMISSION_CONTAINER_TAG:
                    pass
                else:
                    msg = 'Finding digest for image %s' % service.image
                    dtslogger.info(msg)
                    image = client.images.get(service.image)
                    service.image_digest = image.id
                    dtslogger.info('Found: %s' % image.id)

    data2 = yaml.dump(challenge.as_dict())

    res = dtserver_challenge_define(token, data2, parsed.force_invalidate_subs, impersonate=impersonate)
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


def build_image(client, path, challenge_name, step_name, service_name, filename, no_cache: bool,
                registry_info: RegistryInfo) -> BuildResult:
    d = datetime.datetime.now()
    username = get_dockerhub_username()
    from duckietown_challenges.utils import tag_from_date
    if username.lower() != username:
        msg = f'Are you sure that the DockerHub username is not lowercase? You gave "{username}".'
        dtslogger.warning(msg)
        username = username.lower()
    br = BuildResult(
            repository=('%s-%s-%s' % (challenge_name, step_name, service_name)).lower(),
            organization=username,
            registry=registry_info.registry,
            tag=tag_from_date(d),
            digest=None)
    complete = get_complete_tag(br)

    cmd = ['docker', 'build', '--pull', '-t', complete, '-f', filename]
    if no_cache:
        cmd.append('--no-cache')

    cmd.append(path)
    dtslogger.debug('Running %s' % " ".join(cmd))
    subprocess.check_call(cmd)

    cmd = ['docker', 'push', complete]
    dtslogger.debug('Running %s' % " ".join(cmd))
    subprocess.check_call(cmd)

    image = client.images.get(complete)
    dtslogger.info('image id: %s' % image.id)
    dtslogger.info('complete: %s' % get_complete_tag(br))
    br.digest = image.id

    br = parse_complete_tag(get_complete_tag(br))
    return br
