from __future__ import unicode_literals

import argparse
import getpass
import os
import subprocess
import sys

from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError
from dt_shell.env_checks import check_docker_environment, InvalidEnvironment



class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args):

        parser = argparse.ArgumentParser()

        parser.add_argument('--image',
                            default='duckietown/docs-build:daffy',
                            help="Which image to use")

        parsed = parser.parse_args(args=args)
        image = parsed.image

        check_docker_environment()

        pwd = os.getcwd()
        # bookdir = os.path.join(pwd, 'book')
        #
        # if not os.path.exists(bookdir):
        #     msg = 'Could not find "book" directory %r.' % bookdir
        #     raise UserError(msg)

        # check that the resources directory is present

        # resources = os.path.join(pwd, 'resources')
        # if not os.path.exists(os.path.join(resources, 'templates')):
        #     msg = 'It looks like that the "resources" repo is not checked out.'
        #     msg += '\nMaybe try:\n'
        #     msg += '\n   git submodule init'
        #     msg += '\n   git submodule update'
        #     raise Exception(msg)  # XXX

        # entries = list(os.listdir(bookdir))
        # entries = [_ for _ in entries if not _[0] == '.']
        # if len(entries) > 1:
        #     msg = 'Found more than one directory in "book": %s' % entries
        #     DTCommandAbs.fail(msg)
        # bookname = entries[0]
        # src = os.path.join(bookdir, bookname)
        #
        # git_version = system_cmd_result(pwd, ['git', '--version']).strip()
        # dtslogger.debug('git version: %s' % git_version)

        # cmd = ['git', 'rev-parse', '--show-superproject-working-tree']
        # gitdir_super = system_cmd_result(pwd, cmd).strip()

        # dtslogger.debug('gitdir_super: %r' % gitdir_super)
        # gitdir = system_cmd_result(pwd, ['git', 'rev-parse', '--show-toplevel']).strip()
        #
        # dtslogger.debug('gitdir: %r' % gitdir)

        # if '--show' in gitdir_super:  # or not gitdir_super:
        #     msg = "Your git version is too low, as it does not support --show-superproject-working-tree"
        #     msg += '\n\nDetected: %s' % git_version
        #     raise InvalidEnvironment(msg)
        #
        # if '--show' in gitdir or not gitdir:
        #     msg = "Your git version is too low, as it does not support --show-toplevel"
        #     msg += '\n\nDetected: %s' % git_version
        #     raise InvalidEnvironment(msg)

        pwd1 = os.path.realpath(pwd)
        user = getpass.getuser()

        # tmpdir = '/tmp'
        # fake_home = os.path.join(tmpdir, 'fake-%s-home' % user)
        # if not os.path.exists(fake_home):
        #     os.makedirs(fake_home)
        uid1 = os.getuid()

        if sys.platform == 'darwin':
            flag = ':delegated'
        else:
            flag = ''

        cache = '/tmp/cache'
        if not os.path.exists(cache):
            os.makedirs(cache)

        total_mem_bytes = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')  # e.g. 4015976448
        total_mem_gib = int(total_mem_bytes/(1024.**3))  # e.g. 3.74
        constrain_memory = (total_mem_gib-2) if (total_mem_gib-2)>4 else 4
        memory_set = ""+str(constrain_memory)+"GB"

        cmd = ['docker', 'run',
               '-e', 'USER=%s' % user,
               '-e', 'USERID=%s' % uid1,
               '-m', memory_set,
               '--user', '%s' % uid1,
               '-e', 'COMPMAKE_COMMAND=rparmake',
               '-it', '-v', f'{pwd1}:/pwd{flag}', '--workdir', '/pwd', image]

        dtslogger.info('executing:\nls ' + " ".join(cmd))

        try:
            p = subprocess.Popen(cmd, bufsize=0, executable=None, stdin=None, stdout=None, stderr=None, preexec_fn=None,
                                 shell=False, cwd=pwd, env=None)
        except OSError as e:
            if e.errno == 2:
                msg = 'Could not find "docker" executable.'
                DTCommandAbs.fail(msg)
            raise

        p.communicate()
        dtslogger.info('\n\nCompleted.')


def system_cmd_result(pwd, cmd):
    s = subprocess.check_output(cmd, cwd=pwd)
    return s.decode('utf-8')
