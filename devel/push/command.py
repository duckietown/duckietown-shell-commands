import os
import argparse
import subprocess
from dt_shell import DTCommandAbs, dtslogger

DEFAULT_ARCH='arm32v7'
DEFAULT_MACHINE='unix:///var/run/docker.sock'


class DTCommand(DTCommandAbs):

    help = 'Push the images relative to the current project'


    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('-C', '--workdir', default=None,
                            help="Directory containing the project to push")
        parser.add_argument('-a', '--arch', default=DEFAULT_ARCH,
                            help="Target architecture for the image to push")
        parser.add_argument('-H', '--machine', default=DEFAULT_MACHINE,
                            help="Docker socket or hostname from where to push the image")
        parser.add_argument('-f', '--force', default=False, action='store_true',
                            help="Whether to force the push when the git index is not clean")
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
        _run_cmd(["docker", "-H=%s" % parsed.machine, "push", tag])

        dtslogger.info("Creating manifest {}...".format(default_tag))
        _run_cmd(["docker", "-H=%s" % parsed.machine, "manifest", "create", default_tag, "--amend", tag])
        _run_cmd(["docker", "-H=%s" % parsed.machine, "manifest", "push", default_tag])
        # tags = [tag] + ([default_tag] if parsed.arch == DEFAULT_ARCH else [])
        # for t in tags:
        #     # push image
        #     dtslogger.info("Pushing image {}...".format(t))
        #     _run_cmd(["docker", "-H=%s" % parsed.machine, "push", t])


    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(cmd):
    dtslogger.debug('$ %s' % cmd)
    subprocess.check_call(cmd)
