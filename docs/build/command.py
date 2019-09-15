import argparse
import getpass
import os
import subprocess
import sys

from dt_shell import DTCommandAbs, dtslogger, UserError
from dt_shell.env_checks import check_docker_environment, InvalidEnvironment
from utils.docker_utils import pull_image

# image = 'andreacensi/mcdp_books:duckuments@sha256:5e149f33837f999e0aa5233a77f8610baf3c3fc1a2f1bfb500756b427cf52dbe'
# image = 'andreacensi/mcdp_books:duckuments@sha256:ecc502de748fa936f4420980b2fa9f255250400bce32c9b20ad4d6d7bfc49ccf'
# ok
# image = 'andreacensi/mcdp_books:duckuments@sha256:ae2fcdbb8ce409e4817ed74c67b04bb91cd14ca96bed887e75e5275fa2efc933'
# IMAGE = 'andreacensi/mcdp_books:duckuments@sha256:ae2fcdbb8ce409e4817ed74c67b04bb91cd14ca96bed887e75e5275fa2efc933'
# IMAGE = 'andreacensi/mcdp_books:duckuments-master19'
IMAGE = 'andreacensi/mcdp_books:daffy'


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):

        parser = argparse.ArgumentParser()

        parser.add_argument('--image',
                            default=IMAGE,
                            help="Which image to use")

        parsed = parser.parse_args(args=args)
        image = parsed.image

        check_docker_environment()

        pwd = os.getcwd()
        bookdir = os.path.join(pwd, 'book')

        if not os.path.exists(bookdir):
            msg = 'Could not find "book" directory %r.' % bookdir
            raise UserError(msg)

        # check that the resources directory is present

        resources = os.path.join(pwd, 'resources')
        if not os.path.exists(os.path.join(resources, 'templates')):
            msg = 'It looks like that the "resources" repo is not checked out.'
            msg += '\nMaybe try:\n'
            msg += '\n   git submodule init'
            msg += '\n   git submodule update'
            raise Exception(msg)  # XXX

        entries = list(os.listdir(bookdir))
        entries = [_ for _ in entries if not _[0] == '.']
        if len(entries) > 1:
            msg = 'Found more than one directory in "book": %s' % entries
            DTCommandAbs.fail(msg)
        bookname = entries[0]
        src = os.path.join(bookdir, bookname)

        pull_image(image)

        git_version = system_cmd_result(pwd, ['git', '--version']).strip()
        dtslogger.debug('git version: %s' % git_version)

        cmd = ['git', 'rev-parse', '--show-superproject-working-tree']
        gitdir_super = system_cmd_result(pwd, cmd).strip()

        dtslogger.debug('gitdir_super: %r' % gitdir_super)
        gitdir = system_cmd_result(pwd, ['git', 'rev-parse', '--show-toplevel']).strip()

        dtslogger.debug('gitdir: %r' % gitdir)

        if '--show' in gitdir_super:  # or not gitdir_super:
            msg = "Your git version is too low, as it does not support --show-superproject-working-tree"
            msg += '\n\nDetected: %s' % git_version
            raise InvalidEnvironment(msg)

        if '--show' in gitdir or not gitdir:
            msg = "Your git version is too low, as it does not support --show-toplevel"
            msg += '\n\nDetected: %s' % git_version
            raise InvalidEnvironment(msg)

        pwd1 = os.path.realpath(pwd)
        user = getpass.getuser()

        tmpdir = '/tmp'
        fake_home = os.path.join(tmpdir, 'fake-%s-home' % user)
        if not os.path.exists(fake_home):
            os.makedirs(fake_home)
        resources = 'resources'
        uid1 = os.getuid()

        if sys.platform == 'darwin':
            flag = ':delegated'
        else:
            flag = ''

        cache = '/tmp/cache'
        if not os.path.exists(cache):
            os.makedirs(cache)

        cmd = ['docker', 'run',
               
               '-v', '%s:%s%s' % (gitdir, gitdir, flag),
               '-v', '%s:%s%s' % (pwd1, pwd1, flag),
               '-v', '%s:%s%s' % (cache, cache, flag),
               '-v', '%s:%s%s' % (fake_home, '/home/%s' % user, flag),
               '-e', 'USER=%s' % user,
               '-e', 'USERID=%s' % uid1,
               '-m', '4GB',
               '--user', '%s' % uid1]

        if gitdir_super:
            cmd += ['-v', '%s:%s%s' % (gitdir_super, gitdir_super, flag)]

        interactive = True

        if interactive:
            cmd.append('-it')

        cmd += [
            image,
            '/project/run-book-native.sh',
            bookname,
            src,
            resources,
            pwd1
        ]

        dtslogger.info('executing:\nls ' + " ".join(cmd))
        # res = system_cmd_result(pwd, cmd, raise_on_error=True)

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
