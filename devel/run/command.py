import os
import json
import shutil
import argparse
import subprocess
from dt_shell import DTCommandAbs, dtslogger
from utils.networking_utils import get_duckiebot_ip
from utils.docker_utils import default_env


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
    'arm32v7': ['arm', 'arm32v7', 'armv7l', 'armhf'],
    'amd64': ['x64', 'x86_64', 'amd64', 'Intel 64'],
    'arm64v8': ['arm64', 'arm64v8', 'armv8', 'aarch64']
}
CANONICAL_ARCH = {
    'arm': 'arm32v7',
    'arm32v7': 'arm32v7',
    'armv7l': 'arm32v7',
    'armhf': 'arm32v7',
    'x64': 'amd64',
    'x86_64': 'amd64',
    'amd64': 'amd64',
    'Intel 64': 'amd64',
    'arm64': 'arm64v8',
    'arm64v8': 'arm64v8',
    'armv8': 'arm64v8',
    'aarch64': 'arm64v8'
}
ARCH_COMPATIBILITY_MAP = {
    'arm32v7': ['arm32v7'],
    'arm64v8': ['arm32v7', 'arm64v8'],
    'amd64': ['amd64']
}
DOCKER_LABEL_DOMAIN = "org.duckietown.label"
TEMPLATE_TO_SRC = {
    'template-basic': {
        '1': lambda repo: ('code', '/packages/{:s}/'.format(repo))
    },
    'template-ros': {
        '1': lambda repo: ('', '/code/catkin_ws/src/{:s}/'.format(repo))
    }
}
TEMPLATE_TO_LAUNCHFILE = {
    'template-basic': {
        '1': lambda repo: ('launch.sh', '/launch/{:s}/launch.sh'.format(repo))
    },
    'template-ros': {
        '1': lambda repo: ('launch.sh', '/launch/{:s}/launch.sh'.format(repo))
    }
}
DEFAULT_VOLUMES = [
    '/var/run/avahi-daemon/socket'
]


