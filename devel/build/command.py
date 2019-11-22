import os
import re
import json
import argparse
import subprocess
import io, sys
import getpass
import itertools
from shutil import which
from .image_analyzer import ImageAnalyzer
from dt_shell import DTCommandAbs, dtslogger

DEFAULT_ARCH = 'arm32v7'
DEFAULT_MACHINE = 'unix:///var/run/docker.sock'
DOCKER_INFO = """
Docker Endpoint:
  Hostname: {Name}
  Operating System: {OperatingSystem}
  Kernel Version: {KernelVersion}
  OSType: {OSType}
  Architecture: {Architecture}
  Total Memory: {MemTotal}
  CPUs: {NCPU}
"""
ARCH_MAP = {
    'arm32v7' : ['arm', 'arm32v7', 'armv7l', 'armhf'],
    'amd64' : ['x64', 'x86_64', 'amd64', 'Intel 64'],
    'arm64v8' : ['arm64', 'arm64v8', 'armv8', 'aarch64']
}
CANONICAL_ARCH = {
    'arm' : 'arm32v7',
    'arm32v7' : 'arm32v7',
    'armv7l' : 'arm32v7',
    'armhf' : 'arm32v7',
    'x64' : 'amd64',
    'x86_64' : 'amd64',
    'amd64' : 'amd64',
    'Intel 64' : 'amd64',
    'arm64' : 'arm64v8',
    'arm64v8' : 'arm64v8',
    'armv8' : 'arm64v8',
    'aarch64' : 'arm64v8'
}
BUILD_COMPATIBILITY_MAP = {
    'arm32v7' : ['arm32v7'],
    'arm64v8' : ['arm32v7', 'arm64v8'],
    'amd64' : ['amd64']
}
CATKIN_REGEX = "^\[build (\d+\:)?\d+\.\d+ s\] \[\d+\/\d+ complete\] .*$"
DOCKER_LABEL_DOMAIN = "org.duckietown.label"
CLOUD_BUILDERS = {
    'arm32v7': 'ec2-54-174-175-117.compute-1.amazonaws.com',
    'arm64v8': 'ec2-54-174-175-117.compute-1.amazonaws.com'
}


