import getpass
import os
import subprocess

from dt_shell import DTCommandAbs
from dt_shell.env_checks import check_docker_environment


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        check_docker_environment()

        from system_cmd import system_cmd_result

        pwd = os.getcwd()
        bookdir = os.path.join(pwd, 'book')

        if not os.path.exists(bookdir):
            msg = 'Could not find "book" directory %r.' % bookdir
            DTCommandAbs.fail(msg)

        entries = list(os.listdir(bookdir))
        entries = [_ for _ in entries if not _[0] == '.']
        if len(entries) > 1:
            msg = 'Found more than one directory in "book": %s' % entries
            DTCommandAbs.fail(msg)
        bookname = entries[0]
        src = os.path.join(bookdir, bookname)

        # gitdir_super:=$(shell git rev-parse --show-superproject-working-tree)
        # gitdir:=$(shell git rev-parse --show-toplevel)

        res = system_cmd_result(pwd, ['git', 'rev-parse', '--show-superproject-working-tree'],
                                raise_on_error=True)
        gitdir_super = res.stdout

        res = system_cmd_result(pwd, ['git', 'rev-parse', '--show-toplevel'],
                                raise_on_error=True)
        gitdir = res.stdout

        # gitdir0 = os.path.join(pwd, '.git')
        # if os.path.exists(gitdir0):
        #     gitdir_super = gitdir0
        #     gitdir = gitdir0
        # else:
        #     msg = 'Cannot work with this directory structure - %r' % gitdir0
        #     DTCommandAbs.fail(msg)

        # res = system_cmd_result(pwd, ['tput', 'cols'], raise_on_error=True)
        # cols = res.stdout
        pwd1 = os.path.realpath(pwd)
        user = getpass.getuser()

        tmpdir = '/tmp'
        fake_home = os.path.join(tmpdir, 'fake-%s-home' % user)
        if not os.path.exists(fake_home):
            os.makedirs(fake_home)

        resources = 'resources'
        image = 'andreacensi/mcdp_books:duckuments'
        uid1 = os.getuid()

        cmd = ['docker', 'run',
               '-v', '%s:%s' % (gitdir, gitdir),
               '-v', '%s:%s' % (gitdir_super, gitdir_super),
               '-v', '%s:%s' % (pwd1, pwd1),
               '-v', '%s:%s' % (fake_home, '/home/%s' % user),
               '-e', 'USER=%s' % user,
               '-e', 'USERID=%s' % uid1,
               '--user', '%s' % uid1,
               '-i',
               image,
               '/project/run-book-native.sh',
               bookname,
               src,
               resources,
               pwd1
               ]

        print('executing: ' + "\n".join(cmd))
        # res = system_cmd_result(pwd, cmd, raise_on_error=True)

        try:
            p = subprocess.Popen(cmd, bufsize=0, executable=None, stdin=None, stdout=None, stderr=None, preexec_fn=None,
                                 shell=False, cwd=pwd, env=None)
        except OSError as e:
            if e.errno == 2:
                msg = 'Could not find "docker" executable.'
                DTCommandAbs.fail(msg)

        p.wait()

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

        print('hello')
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