class DTCommand(DTCommandAbs):

    help = 'Runs the current project'

    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('-C', '--workdir', default=os.getcwd(),
                            help="Directory containing the project to run")
        parser.add_argument('-a', '--arch', default=DEFAULT_ARCH, choices=set(CANONICAL_ARCH.values()),
                            help="Target architecture for the image to run")
        parser.add_argument('-H', '--machine', default=DEFAULT_MACHINE,
                            help="Docker socket or hostname where to run the image")
        parser.add_argument('-n', '--name', default=None,
                            help="Name of the container")
        parser.add_argument('--cmd', default=None,
                            help="Command to run in the Docker container")
        parser.add_argument('--pull', default=False, action='store_true',
                            help="Whether to pull the image of the project")
        parser.add_argument('--force-pull', default=False, action='store_true',
                            help="Whether to force pull the image of the project")
        parser.add_argument('--duckiebot', default=None,
                            help="specify which duckiebot to interface to")
        parser.add_argument('--build', default=False, action='store_true',
                            help="Whether to build the image of the project")
        parser.add_argument('--no-multiarch', default=False, action='store_true',
                            help="Whether to disable multiarch support (based on bin_fmt)")
        parser.add_argument('-f', '--force', default=False, action='store_true',
                            help="Whether to force the run when the git index is not clean")
        parser.add_argument('-M', '--mount', default=False, const=True, action='store',
                            nargs='?', type=str,
                            help="Whether to mount the current project into the container. "
                                 "Pass a comma-separated list of paths to mount multiple projects")
        parser.add_argument('-u', '--username', default="duckietown",
                            help="The docker registry username that owns the Docker image")
        parser.add_argument('--rm', default=True, action='store_true',
                            help="Whether to remove the container once done")
        parser.add_argument('--loop', default=False, action='store_true',
                            help="(Experimental) Whether to run the LOOP image")
        parser.add_argument('-A', '--argument', dest='arguments', default=[], action='append',
                            help="Arguments for the container command")
        parser.add_argument('--runtime', default='docker', type=str,
                            help="Docker runtime to use to run the container")
        parser.add_argument('-X', dest='use_x_docker', default=False, action='store_true',
                            help="Use x-docker as runtime (needs to be installed separately)")
        parser.add_argument('docker_args', nargs='*', default=[])
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        # x-docker runtime
        if parsed.use_x_docker:
            parsed.runtime = 'x-docker'
        # check runtime
        if shutil.which(parsed.runtime) is None:
            raise ValueError('Docker runtime binary "{}" not found!'.format(parsed.runtime))
        # ---
        dtslogger.info('Project workspace: {}'.format(parsed.workdir))
        # show info about project
        shell.include.devel.info.command(shell, args)
        # get info about current repo
        repo_info = shell.include.devel.info.get_repo_info(parsed.workdir)
        repo = repo_info['REPOSITORY']
        branch = repo_info['BRANCH']
        nmodified = repo_info['INDEX_NUM_MODIFIED']
        nadded = repo_info['INDEX_NUM_ADDED']
        # parse arguments
        mount_code = parsed.mount is True or isinstance(parsed.mount, str)
        mount_option = []
        if mount_code:
            projects_to_mount = []
            # (always) mount current project
            projects_to_mount.append(parsed.workdir)
            # mount secondary projects
            if isinstance(parsed.mount, str):
                projects_to_mount.extend([
                    os.path.join(os.getcwd(), p.strip()) for p in parsed.mount.split(',')
                ])
            # create mount points definitions
            for project_path in projects_to_mount:
                # make sure that the project exists
                if not os.path.isdir(project_path):
                    dtslogger.error(
                        'The path "{:s}" is not a Duckietown project'.format(project_path)
                    )
                # get project info
                project = shell.include.devel.info.get_project_info(project_path)
                template = project['TYPE']
                template_v = project['TYPE_VERSION']
                # make sure we support this project version
                if template not in TEMPLATE_TO_SRC or \
                        template_v not in TEMPLATE_TO_SRC[template] or \
                        template not in TEMPLATE_TO_LAUNCHFILE or \
                        template_v not in TEMPLATE_TO_LAUNCHFILE[template]:
                    dtslogger.error(
                        'Template {:s} v{:s} for project {:s} is not supported'.format(
                            template, template_v, project_path
                        )
                    )
                    exit(2)
                # get project repo info
                project_repo_info = shell.include.devel.info.get_repo_info(project_path)
                project_repo = project_repo_info['REPOSITORY']
                # create mountpoints
                local_src, destination_src = \
                    TEMPLATE_TO_SRC[template][template_v](project_repo)
                local_launch, destination_launch = \
                    TEMPLATE_TO_LAUNCHFILE[template][template_v](project_repo)
                mount_option += [
                    '-v', '{:s}:{:s}'.format(
                        os.path.join(project_path, local_src),
                        destination_src
                    ),
                    '-v', '{:s}:{:s}'.format(
                        os.path.join(project_path, local_launch),
                        destination_launch
                    )
                ]
        # check if the index is clean
        if parsed.mount and nmodified + nadded > 0:
            dtslogger.warning('Your index is not clean (some files are not committed).')
            dtslogger.warning('If you know what you are doing, use --force (-f) to force '
                              'the execution of the command.')
            if not parsed.force:
                exit(1)
            dtslogger.warning('Forced!')
        # volumes
        mount_option += [
            '--volume=%s:%s' % (v, v) for v in DEFAULT_VOLUMES
            if os.path.exists(v)
        ]
        # loop mode (Experimental)
        loop_tag = '' if not parsed.loop else 'LOOP-'
        # create image name
        image = "%s/%s:%s-%s%s" % (parsed.username, repo, branch, loop_tag, parsed.arch)
        # get info about docker endpoint
        dtslogger.info('Retrieving info about Docker endpoint...')
        epoint = _run_cmd([
            'docker',
                '-H=%s' % parsed.machine,
                'info',
                    '--format',
                    '{{json .}}'
        ], get_output=True, print_output=False)
        epoint = json.loads(epoint)
        if 'ServerErrors' in epoint:
            dtslogger.error('\n'.join(epoint['ServerErrors']))
            return
        epoint['MemTotal'] = _sizeof_fmt(epoint['MemTotal'])
        print(DOCKER_INFO.format(**epoint))
        # print info about multiarch
        msg = 'Running an image for {} on {}.'.format(parsed.arch, epoint['Architecture'])
        dtslogger.info(msg)
        # register bin_fmt in the target machine (if needed)
        if not parsed.no_multiarch:
            compatible_archs = ARCH_COMPATIBILITY_MAP[CANONICAL_ARCH[epoint['Architecture']]]
            if parsed.arch not in compatible_archs:
                dtslogger.info('Configuring machine for multiarch...')
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
                msg = 'Running an image for {} on {}. Multiarch not needed!'.format(parsed.arch, epoint['Architecture'])
                dtslogger.info(msg)
        # pulling image (if requested)
        if parsed.pull or parsed.force_pull:
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
                is_present = image in out
            except:
                pass
            if not is_present or parsed.force_pull:
                # try to pull the image
                dtslogger.info('Pulling image "%s"...' % image)
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
                dtslogger.info('Found an image with the same name. Using it. User --force-pull to force a new pull.')
        # cmd option
        cmd_option = [] if not parsed.cmd else [parsed.cmd]
        cmd_arguments = [] if not parsed.arguments else \
            ['--'] + list(map(lambda s: '--%s' % s, parsed.arguments))
        # docker arguments
        if not parsed.docker_args:
            parsed.docker_args = []
        if parsed.rm:
            parsed.docker_args += ['--rm']
        if parsed.duckiebot is not None:
            parsed.docker_args += setup_duckiebot_env_vars(parsed.duckiebot)
        # container name
        if not parsed.name:
            parsed.name = 'dts-run-{:s}'.format(repo)
        parsed.docker_args += ['--name', parsed.name]
        # escape spaces in arguments
        parsed.docker_args = [a.replace(' ', '\\ ') for a in parsed.docker_args]
        # run
        _run_cmd([
            parsed.runtime,
                '-H=%s' % parsed.machine,
                'run', '-it'] +
                    parsed.docker_args +
                    mount_option +
                    [image] +
                    cmd_option +
                    cmd_arguments
            , suppress_errors=True
        )

    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(cmd, get_output=False, print_output=False, suppress_errors=False, shell=False):
    if shell:
        cmd = ' '.join([str(s) for s in cmd])
    dtslogger.debug('$ %s' % cmd)
    if get_output:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=shell)
        proc.wait()
        if proc.returncode != 0:
            if not suppress_errors:
                msg = 'The command {} returned exit code {}'.format(cmd, proc.returncode)
                dtslogger.error(msg)
            raise RuntimeError(msg)
        out = proc.stdout.read().decode('utf-8').rstrip()
        if print_output:
            print(out)
        return out
    else:
        try:
            subprocess.check_call(cmd, shell=shell)
        except subprocess.CalledProcessError as e:
            if not suppress_errors:
                raise e


def _sizeof_fmt(num, suffix='B'):
    for unit in ['', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']:
        if abs(num) < 1024.0:
            return "%3.2f %s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.2f%s%s" % (num, 'Yi', suffix)

def setup_duckiebot_env_vars(db_name):
    db_ip = get_duckiebot_ip(db_name)
    env_vars = default_env(db_name, db_ip)
    env_vars.update({
        "VEHICLE_NAME": db_name,
        "VEHICLE_IP": db_ip
    })
    env_vars_string = []
    for var in env_vars:
        env_vars_string += ['--env']
        env_vars_string += ['%s=%s' % (var, env_vars[var])]
    return env_vars_string