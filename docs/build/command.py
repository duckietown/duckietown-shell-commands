import getpass
import os
import subprocess
import sys

from dt_shell import DTCommandAbs
from dt_shell.env_checks import check_docker_environment, InvalidEnvironment

image = 'andreacensi/mcdp_books:duckuments@sha256:5e149f33837f999e0aa5233a77f8610baf3c3fc1a2f1bfb500756b427cf52dbe'


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        check_docker_environment()
        # check_git_supports_superproject()

        from system_cmd import system_cmd_result

        pwd = os.getcwd()
        bookdir = os.path.join(pwd, 'book')

        if not os.path.exists(bookdir):
            msg = 'Could not find "book" directory %r.' % bookdir
            DTCommandAbs.fail(msg)

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

        res = system_cmd_result(pwd, ['git', '--version'],
                                raise_on_error=True)
        git_version = res.stdout
        print('git version: %s' % git_version)

        res = system_cmd_result(pwd, ['git', 'rev-parse', '--show-superproject-working-tree'],
                                raise_on_error=True)
        if '--show' in res.stdout:
            msg = "Your git version is too low, as it does not support --show-superproject-working-tree"
            msg += '\n\nDetected: %s' % git_version
            raise InvalidEnvironment(msg)

        gitdir_super = res.stdout

        print('gitdir_super: %r' % gitdir_super)
        res = system_cmd_result(pwd, ['git', 'rev-parse', '--show-toplevel'],
                                raise_on_error=True)
        gitdir = res.stdout

        if '--show' in res.stdout:
            msg = "Your git version is too low, as it does not support --show-toplevel"
            msg += '\n\nDetected: %s' % git_version
            raise InvalidEnvironment(msg)

        print('gitdir: %r' % gitdir)

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

        cmd = ['docker', 'run',
               '-v', '%s:%s%s' % (gitdir, gitdir, flag),
               '-v', '%s:%s%s' % (gitdir_super, gitdir_super, flag),
               '-v', '%s:%s%s' % (pwd1, pwd1, flag),
               '-v', '%s:%s%s' % (fake_home, '/home/%s' % user, flag),
               '-e', 'USER=%s' % user,
               '-e', 'USERID=%s' % uid1,
               '--user', '%s' % uid1]

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

        print('executing:\nls ' + " ".join(cmd))
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

        # mkdir - p / tmp / fake -$(USER) - home
        # 	docker run \
        # 		-v $(gitdir):$(gitdir) \
        # 		-v $(gitdir_super):$(gitdir_super) \
        # 		-v $(pwd1):$(pwd1) \
        # 		-v /tmp/fake-$(USER)-home:/home/$(USER) \
        # 		-e USER=$(USER) -e USERID=$(uid1) --user $(uid1) \
        # 		-e COLUMNS=$(cols)\
        # 		-ti \
        # 		"$(IMAGE)" \
        # 		/project/run-book-native.sh \
        # 		"$(BOOKNAME)" "$(SRC)" "$(RESOURCES)" \
        # 		"$(pwd1)"
        #

        print('\n\nCompleted.')
#
#
#
# IMAGE?=andreacensi/mcdp_books:duckuments
#
# clean:
# 	rm -rf out duckuments-dist
#
# update-resources:
# 	echo
# 	# git submodule sync --recursive
# 	# git submodule update --init --recursive
#
# THIS_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
#
# compile-native: update-resources
# 	$(THIS_DIR)/../scripts/run-book-native.sh "$(BOOKNAME)" "$(SRC)" "$(RESOURCES)" "$(PWD)"
#
# gitdir_super:=$(shell git rev-parse --show-superproject-working-tree)
# gitdir:=$(shell git rev-parse --show-toplevel)
# pwd1:=$(shell realpath $(PWD))
# uid1:=$(shell id -u)
# cols:=$(shell tput cols)
#
# compile-docker: update-resources
# 	# docker pull $(IMAGE)
# 	echo gitdir = $(gitdir)
# 	echo gitdir_super = $(gitdir_super)
# 	mkdir -p /tmp/fake-$(USER)-home
# 	docker run \
# 		-v $(gitdir):$(gitdir) \
# 		-v $(gitdir_super):$(gitdir_super) \
# 		-v $(pwd1):$(pwd1) \
# 		-v /tmp/fake-$(USER)-home:/home/$(USER) \
# 		-e USER=$(USER) -e USERID=$(uid1) --user $(uid1) \
# 		-e COLUMNS=$(cols)\
# 		-ti \
# 		"$(IMAGE)" \
# 		/project/run-book-native.sh \
# 		"$(BOOKNAME)" "$(SRC)" "$(RESOURCES)" \
# 		"$(pwd1)"
#
