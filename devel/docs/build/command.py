import argparse
import os
import sys
import string
import random
import docker
import tarfile
import io
import pathlib

from dt_shell import DTCommandAbs, dtslogger

from utils.docker_utils import get_endpoint_architecture, build_logs_to_string
from utils.cli_utils import start_command_in_subprocess
from utils.dtproject_utils import DTProject


class DTCommand(DTCommandAbs):
    help = 'Builds the current project\'s documentation'

    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('-C', '--workdir', default=os.getcwd(),
                            help="Directory containing the project to build")
        parser.add_argument('-f', '--force', default=False, action='store_true',
                            help="Whether to force the build when the git index is not clean")
        parser.add_argument('-u', '--username', default="duckietown",
                            help="The docker registry username to tag the image with")
        parser.add_argument('--no-cache', default=False, action='store_true',
                            help="Whether to use the Docker cache")
        parser.add_argument('--push', default=False, action='store_true',
                            help="Whether to push the resulting documentation")
        parser.add_argument('--loop', default=False, action='store_true',
                            help="(Developers only) Reuse the same base image, speed up the build")
        parser.add_argument('--ci', default=False, action='store_true',
                            help="Overwrites configuration for CI (Continuous Integration) builds")
        parser.add_argument('--quiet', default=False, action='store_true',
                            help="Suppress any building log")
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        parsed.workdir = os.path.abspath(parsed.workdir)
        dtslogger.info('Project workspace: {}'.format(parsed.workdir))
        # CI builds
        if parsed.ci:
            parsed.pull = True
            parsed.cloud = True
            parsed.no_multiarch = True
            parsed.push = True
            parsed.rm = True
            # check that the env variables are set
            for key in ['DISTRO', 'DT_TOKEN']:
                if 'DUCKIETOWN_CI_' + key not in os.environ:
                    dtslogger.error(
                        'Variable DUCKIETOWN_CI_{:s} required when building with --ci'.format(key)
                    )
                    sys.exit(5)
        # show info about project
        if not parsed.quiet:
            shell.include.devel.info.command(shell, args)
        project = DTProject(parsed.workdir)
        # check if the index is clean
        if project.is_dirty():
            dtslogger.warning('Your index is not clean (some files are not committed).')
            dtslogger.warning('If you know what you are doing, use --force (-f) to ' +
                              'force the build.')
            if not parsed.force:
                exit(1)
            dtslogger.warning('Forced!')

        # get the arch
        arch = get_endpoint_architecture()

        # create defaults
        image = project.image(arch, loop=parsed.loop, owner=parsed.username)
        # image_docs = project.image(arch, loop=parsed.loop, docs=True, owner=parsed.username)

        # file locators
        repo_file = lambda *p: os.path.join(parsed.workdir, *p)
        docs_file = lambda *p: os.path.join(repo_file('docs'), *p)

        # check if folders and files exist
        dtslogger.info("Checking if the documentation files are in order...")
        for f in ['', 'config.yaml', 'index.rst']:
            if not os.path.exists(docs_file(f)):
                dtslogger.error(f"File {docs_file(f)} not found. Aborting.")
                exit(1)
        dtslogger.info("Done!")

        # Get a docker client
        dclient = docker.from_env()

        # build and run the docs container
        dtslogger.info("Building the documentation environment...")
        cmd_dir = os.path.dirname(os.path.abspath(__file__))
        # dockerfile = os.path.join(cmd_dir, 'Dockerfile')
        docs_image, logs = dclient.images.build(
            path=cmd_dir,
            buildargs={'BASE_IMAGE': image},
            nocache=parsed.no_cache )
        print(build_logs_to_string(logs))
        dtslogger.info("Done!")

        # clear output directories
        for f in os.listdir(repo_file(repo_file('html'))):
            if f.endswith('DOCS_WILL_BE_GENERATED_HERE'):
                continue
            start_command_in_subprocess([
                'rm', '-rf', repo_file(repo_file('html'), f)
            ], shell=False, nostdout=parsed.quiet, nostderr=parsed.quiet)

        # build docs (without mounting to work well in CircleCI)
        dtslogger.info("Building the documentation...")
        container = dclient.containers.create(image=docs_image.id)

        # archive the input files:
        in_files_buf = io.BytesIO()
        in_files = tarfile.open(fileobj=in_files_buf, mode='w')
        for obj in os.listdir(repo_file('docs')):
            in_files.add(os.path.join(repo_file('docs'), obj), arcname=obj)
        in_files_buf.seek(0)

        # put them in the container
        container.put_archive(path='/docs/in/', data=in_files_buf)

        # run the container
        container.start()

        # attach and print output
        logs = container.attach(stdout=True, stderr=True, stream=True, logs=True)
        for log_line in logs:
            print(log_line.decode('utf-8'), end='')
        container.wait()

        # copy the results back to the host
        bits, stat = container.get_archive(path='/docs/out/')
        out_files_buf = io.BytesIO()
        for b in bits:
            out_files_buf.write(b)
        out_files_buf.seek(0)
        t = tarfile.open(fileobj=out_files_buf , mode='r')
        t.extractall(pathlib.Path(repo_file('html')))

        # delete container
        container.remove()

        dtslogger.info("Done!")


    @staticmethod
    def complete(shell, word, line):
        return []


