import os
import argparse
import subprocess
from dt_shell import DTCommandAbs, dtslogger

DEFAULT_ARCH='arm32v7'
DEFAULT_MACHINE='unix:///var/run/docker.sock'


class DTCommand(DTCommandAbs):

    help = 'Removes the Docker images relative to the current project'


    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('-C', '--workdir', default=None,
                            help="Directory containing the project to clean")
        parser.add_argument('-a', '--arch', default=DEFAULT_ARCH,
                            help="Target architecture for the image to clean")
        parser.add_argument('-H', '--machine', default=DEFAULT_MACHINE,
                            help="Docker socket or hostname where to clean the image")
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
        # create defaults
        default_tag = "duckietown/%s:%s" % (repo, branch)
        tag = "%s-%s" % (default_tag, parsed.arch)
        tags = [tag] + ([default_tag] if parsed.arch == DEFAULT_ARCH else [])
        # remove images
        for t in tags:
            dtslogger.info("Removing image {}...".format(t))
            _run_cmd([
                'docker',
                    '-H=%s' % parsed.machine,
                    'rmi',
                        t
            ])

    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(cmd):
    dtslogger.debug('$ %s' % cmd)
    subprocess.check_call(cmd)
