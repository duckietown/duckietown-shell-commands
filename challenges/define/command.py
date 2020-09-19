import argparse
import datetime
import os
import subprocess
from typing import List, Optional

import yaml
from docker import DockerClient
from zuper_ipce import IESO, ipce_from_object
from zuper_typing import debug_print

from challenges.challenges_cmd_utils import wrap_server_operations
from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.env_checks import get_dockerhub_username
from dt_shell.exceptions import UserError
from dt_shell.utils import indent
from duckietown_challenges import read_yaml_file
from duckietown_challenges.challenge import ChallengeDescription, ChallengesConstants
from duckietown_challenges.cmd_submit_build import (
    BuildResult,
    get_complete_tag,
    parse_complete_tag,
)
from duckietown_challenges.rest_methods import (
    dtserver_challenge_define,
    get_registry_info,
    RegistryInfo,
)
from duckietown_challenges.utils import tag_from_date


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):

        token = shell.get_dt1_token()

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--config", default="challenge.yaml", help="YAML configuration file"
        )

        parser.add_argument("--no-cache", default=False, action="store_true")
        parser.add_argument(
            "--steps", default=None, help="Which steps (comma separated)"
        )
        parser.add_argument(
            "--force-invalidate-subs", default=False, action="store_true"
        )
        parser.add_argument("-C", dest="cwd", default=None, help="Base directory")
        parser.add_argument("--impersonate", type=str, default=None)
        parser.add_argument(
            "--pull", default=False, action="store_true"
        )

        parsed = parser.parse_args(args)
        impersonate = parsed.impersonate

        from dt_shell.env_checks import check_docker_environment

        client = check_docker_environment()
        if client is None:  # To remove when done
            client = check_docker_environment()

        if parsed.cwd is not None:
            dtslogger.info("Changing to directory %s" % parsed.cwd)
            os.chdir(parsed.cwd)

        no_cache = parsed.no_cache

        fn = os.path.join(parsed.config)
        if not os.path.exists(fn):
            msg = "File %s does not exist." % fn
            raise UserError(msg)

        data = read_yaml_file(fn)

        if "description" not in data or data["description"] is None:
            fnd = os.path.join(os.path.dirname(fn), "challenge.description.md")
            if os.path.exists(fnd):
                desc = open(fnd).read()
                data["description"] = desc
                msg = "Read description from %s" % fnd
                dtslogger.info(msg)

        base = os.path.dirname(fn)
        dtslogger.info(f'data {data}')
        challenge = ChallengeDescription.from_yaml(data)
        assert challenge.date_close.tzinfo is not None, (
        challenge.date_close.tzinfo, challenge.date_open.tzinfo)
        assert challenge.date_open.tzinfo is not None, (
        challenge.date_close.tzinfo, challenge.date_open.tzinfo)

        dtslogger.info(debug_print(challenge))
        with wrap_server_operations():
            dts_define(token, impersonate, parsed, challenge, base, client, no_cache)


def dts_define(token: str, impersonate: Optional[int], parsed, challenge: ChallengeDescription, base,
               client: DockerClient,
               no_cache: bool):
    ri = get_registry_info(token=token, impersonate=impersonate)
    dtslogger.info(f'impersonate {impersonate}')
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
                    msg = "Context does not exist %s" % context
                    raise Exception(msg)

                dockerfile_abs = os.path.join(context, dockerfile)
                if not os.path.exists(dockerfile_abs):
                    msg = "Cannot find Dockerfile %s" % dockerfile_abs
                    raise Exception(msg)

                dtslogger.info("context: %s" % context)
                args = service.build.args
                if args:
                    dtslogger.warning("arguments not supported yet: %s" % args)

                br = build_image(
                    client,
                    context,
                    challenge.name,
                    step_name,
                    service_name,
                    dockerfile_abs,
                    no_cache,
                    registry_info=ri,
                    dopull=parsed.pull,
                )
                complete = get_complete_tag(br)
                service.image = complete

                # very important: get rid of it!
                service.build = None
            else:
                if service.image == ChallengesConstants.SUBMISSION_CONTAINER_TAG:
                    pass
                else:
                    vname = 'AIDO_REGISTRY'
                    vref = '${%s}' % vname
                    if vref in service.image:
                        value = os.environ.get(vname)
                        service.image = service.image.replace(vref, value)
                    dtslogger.info(f'service = {service}')
                    br = parse_complete_tag(service.image)
                    if br.digest is None:
                        msg = "Finding digest for image %s" % service.image
                        dtslogger.warning(msg)

                        # noinspection PyTypeChecker
                        br_no_registry = replace(br, tag=None)
                        image_name = get_complete_tag(br_no_registry)
                        image = client.images.pull(image_name, tag=br.tag)

                        # service.image_digest = image.id
                        br.digest = image.id

                        service.image = get_complete_tag(br)
                        dtslogger.warning("complete: %s" % service.image)

    ieso = IESO(with_schema=False)
    assert challenge.date_close.tzinfo is not None, (challenge.date_close, challenge.date_open)
    assert challenge.date_open.tzinfo is not None, (challenge.date_close, challenge.date_open)
    ipce = ipce_from_object(challenge, ChallengeDescription, ieso=ieso)
    data2 = yaml.dump(ipce)
    res = dtserver_challenge_define(
        token, data2, parsed.force_invalidate_subs, impersonate=impersonate
    )
    challenge_id = res["challenge_id"]
    steps_updated = res["steps_updated"]

    if steps_updated:
        dtslogger.info("Updated challenge %s" % challenge_id)
        dtslogger.info("The following steps were updated and will be invalidated.")
        for step_name, reason in steps_updated.items():
            dtslogger.info("\n\n" + indent(reason, " ", step_name + "   "))
    else:
        msg = "No update needed - the container digests did not change."
        dtslogger.info(msg)


