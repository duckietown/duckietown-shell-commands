import argparse
import copy
import json
import os
import sys
import time
import datetime
from shutil import which
from pathlib import Path
from termcolor import colored
from docker.errors import ImageNotFound, ContainerError, APIError

from dt_shell import DTCommandAbs, dtslogger

from utils.docker_utils import \
    DEFAULT_MACHINE, \
    DOCKER_INFO, \
    get_endpoint_architecture, \
    get_client, \
    pull_image
from utils.dtproject_utils import \
    CANONICAL_ARCH, \
    BUILD_COMPATIBILITY_MAP, \
    CLOUD_BUILDERS, \
    DTProject, \
    dtlabel, \
    DISTRO_KEY
from utils.misc_utils import human_time, human_size
from utils.cli_utils import start_command_in_subprocess

from .image_analyzer import ImageAnalyzer, EXTRA_INFO_SEPARATOR


class DTCommand(DTCommandAbs):

    help = 'Builds the current project'

    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('-C', '--workdir', default=os.getcwd(),
                            help="Directory containing the project to build")
        parser.add_argument('-a', '--arch', default=None, choices=set(CANONICAL_ARCH.values()),
                            help="Target architecture for the image to build")
        parser.add_argument('-H', '--machine', default=None,
                            help="Docker socket or hostname where to build the image")
        parser.add_argument('--pull', default=False, action='store_true',
                            help="Whether to pull the latest base image used by the Dockerfile")
        parser.add_argument('--no-cache', default=False, action='store_true',
                            help="Whether to use the Docker cache")
        parser.add_argument('--force-cache', default=False, action='store_true',
                            help="Whether to force Docker to use an old version of the same "
                                 "image as cache")
        parser.add_argument('--no-multiarch', default=False, action='store_true',
                            help="Whether to disable multiarch support (based on bin_fmt)")
        parser.add_argument('-f', '--force', default=False, action='store_true',
                            help="Whether to force the build when the git index is not clean")
        parser.add_argument('--push', default=False, action='store_true',
                            help="Whether to push the resulting image")
        parser.add_argument('--rm', default=False, action='store_true',
                            help="Remove the images once the build succeded (after pushing)")
        parser.add_argument('--loop', default=False, action='store_true',
                            help="(Developers only) Reuse the same base image, speed up the build")
        parser.add_argument('-u', '--username', default="duckietown",
                            help="The docker registry username to tag the image with")
        parser.add_argument('-b', '--base-tag', default=None,
                            help="Docker tag for the base image. "
                                 "Use when the base image is also a development version")
        parser.add_argument('--ci', default=False, action='store_true',
                            help="Overwrites configuration for CI (Continuous Integration) builds")
        parser.add_argument('--ci-force-builder-arch', dest='ci_force_builder_arch', default=None,
                            choices=set(CANONICAL_ARCH.values()),
                            help="Forces CI to build on a specific architecture node")
        parser.add_argument('--cloud', default=False, action='store_true',
                            help="Build the image on the cloud")
        parser.add_argument('--stamp', default=False, action='store_true',
                            help="Stamp image with the build time")
        parser.add_argument('-D', '--destination', default=None,
                            help="Docker socket or hostname where to deliver the image")
        parser.add_argument('--docs', default=False, action='store_true',
                            help="Build the code documentation as well")
        parser.add_argument('-v', '--verbose', default=False, action='store_true',
                            help="Be verbose")
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        stime = time.time()
        parsed.workdir = os.path.abspath(parsed.workdir)
        dtslogger.info('Project workspace: {}'.format(parsed.workdir))
        # show info about project
        shell.include.devel.info.command(shell, args)
        project = DTProject(parsed.workdir)
        try:
            project_template_ver = int(project.type_version)
        except ValueError:
            project_template_ver = -1
        # check if the git HEAD is detached
        if project.is_detached():
            dtslogger.error('The repository HEAD is detached. Create a branch or check one out '
                            'before continuing. Aborting.')
            exit(8)
        # define build-args
        buildargs = {
            'buildargs': {},
            'labels': {}
        }
        # CI builds
        if parsed.ci:
            parsed.pull = True
            parsed.cloud = True
            parsed.push = True
            parsed.rm = True
            parsed.stamp = True
            parsed.force_cache = True
            # check that the env variables are set
            for key in ['ARCH', 'DT_TOKEN']:
                if 'DUCKIETOWN_CI_'+key not in os.environ:
                    dtslogger.error(
                        'Variable DUCKIETOWN_CI_{:s} required when building with --ci'.format(key)
                    )
                    exit(5)
            # set configuration
            parsed.arch = os.environ['DUCKIETOWN_CI_ARCH']
            buildargs['labels'][dtlabel('image.authoritative')] = '1'
        # cloud build
        if parsed.cloud:
            if parsed.arch is None:
                dtslogger.error('When building on the cloud you need to explicitly specify '
                                'a target architecture. Aborting...')
                exit(6)
            if parsed.machine is not None:
                dtslogger.error('The parameter --machine (-H) cannot be set together with '
                                + '--cloud. Use --destination (-D) if you want to specify '
                                + 'a destination for the image. Aborting...')
                exit(4)
            # route the build to the native node
            if parsed.arch not in CLOUD_BUILDERS:
                dtslogger.error(f'No cloud machines found for target architecture {parsed.arch}. '
                                f'Aborting...')
                exit(3)
            # update machine parameter
            parsed.machine = CLOUD_BUILDERS[parsed.arch]
            # in CI we can force builds on specific architectures
            if parsed.ci_force_builder_arch is not None:
                # force routing to the given architecture node
                if parsed.ci_force_builder_arch not in CLOUD_BUILDERS:
                    dtslogger.error(f'No cloud machines found for (forced) architecture '
                                    f'{parsed.ci_force_builder_arch}. Aborting...')
                    exit(7)
                # update machine parameter
                parsed.machine = CLOUD_BUILDERS[parsed.ci_force_builder_arch]
                dtslogger.info(f'Build forced to happen on {parsed.ci_force_builder_arch} CI node')
            # configure docker for DT
            if parsed.ci:
                token = os.environ['DUCKIETOWN_CI_DT_TOKEN']
                parsed.destination = parsed.machine
            else:
                token = shell.get_dt1_token()
            _add_token_to_docker_config(token)
            # update destination parameter
            if not parsed.destination:
                parsed.destination = DEFAULT_MACHINE
        # add code labels
        project_head_version = project.head_version if project.is_clean() else 'ND'
        project_closest_version = project.closest_version
        buildargs['labels'][dtlabel('code.distro')] = project.distro
        buildargs['labels'][dtlabel('code.version.head')] = project_head_version
        buildargs['labels'][dtlabel('code.version.closest')] = project_closest_version
        # git-based project
        if 'git' in project.adapters:
            buildargs['labels'][dtlabel('code.vcs')] = 'git'
            buildargs['labels'][dtlabel('code.repository')] = project.name
            buildargs['labels'][dtlabel('code.branch')] = project.version_name
            buildargs['labels'][dtlabel('code.url')] = project.url
        else:
            buildargs['labels'][dtlabel('code.vcs')] = 'ND'
            buildargs['labels'][dtlabel('code.repository')] = 'ND'
            buildargs['labels'][dtlabel('code.branch')] = 'ND'
            buildargs['labels'][dtlabel('code.url')] = 'ND'
        # add template labels
        buildargs['labels'][dtlabel('template.name')] = project.type
        buildargs['labels'][dtlabel('template.version')] = project.type_version
        # check if the index is clean
        if project.is_dirty():
            dtslogger.warning('Your index is not clean (some files are not committed).')
            dtslogger.warning('If you know what you are doing, use --force (-f) to ' +
                              'force the execution of the command.')
            if not parsed.force:
                exit(1)
            dtslogger.warning('Forced!')
        # add configuration labels (template v2+)
        if project_template_ver >= 2:
            for cfg_name, cfg_data in project.configurations().items():
                buildargs['labels'][dtlabel(f'image.configuration.{cfg_name}')] = \
                    json.dumps(cfg_data)
        # create docker client
        docker = get_client(parsed.machine)
        # get info about docker endpoint
        dtslogger.info('Retrieving info about Docker endpoint...')
        epoint = docker.info()
        if 'ServerErrors' in epoint:
            dtslogger.error('\n'.join(epoint['ServerErrors']))
            return
        epoint['MemTotal'] = human_size(epoint['MemTotal'])
        print(DOCKER_INFO.format(**epoint))
        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f'Target architecture automatically set to {parsed.arch}.')
        # create defaults
        image = project.image(parsed.arch, loop=parsed.loop, owner=parsed.username)
        # search for launchers (template v2+)
        launchers = []
        if project_template_ver >= 2:
            launchers_dir = os.path.join(parsed.workdir, 'launchers')
            files = [
                os.path.join(launchers_dir, f)
                for f in os.listdir(launchers_dir)
                if os.path.isfile(os.path.join(launchers_dir, f))
            ] if os.path.isdir(launchers_dir) else []

            def _has_shebang(f):
                with open(f, 'rt') as fin:
                    return fin.readline().startswith('#!')

            launchers = [
                Path(f).stem for f in files
                if os.access(f, os.X_OK) or _has_shebang(f)
            ]
            # add launchers to image labels
            buildargs['labels'][dtlabel('code.launchers')] = ','.join(sorted(launchers))
        # print info about multiarch
        msg = 'Building an image for {} on {}.'.format(parsed.arch, epoint['Architecture'])
        dtslogger.info(msg)
        # register bin_fmt in the target machine (if needed)
        if not parsed.no_multiarch:
            compatible_archs = BUILD_COMPATIBILITY_MAP[CANONICAL_ARCH[epoint['Architecture']]]
            if parsed.arch not in compatible_archs:
                dtslogger.info('Configuring machine for multiarch builds...')
                try:
                    docker.containers.run(
                        'multiarch/qemu-user-static:register',
                        remove=True,
                        auto_remove=True,
                        privileged=True,
                        command='--reset'
                    )
                    dtslogger.info('Multiarch Enabled!')
                except (ContainerError, ImageNotFound, APIError) as e:
                    msg = 'Multiarch cannot be enabled on the target machine. ' \
                          'This might create issues.'
                    dtslogger.warning(msg)
                    dtslogger.debug(f'The error reads:\n\t{str(e)}\n')
            else:
                msg = 'Building an image for {} on {}. Multiarch not needed!'.format(
                    parsed.arch, epoint['Architecture'])
                dtslogger.info(msg)

        # architecture target
        buildargs['buildargs']['ARCH'] = parsed.arch

        # development base images
        if parsed.base_tag is not None:
            buildargs['buildargs'][DISTRO_KEY[str(project_template_ver)]] = parsed.base_tag

        # loop mode (Experimental)
        if parsed.loop:
            buildargs['buildargs']['BASE_IMAGE'] = project.name
            buildargs['buildargs']['BASE_TAG'] = '-'.join([project.version_name, parsed.arch])
            buildargs['labels'][dtlabel('image.loop')] = '1'
            # ---
            msg = "WARNING: Experimental mode 'loop' is enabled!. Use with caution."
            dtslogger.warn(msg)

        # cache
        if not parsed.no_cache:
            # check if the endpoint contains an image with the same name
            try:
                docker.images.get(image)
                is_present = True
            except (ImageNotFound, BaseException):
                is_present = False
            # ---
            if not is_present:
                # try to pull the same image so Docker can use it as cache source
                dtslogger.info('Pulling image "%s" to use as cache...' % image)
                try:
                    pull_image(image, endpoint=docker, progress=not parsed.ci)
                    is_present = True
                except KeyboardInterrupt:
                    dtslogger.info('Aborting.')
                    return
                except (ImageNotFound, BaseException):
                    dtslogger.warning('An error occurred while pulling the image "%s", maybe the '
                                      'image does not exist' % image)
            else:
                dtslogger.info('Found an image with the same name. Using it as cache source.')
            # configure cache
            if parsed.force_cache and is_present:
                buildargs['cache_from'] = [image]

        # stamp image
        build_time = 'ND'
        if parsed.stamp:
            if project.is_dirty():
                dtslogger.warning('Your git index is not clean. You can\'t stamp an image built '
                                  'from a dirty index. The image will not be stamped.')
            else:
                # project is clean
                build_time = None
                local_sha = project.sha
                # get remote image metadata
                try:
                    labels = project.image_labels(parsed.machine, parsed.arch, parsed.username)
                    time_label = dtlabel('time')
                    sha_label = dtlabel('code.sha')
                    if time_label in labels and sha_label in labels:
                        remote_time = labels[time_label]
                        remote_sha = labels[sha_label]
                        if remote_sha == local_sha and remote_time != 'ND':
                            dtslogger.debug('Identical image found. Reusing cache.')
                            # local and remote SHA match, reuse time
                            build_time = remote_time
                except BaseException as e:
                    dtslogger.warning(f'Cannot fetch image metadata. Reason: {str(e)}')
        # default build_time
        build_time = build_time or datetime.datetime.utcnow().isoformat()
        dtslogger.debug(f'Image timestamp: {build_time}')
        # add timestamp label
        buildargs['labels'][dtlabel('time')] = build_time
        # add code SHA label (CI only)
        code_sha = project.sha if project.is_clean() else 'ND'
        buildargs['labels'][dtlabel('code.sha')] = code_sha

        # collect build args
        buildargs.update({
            'path': parsed.workdir,
            'rm': True,
            'pull': parsed.pull,
            'nocache': parsed.no_cache,
            'tag': image
        })
        dtslogger.debug('Build arguments:\n%s\n' % json.dumps(buildargs, sort_keys=True, indent=4))

        # build image
        buildlog = []
        try:
            for line in docker.api.build(**buildargs, decode=True):
                line = _build_line(line)
                if not line:
                    continue
                try:
                    sys.stdout.write(line)
                    buildlog.append(line)
                except UnicodeEncodeError:
                    pass
                sys.stdout.flush()

        except APIError as e:
            dtslogger.error(f'An error occurred while building the project image:\n{str(e)}')
            exit(1)
        except ProjectBuildError:
            dtslogger.error(f'An error occurred while building the project image.')
            exit(2)
        dimage = docker.images.get(image)

        # tag release images
        if project.is_release():
            rimage = project.image_release(parsed.arch, owner=parsed.username)
            dimage.tag(*rimage.split(':'))
            msg = f'Successfully tagged {rimage}'
            buildlog.append(msg)
            print(msg)

        # build code docs
        if parsed.docs:
            docs_args = ['--quiet'] * int(not parsed.verbose)
            # build docs
            dtslogger.info('Building documentation...')
            shell.include.devel.docs.build.command(shell, args + docs_args)

        # get image history
        historylog = [(layer['Id'], layer['Size']) for layer in dimage.history()]

        # round up extra info
        extra_info = []
        # - launchers info
        if len(launchers) > 0:
            extra_info.append('Image launchers:')
            for launcher in launchers:
                extra_info.append(' - {:s}'.format(launcher))
            extra_info.append(EXTRA_INFO_SEPARATOR)
        # - timing
        extra_info.append('Time: {}'.format(human_time(time.time() - stime)))
        # - documentation
        extra_info.append('Documentation: {}'.format(
            colored('Built', 'green') if parsed.docs else
            colored('Skipped', 'yellow')
        ))
        # compile extra info
        extra_info = '\n'.join(extra_info)
        # run docker image analysis
        _, _, final_image_size = ImageAnalyzer.process(
            buildlog, historylog, codens=100, extra_info=extra_info, nocolor=parsed.ci
        )
        # pull image (if the destination is different from the builder machine)
        if parsed.destination and parsed.machine != parsed.destination:
            _transfer_image(
                origin=parsed.machine,
                destination=parsed.destination,
                image=image,
                image_size=final_image_size
            )
        # perform push (if needed)
        if parsed.push:
            if not parsed.loop:
                # call devel/push
                shell.include.devel.push.command(shell, [], parsed=copy.deepcopy(parsed))
            else:
                msg = "Forbidden: You cannot push an image when using the flag `--loop`."
                dtslogger.warn(msg)
        # perform remove (if needed)
        if parsed.rm:
            # noinspection PyBroadException
            try:
                shell.include.devel.clean.command(shell, [], parsed=copy.deepcopy(parsed))
            except BaseException:
                dtslogger.warn(
                    "We had some issues cleaning up the image on '{:s}'".format(
                        parsed.machine
                    ) + ". Just a heads up!"
                )

    @staticmethod
    def complete(shell, word, line):
        return []


