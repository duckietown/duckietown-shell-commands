import argparse
import copy
import io
import json
import os
import re
import subprocess
import sys
import time
import datetime
from shutil import which
from pathlib import Path
from termcolor import colored

from dt_shell import DTCommandAbs, dtslogger

from utils.docker_utils import DEFAULT_MACHINE, DOCKER_INFO, get_endpoint_architecture
from utils.dtproject_utils import \
    CANONICAL_ARCH, \
    BUILD_COMPATIBILITY_MAP, \
    DOCKER_LABEL_DOMAIN, \
    CLOUD_BUILDERS, \
    DTProject
from utils.misc_utils import human_time

from .image_analyzer import ImageAnalyzer, EXTRA_INFO_SEPARATOR

CATKIN_REGEX = "^\[build (\d+\:)?\d+\.\d+ s\] \[\d+\/\d+ complete\] .*$"


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
        parser.add_argument('-H', '--machine', default=DEFAULT_MACHINE,
                            help="Docker socket or hostname where to build the image")
        parser.add_argument('--pull', default=False, action='store_true',
                            help="Whether to pull the latest base image used by the Dockerfile")
        parser.add_argument('--no-cache', default=False, action='store_true',
                            help="Whether to use the Docker cache")
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
        parser.add_argument('-u','--username',default="duckietown",
                            help="The docker registry username to tag the image with")
        parser.add_argument('-b', '--base-tag', default=None,
                            help="Docker tag for the base image. "
                                 "Use when the base image is also a development version")
        parser.add_argument('--ci', default=False, action='store_true',
                            help="Overwrites configuration for CI (Continuous Integration) builds")
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
        # define labels / build-args
        buildlabels = []
        buildargs = []
        # CI builds
        if parsed.ci:
            parsed.pull = True
            parsed.cloud = True
            parsed.no_multiarch = True
            parsed.push = True
            parsed.rm = True
            parsed.stamp = True
            # check that the env variables are set
            for key in ['ARCH', 'MAJOR', 'DOCKERHUB_USER', 'DOCKERHUB_TOKEN', 'DT_TOKEN']:
                if 'DUCKIETOWN_CI_'+key not in os.environ:
                    dtslogger.error(
                        'Variable DUCKIETOWN_CI_{:s} required when building with --ci'.format(key)
                    )
                    sys.exit(5)
            # set configuration
            parsed.arch = os.environ['DUCKIETOWN_CI_ARCH']
            buildlabels += ['--label', f'{DOCKER_LABEL_DOMAIN}.image.authoritative=1']
        # cloud build
        if parsed.cloud:
            if parsed.arch not in CLOUD_BUILDERS:
                dtslogger.error(f'No cloud machines found for target architecture {parsed.arch}. Aborting...')
                exit(3)
            if parsed.machine != DEFAULT_MACHINE:
                dtslogger.error('The parameter --machine (-H) cannot be set together with '
                                + '--cloud. Use --destionation (-D) if you want to specify '
                                + 'a destination for the image. Aborting...')
                exit(4)
            # configure docker for DT
            if parsed.ci:
                token = os.environ['DUCKIETOWN_CI_DT_TOKEN']
            else:
                token = shell.get_dt1_token()
            add_token_to_docker_config(token)
            # update machine parameter
            parsed.machine = CLOUD_BUILDERS[parsed.arch]
            # update destination parameter
            if not parsed.destination:
                parsed.destination = DEFAULT_MACHINE
        # show info about project
        shell.include.devel.info.command(shell, args)
        project = DTProject(parsed.workdir)
        try:
            project_template_ver = int(project.type_version)
        except ValueError:
            project_template_ver = -1
        # add code labels
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.code.vcs=git"]
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.code.version.major={project.repository.branch}"]
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.code.repository={project.repository.name}"]
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.code.branch={project.repository.branch}"]
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.code.url={project.repository.repository_page}"]
        # add template labels
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.template.name={project.type}"]
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.template.version={project.type_version}"]
        # check if the index is clean
        if project.is_dirty():
            dtslogger.warning('Your index is not clean (some files are not committed).')
            dtslogger.warning('If you know what you are doing, use --force (-f) to ' +
                              'force the execution of the command.')
            if not parsed.force:
                exit(1)
            dtslogger.warning('Forced!')
        # in CI, we only build certain branches
        if parsed.ci and os.environ['DUCKIETOWN_CI_MAJOR'] != project.repository.branch:
            dtslogger.info(
                'CI is looking for the branch "{:s}", this is "{:s}". Nothing to do!'.format(
                    os.environ['DUCKIETOWN_CI_MAJOR'], project.repository.branch
                )
            )
            exit(0)
        # get info about docker endpoint
        dtslogger.info('Retrieving info about Docker endpoint...')
        epoint = _run_cmd([
            'docker',
            '-H=%s' % parsed.machine,
                'info',
                    '--format',
                    '{{json .}}'
        ], get_output=True, print_output=False)
        epoint = json.loads(epoint[0])
        if 'ServerErrors' in epoint:
            dtslogger.error('\n'.join(epoint['ServerErrors']))
            return
        epoint['MemTotal'] = _sizeof_fmt(epoint['MemTotal'])
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
            buildlabels += [
                '--label',
                f"{DOCKER_LABEL_DOMAIN}.code.launchers={','.join(sorted(launchers))}"
            ]
        # print info about multiarch
        msg = 'Building an image for {} on {}.'.format(parsed.arch, epoint['Architecture'])
        dtslogger.info(msg)
        # register bin_fmt in the target machine (if needed)
        if not parsed.no_multiarch:
            compatible_archs = BUILD_COMPATIBILITY_MAP[CANONICAL_ARCH[epoint['Architecture']]]
            if parsed.arch not in compatible_archs:
                dtslogger.info('Configuring machine for multiarch builds...')
                try:
                    _run_cmd([
                        'docker',
                            '-H=%s' % parsed.machine,
                            'run',
                                '--rm',
                                '--privileged',
                                'multiarch/qemu-user-static:register',
                                '--reset'
                    ], True)
                    dtslogger.info('Multiarch Enabled!')
                except:
                    msg = 'Multiarch cannot be enabled on the target machine. This might create issues.'
                    dtslogger.warning(msg)
            else:
                msg = 'Building an image for {} on {}. Multiarch not needed!'.format(parsed.arch, epoint['Architecture'])
                dtslogger.info(msg)
        # architecture target
        buildargs += ['--build-arg', 'ARCH={}'.format(parsed.arch)]
        # development base images
        if parsed.base_tag is not None:
            buildargs += ['--build-arg', 'MAJOR={}'.format(parsed.base_tag)]
        # loop mode (Experimental)
        if parsed.loop:
            buildargs += ['--build-arg', 'BASE_IMAGE={}'.format(project.repository.name)]
            buildargs += ['--build-arg', 'BASE_TAG={}-{}'.format(project.repository.branch, parsed.arch)]
            buildlabels += ['--label', f'{DOCKER_LABEL_DOMAIN}.image.loop=1']
            # ---
            msg = "WARNING: Experimental mode 'loop' is enabled!. Use with caution"
            dtslogger.warn(msg)
        if not parsed.no_cache:
            # check if the endpoint contains an image with the same name
            is_present = False
            try:
                _run_cmd([
                    'docker',
                        '-H=%s' % parsed.machine,
                        'image',
                        'inspect',
                            image
                ], get_output=True, suppress_errors=True)
                is_present = True
            except (RuntimeError, subprocess.CalledProcessError):
                pass
            if not is_present:
                # try to pull the same image so Docker can use it as cache source
                dtslogger.info('Pulling image "%s" to use as cache...' % image)
                try:
                    _run_cmd([
                        'docker',
                            '-H=%s' % parsed.machine,
                            'pull',
                                image
                    ], get_output=True, print_output=True, suppress_errors=True)
                except:
                    dtslogger.warning('An error occurred while pulling the image "%s", maybe the image does not exist' % image)
            else:
                dtslogger.info('Found an image with the same name. Using it as cache source.')

        # stamp image
        build_time = 'ND'
        if parsed.stamp:
            if project.is_dirty():
                dtslogger.warning('Your git index is not clean. You can\'t stamp an image built '
                                  'from a dirty index. The image will not be stamped.')
            else:
                # project is clean
                build_time = None
                local_sha = project.repository.sha
                # get remote image metadata
                try:
                    labels = project.image_labels(parsed.machine, parsed.arch, parsed.username)
                    time_label = f"{DOCKER_LABEL_DOMAIN}.time"
                    sha_label = f"{DOCKER_LABEL_DOMAIN}.code.sha"
                    if time_label in labels and sha_label in labels:
                        remote_time = labels[time_label]
                        remote_sha = labels[sha_label]
                        if remote_sha == local_sha:
                            # local and remote SHA match, reuse time
                            build_time = remote_time
                except BaseException:
                    dtslogger.warning('Cannot fetch image metadata.')
        # default build_time
        build_time = build_time or datetime.datetime.utcnow().isoformat()
        # add timestamp label
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.time={build_time}"]
        # add code SHA label (CI only)
        code_sha = project.repository.sha if (parsed.ci and project.is_clean()) else 'ND'
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.code.sha={code_sha}"]

        # build code
        buildlog = _run_cmd([
            'docker',
                '-H=%s' % parsed.machine,
                'build',
                    '--pull=%d' % int(parsed.pull),
                    '--no-cache=%d' % int(parsed.no_cache),
                    '-t', image] + \
                    buildlabels + \
                    buildargs + [
                    parsed.workdir
        ], True, True)

        # build code docs
        if parsed.docs:
            docs_args = ['--quiet'] * int(not parsed.verbose)
            # build docs
            dtslogger.info('Building documentation...')
            shell.include.devel.docs.build.command(shell, args + docs_args)

        # get image history
        historylog = _run_cmd([
            'docker',
                '-H=%s' % parsed.machine,
                'history',
                    '-H=false',
                    '--format',
                    '{{.ID}}:{{.Size}}',
                    image
        ], True)
        historylog = [l.split(':') for l in historylog if len(l.strip()) > 0]
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
            buildlog, historylog, codens=100, extra_info=extra_info
        )
        # pull image (if the destination is different from the builder machine)
        if parsed.cloud or (parsed.destination and parsed.machine != parsed.destination):
            _transfer_image(
                origin=parsed.machine,
                destination=parsed.destination,
                image=image,
                image_size=final_image_size
            )
        # perform docker login if on CI
        if parsed.ci:
            _run_cmd([
                'docker',
                '-H=%s' % parsed.destination,
                'login',
                '--username={:s}'.format(os.environ['DUCKIETOWN_CI_DOCKERHUB_USER']),
                '--password={:s}'.format(os.environ['DUCKIETOWN_CI_DOCKERHUB_TOKEN'])
            ])
        # perform push (if needed)
        if parsed.push:
            if not parsed.loop:
                push_args = parsed
                if parsed.cloud:
                    # the image was transferred to this machine, so we push from here
                    push_args = copy.deepcopy(parsed)
                    push_args.machine = parsed.destination
                # call devel/push
                shell.include.devel.push.command(shell, [], parsed=push_args)
            else:
                msg = "Forbidden: You cannot push an image when using the flag `--loop`."
                dtslogger.warn(msg)
        # perform remove (if needed)
        if parsed.rm:
            try:
                shell.include.devel.clean.command(shell, [], parsed=copy.deepcopy(parsed))
            except Exception:
                dtslogger.warn(
                    "We had some issues cleaning up the image on '{:s}'".format(
                        parsed.machine
                    ) + ". Just a heads up!"
                )

    @staticmethod
    def complete(shell, word, line):
        return []