def build_image(
    client,
    path,
    challenge_name,
    step_name,
    service_name,
    filename,
    no_cache: bool,
    registry_info: RegistryInfo,
    dopull: bool,
) -> BuildResult:
    d = datetime.datetime.now()
    username = get_dockerhub_username()

    # read the content to see if we need the AIDO_REGISTRY arg?
    with open(filename) as _:
        dockerfile = _.read()

    if username.lower() != username:
        msg = f'Are you sure that the DockerHub username is not lowercase? You gave "{username}".'
        dtslogger.warning(msg)
        username = username.lower()

    br = BuildResult(
        repository=("%s-%s-%s" % (challenge_name, step_name, service_name)).lower(),
        organization=username,
        registry=registry_info.registry,
        tag=tag_from_date(d),
        digest=None,
    )
    complete = get_complete_tag(br)

    cmd = ["docker", "build"]
    if dopull:
        cmd.append("--pull")

    cmd.extend(["-t", complete, "-f", filename])

    env_vars = ['AIDO_REGISTRY', 'PIP_INDEX_URL']
    for v in env_vars:
        if v not in dockerfile:
            continue
        val = os.getenv(v)
        if val is not None:
            cmd.append('--build-arg')
            cmd.append(f'{v}={val}')

    if no_cache:
        cmd.append("--no-cache")

    cmd.append(path)
    dtslogger.debug("$ %s" % " ".join(cmd))
    subprocess.check_call(cmd)

    use_repo_digests = False

    if use_repo_digests:
        try:
            br = get_compatible_br(client, complete, registry_info.registry)
            return br
        except KeyError:
            pass

    dtslogger.info("Image not present on registry. Need to push.")

    cmd = ["docker", "push", complete]
    dtslogger.debug("$ %s" % " ".join(cmd))
    subprocess.check_call(cmd)

    image = client.images.get(complete)
    dtslogger.info("image id: %s" % image.id)
    dtslogger.info("complete: %s" % get_complete_tag(br))

    try:
        br0 = get_compatible_br(client, complete, registry_info.registry)
    except KeyError:
        msg = "Could not find any repo digests (push not succeeded?)"
        raise Exception(msg)

    br = parse_complete_tag(complete)
    br.digest = br0.digest

    dtslogger.info(f'using: {br}')
    return br


from dataclasses import replace


def fix_none(br: BuildResult) -> BuildResult:
    if br.registry is None:
        return replace(br, registry='docker.io')
    else:
        return br


def compatible_br(rd: List[str], registry) -> List[BuildResult]:
    # dtslogger.info(rd)
    brs = [parse_complete_tag(_) for _ in rd]
    brs = list(map(fix_none, brs))
    compatible = [_ for _ in brs if _.registry == registry]
    return compatible


def get_compatible_br(client, complete, registry) -> BuildResult:
    image = client.images.get(complete)

    repo_tags = list(reversed(sorted(image.attrs.get("RepoTags", []))))
    repo_digests = list(reversed(sorted(image.attrs.get("RepoDigests", []))))
    dtslogger.info(f'repo_tags: {repo_tags}')
    dtslogger.info(f'repo_digests: {repo_digests}')
    compatible_digests = compatible_br(repo_digests, registry)
    compatible_tags = compatible_br(repo_tags, registry)

    if compatible_digests and compatible_tags:
        dtslogger.info(f'compatible: {compatible_digests} {compatible_tags}')
        br = compatible_tags[0]
        br.digest = compatible_digests[0].digest
        dtslogger.info(f'choosing: {br}\n{get_complete_tag(br)}')
        return br
    else:
        raise KeyError()