class ProjectBuildError(Exception):
    pass


def _transfer_image(origin, destination, image, image_size):
    monitor_info = '' if which('pv') else ' (install `pv` to see the progress)'
    dtslogger.info(f'Transferring image "{image}": [{origin}] -> [{destination}]{monitor_info}...')
    data_source = ['docker', '-H=%s' % origin, 'save', image]
    data_destination = ['docker', '-H=%s' % destination, 'load']
    progress_monitor = ['|', 'pv', '-cN', 'image', '-s', image_size] if which('pv') else []
    cmd = data_source + progress_monitor + data_destination
    start_command_in_subprocess(cmd, nostdout=True)


def _build_line(line):
    if 'error' in line and 'errorDetail' in line:
        msg = line['errorDetail']['message']
        dtslogger.error(msg)
        raise ProjectBuildError(msg)
    if 'stream' not in line:
        return None
    line = line['stream'].strip('\n')
    if not line:
        return None
    # this allows apps inside docker build to clear lines
    if not line.endswith('\r'):
        line += '\n'
    # ---
    return line


def _add_token_to_docker_config(token):
    config = {}
    config_file = os.path.expanduser('~/.docker/config.json')
    if os.path.isfile(config_file):
        config = json.load(open(config_file, 'r')) if os.path.exists(config_file) else {}
    else:
        docker_config_dir = os.path.dirname(config_file)
        dtslogger.info('Creating directory "{:s}"'.format(docker_config_dir))
        os.makedirs(docker_config_dir)
    if 'HttpHeaders' not in config:
        config['HttpHeaders'] = {}
    if 'X-Duckietown-Token' not in config['HttpHeaders']:
        config['HttpHeaders']['X-Duckietown-Token'] = token
        json.dump(config, open(config_file, 'w'), indent=2)