def _transfer_image(origin, destination, image, image_size):
    monitor_info = '' if which('pv') else ' (install `pv` to see the progress)'
    dtslogger.info(f'Transferring image "{image}": [{origin}] -> [{destination}]{monitor_info}...')
    progress_monitor = ['|', 'pv', '-cN', 'image', '-s', image_size] if which('pv') else []
    _run_cmd([
        'docker',
            '-H=%s' % origin,
            'save',
                image \
        ] + progress_monitor + [\
        '|',
        'docker',
            '-H=%s' % destination,
            'load'
    ], print_output=False, shell=True)


def _run_cmd(cmd, get_output=False, print_output=False, suppress_errors=False, shell=False):
    dtslogger.debug('$ %s' % cmd)
    if shell:
        cmd = ' '.join([str(s) for s in cmd])
    if get_output:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=shell)
        p = re.compile(CATKIN_REGEX, re.IGNORECASE)
        lines = []
        last_matched = False
        for line in io.TextIOWrapper(proc.stdout, encoding="utf-8"):
            line = line.rstrip()
            if print_output:
                if last_matched:
                    sys.stdout.write("\033[F")
                sys.stdout.write(line + "\033[K" + "\n")
                sys.stdout.flush()
                last_matched = p.match(line.strip()) is not None
            if line:
                lines.append(line)
        proc.wait()
        if proc.returncode != 0:
            msg = 'The command {} returned exit code {}'.format(cmd, proc.returncode)
            if not suppress_errors:
                dtslogger.error(msg)
            raise RuntimeError(msg)
        return lines
    else:
        subprocess.check_call(cmd, shell=shell)


def _sizeof_fmt(num, suffix='B'):
    for unit in ['', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']:
        if abs(num) < 1024.0:
            return "%3.2f %s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.2f%s%s" % (num, 'Yi', suffix)


def add_token_to_docker_config(token):
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