class DTCommand(DTCommandAbs):

    help = 'Builds the current project'


    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('-C', '--workdir', default=None,
                            help="Directory containing the project to build")
        parser.add_argument('-a', '--arch', default=DEFAULT_ARCH, choices=set(CANONICAL_ARCH.values()),
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
                            help="Whether to remove the images once the build succeded (after pushing)")
        parser.add_argument('--loop', default=False, action='store_true',
                            help="(Experimental) Whether to reuse the same base image to speed up the build process")
        parser.add_argument('--ignore-watchtower', default=False, action='store_true',
                            help="Whether to ignore a running Docker watchtower")
        parser.add_argument('-u','--username',default="duckietown",
                            help="The docker registry username to tag the image with")
        parser.add_argument('-b', '--base-tag', default=None,
                            help="Docker tag for the base image. Used when the base image is a development version")
        parser.add_argument('--ci', default=False, action='store_true',
                            help="Overwrites configuration for CI (Continuous Integration) builds")
        parser.add_argument('--cloud', default=False, action='store_true',
                            help="Build the image on the cloud")
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        code_dir = parsed.workdir if parsed.workdir else os.getcwd()
        dtslogger.info('Project workspace: {}'.format(code_dir))
        # define labels / build-args
        buildlabels = []
        buildargs = []
        # CI builds
        if parsed.ci:
            parsed.pull = True
            parsed.no_multiarch = True
            buildlabels += ['--label', f'{DOCKER_LABEL_DOMAIN}.authoritative=1']
        # cloud build
        if parsed.cloud:
            if parsed.arch not in CLOUD_BUILDERS:
                dtslogger.error(f'No cloud machines found for target architecture {parsed.arch}. Aborting...')
                exit(3)
            # configure docker for DT
            token = shell.get_dt1_token()
            add_token_to_docker_config(token)
            # update machine parameter
            parsed.machine = CLOUD_BUILDERS[parsed.arch]
        # show info about project
        shell.include.devel.info.command(shell, args)
        project_info = shell.include.devel.info.get_project_info(code_dir)
        # get info about current repo
        repo_info = shell.include.devel.info.get_repo_info(code_dir)
        repo = repo_info['REPOSITORY']
        branch = repo_info['BRANCH']
        nmodified = repo_info['INDEX_NUM_MODIFIED']
        nadded = repo_info['INDEX_NUM_ADDED']
        # add code labels
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.code.vcs=git"]
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.code.repository={repo_info['REPOSITORY']}"]
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.code.branch={repo_info['BRANCH']}"]
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.code.url={repo_info['ORIGIN.HTTPS.URL']}"]
        # add template labels
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.template.name={project_info['TYPE']}"]
        buildlabels += ['--label', f"{DOCKER_LABEL_DOMAIN}.template.version={project_info['TYPE_VERSION']}"]
        # check if the index is clean
        if nmodified + nadded > 0:
            dtslogger.warning('Your index is not clean (some files are not committed).')
            dtslogger.warning('If you know what you are doing, use --force (-f) to force the execution of the command.')
            if not parsed.force:
                exit(1)
            dtslogger.warning('Forced!')
        # create defaults
        user = parsed.username
        default_tag = "%s/%s:%s" % (user, repo, branch)
        tag = "%s-%s" % (default_tag, parsed.arch)
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
        # check if there is a watchtower instance running on the endpoint
        if (not parsed.cloud) and (shell.include.devel.watchtower.is_running(parsed.machine)):
            w_machine = ''
            if parsed.machine != DEFAULT_MACHINE:
                w_machine = ' -H {}'.format(parsed.machine)
            dtslogger.warning('An instance of a Docker watchtower was found running on the Docker endpoint.')
            dtslogger.warning('Building new images next to an active watchtower might (sure it will) create race conditions.')
            dtslogger.warning('Solutions:')
            dtslogger.warning('  - Recommended: Use the command `dts devel watchtower stop{}` to stop the watchtower.'.format(w_machine))
            dtslogger.warning('  - NOT Recommended: Use the flag `--ignore-watchtower` to ignore this warning and continue.')
            if not parsed.ignore_watchtower:
                exit(2)
            dtslogger.warning('Ignored!')
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
            buildargs += ['--build-arg', 'BASE_IMAGE={}'.format(repo)]
            buildargs += ['--build-arg', 'BASE_TAG={}-{}'.format(branch, parsed.arch)]
            buildlabels += ['--label', 'LOOP=1']
            # ---
            msg = "WARNING: Experimental mode 'loop' is enabled!. Use with caution"
            dtslogger.warn(msg)
        if not parsed.no_cache:
            # check if the endpoint contains an image with the same name
            is_present = False
            try:
                out = _run_cmd([
                    'docker',
                        '-H=%s' % parsed.machine,
                        'images',
                            '--format',
                            "{{.Repository}}:{{.Tag}}"
                ], get_output=True, print_output=False, suppress_errors=True)
                is_present = tag in out
            except:
                pass
            if not is_present:
                # try to pull the same image so Docker can use it as cache source
                dtslogger.info('Pulling image "%s" to use as cache...' % tag)
                try:
                    _run_cmd([
                        'docker',
                            '-H=%s' % parsed.machine,
                            'pull',
                                tag
                    ], get_output=True, print_output=True, suppress_errors=True)
                except:
                    dtslogger.warning('An error occurred while pulling the image "%s", maybe the image does not exist' % tag)
            else:
                dtslogger.info('Found an image with the same name. Using it as cache source.')

        # build
        buildlog = _run_cmd([
            'docker',
                '-H=%s' % parsed.machine,
                'build',
                    '--pull=%d' % int(parsed.pull),
                    '--no-cache=%d' % int(parsed.no_cache),
                    '-t', tag] + \
                    buildlabels + \
                    buildargs + [
                    code_dir
        ], True, True)
        # get image history
        historylog = _run_cmd([
            'docker',
                '-H=%s' % parsed.machine,
                'history',
                    '-H=false',
                    '--format',
                    '{{.ID}}:{{.Size}}',
                    tag
        ], True)
        historylog = [l.split(':') for l in historylog if len(l.strip()) > 0]
        # run docker image analysis
        _, _, final_image_size = ImageAnalyzer.process(buildlog, historylog, codens=100)
        # pull image if built on the cloud
        if parsed.cloud:
            monitor_info = '' if which('pv') else ' (install `pv` to see the progress)'
            dtslogger.info(f'Fetching image from the cloud{monitor_info}...')
            progress_monitor = ['|', 'pv', '-cN', 'image', '-s', final_image_size] if which('pv') else []
            _run_cmd([
                'docker',
                    '-H=%s' % parsed.machine,
                    'save',
                        tag \
                ] + progress_monitor + [\
                '|',
                'docker',
                    'load'
            ], print_output=False, shell=True)
        # perform push (if needed)
        if parsed.push:
            if not parsed.loop:
                shell.include.devel.push.command(shell, args)
            else:
                msg = "Forbidden: You cannot push an image when using the experimental mode `--loop`."
                dtslogger.warn(msg)
        # perform remove (if needed)
        if parsed.rm:
            shell.include.devel.clean.command(shell, args)


    @staticmethod
    def complete(shell, word, line):
        return []


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
                matches = p.match(line.strip()) is not None
                if matches and last_matched:
                    sys.stdout.write("\033[F")
                sys.stdout.write(line + "\033[K" + "\n")
                sys.stdout.flush()
                last_matched = matches
            if line:
                lines.append(line)
        proc.wait()
        if proc.returncode != 0:
            if not suppress_errors:
                msg = 'The command {} returned exit code {}'.format(cmd, proc.returncode)
                dtslogger.error(msg)
            raise RuntimeError(msg)
        return lines
    else:
        subprocess.check_call(cmd, shell=shell)

def _sizeof_fmt(num, suffix='B'):
    for unit in ['','K','M','G','T','P','E','Z']:
        if abs(num) < 1024.0:
            return "%3.2f %s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.2f%s%s" % (num, 'Yi', suffix)

def add_token_to_docker_config(token):
    config_file = os.path.expanduser('~/.docker/config.json')
    config = json.load(open(config_file, 'r')) if os.path.exists(config_file) else {}
    if 'HttpHeaders' not in config:
        config['HttpHeaders'] = {}
    config['HttpHeaders']['X-Duckietown-Token'] = token
    json.dump(config, open(config_file, 'w'), indent=2)
