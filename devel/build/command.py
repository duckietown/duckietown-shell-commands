import os
import argparse
import subprocess
import io, sys
import getpass
from .image_analyzer import ImageAnalyzer
from dt_shell import DTCommandAbs, dtslogger

DEFAULT_ARCH='arm32v7'
DEFAULT_MACHINE='unix:///var/run/docker.sock'


class DTCommand(DTCommandAbs):

    help = 'Builds the current project'


    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('-C', '--workdir', default=None,
                            help="Directory containing the project to build")
        parser.add_argument('-a', '--arch', default=DEFAULT_ARCH,
                            help="Target architecture for the image to build")
        parser.add_argument('-H', '--machine', default=DEFAULT_MACHINE,
                            help="Docker socket or hostname where to build the image")
        parser.add_argument('--pull', default=False, action='store_true',
                            help="Whether to pull the latest base image used by the Dockerfile")
        parser.add_argument('--no-cache', default=False, action='store_true',
                            help="Whether to use the Docker cache")
        parser.add_argument('--no-multiarch', default=True, action='store_true',
                            help="Whether to disable multiarch support (based on bin_fmt)")
        parser.add_argument('-f', '--force', default=False, action='store_true',
                            help="Whether to force the build when the git index is not clean")
        parser.add_argument('--push', default=False, action='store_true',
                            help="Whether to push the resulting image")
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        code_dir = parsed.workdir if parsed.workdir else os.getcwd()
        dtslogger.info('Project workspace: {}'.format(code_dir))
        # show info about project
        shell.include.devel.info.command(shell, args)
        # get info about current repo
        repo_info = shell.include.devel.info.get_repo_info(code_dir)
        repo = repo_info['REPOSITORY']
        branch = repo_info['BRANCH']
        nmodified = repo_info['INDEX_NUM_MODIFIED']
        nadded = repo_info['INDEX_NUM_ADDED']
        # check if the index is clean
        if nmodified + nadded > 0:
            dtslogger.warning('Your index is not clean (some files are not committed).')
            dtslogger.warning('If you know what you are doing, use --force to force the execution of the command.')
            if not parsed.force:
                exit(1)
            dtslogger.warning('Forced!')
        # create defaults
        default_tag = "duckietown/%s:%s" % (repo, branch)
        tag = "duckietown/%s:%s-%s" % (repo, branch, parsed.arch)
        # register bin_fmt in the target machine (if needed)
        if not parsed.no_multiarch:
            _run_cmd([
                'docker',
                    '-H=%s' % parsed.machine,
                    'run',
                        '--rm',
                        '--privileged',
                        'multiarch/qemu-user-static:register',
                        '--reset'
            ])
        # build
        buildlog = _run_cmd([
            'docker',
                '-H=%s' % parsed.machine,
                'build',
                    '--pull=%d' % int(parsed.pull),
                    '--no-cache=%d' % int(parsed.no_cache),
                    '-t', tag,
                    '--build-arg', 'ARCH={}'.format(parsed.arch),
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
        ImageAnalyzer.process(buildlog, historylog, codens=100)
        # image tagging
        if parsed.arch == DEFAULT_ARCH:
            dtslogger.info("Tagging image {} as {}.".format(tag, default_tag))
            _run_cmd([
                'docker',
                    '-H=%s' % parsed.machine,
                    'tag',
                        tag,
                        default_tag
            ])
        # perform push (if needed)
        if parsed.push:
            shell.include.devel.push.command(shell, args)


    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(cmd, get_output=False, print_output=False):
    dtslogger.debug('$ %s' % cmd)
    if get_output:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        lines = []
        for line in io.TextIOWrapper(proc.stdout, encoding="utf-8"):
            line = line.rstrip()
            if print_output:
                print(line)
            if line:
                lines.append(line)
        proc.wait()
        if proc.returncode != 0:
            msg = 'The command {} returned exit code {}'.format(cmd, proc.returncode)
            dtslogger.error(msg)
            raise RuntimeError(msg)
        return lines
    else:
        subprocess.check_call(cmd)
