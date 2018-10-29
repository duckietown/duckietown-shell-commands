from __future__ import unicode_literals
import argparse
import datetime
import getpass
import os
import platform
import socket
import sys
import time
import traceback

import six
import yaml
from docker.errors import NotFound, APIError

from dt_shell import dtslogger, DTCommandAbs
from dt_shell.constants import DTShellConstants
from dt_shell.env_checks import check_docker_environment
from dt_shell.remote import get_duckietown_server_url

usage = """

## Basic usage

    Evaluate the current submission:

        $ dts challenges evaluate
 


"""


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):

        prog = 'dts challenges evaluate'
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        group = parser.add_argument_group('Basic')

        group.add_argument('--no-cache', action='store_true', default=False,
                           help="")

        group.add_argument('--no-build', action='store_true', default=False,
                           help="")
        group.add_argument('--no-pull', action='store_true', default=False,
                           help="")
        group.add_argument('--image', help="Evaluator image to run",
                           default='duckietown/dt-challenges-evaluator:v3')
        group.add_argument('--shell', action='store_true', default=False,
                           help="Runs a shell in the container")
        group.add_argument('--output', help="", default='output')

        group.add_argument('-C', dest='change', default=None)

        parsed = parser.parse_args(args)

        if parsed.change:
            os.chdir(parsed.change)

        client = check_docker_environment()

        command = [
            'dt-challenges-evaluate-local'
        ]
        if parsed.no_cache:
            command.append('--no-cache')
        if parsed.no_build:
            command.append('--no-build')

        output_rp = os.path.realpath(parsed.output)
        command.extend(['--output', parsed.output])
        #
        # if parsed.features:
        #     dtslogger.debug('Passing features %r' % parsed.features)
        #     command += ['--features', parsed.features]
        # fake_dir = '/submission'
        tmpdir = '/tmp'

        UID = os.getuid()
        USERNAME = getpass.getuser()
        dir_home_guest = os.path.expanduser('~')
        dir_fake_home_host = os.path.join(tmpdir, 'fake-%s-home' % USERNAME)
        if not os.path.exists(dir_fake_home_host):
            os.makedirs(dir_fake_home_host)

        dir_fake_home_guest = dir_home_guest
        dir_dtshell_host = os.path.join(dir_home_guest, '.dt-shell')
        dir_dtshell_guest = os.path.join(dir_fake_home_guest, '.dt-shell')
        dir_tmpdir_host = '/tmp'
        dir_tmpdir_guest = '/tmp'

        volumes = {
            '/var/run/docker.sock': {'bind': '/var/run/docker.sock', 'mode': 'rw'}
        }
        d = os.path.join(os.getcwd(), parsed.output)
        if not os.path.exists(d):
            os.makedirs(d)
        volumes[output_rp] = {'bind': d, 'mode': 'rw'}
        volumes[os.getcwd()] = {'bind': os.getcwd(), 'mode': 'ro'}
        volumes[dir_tmpdir_host] = {'bind': dir_tmpdir_guest, 'mode': 'rw'}
        volumes[dir_dtshell_host] = {'bind': dir_dtshell_guest, 'mode': 'ro'}
        volumes[dir_fake_home_host] = {'bind': dir_fake_home_guest, 'mode': 'rw'}
        volumes['/etc/group'] = {'bind': '/etc/group', 'mode': 'ro'}

        binds = [_['bind'] for _ in volumes.values()]
        for b1 in binds:
            for b2 in binds:
                if b1 == b2:
                    continue
                if b1.startswith(b2):
                    msg = 'Warning, it might be a problem to have binds with overlap'
                    msg += '\n  b1: %s' % b1
                    msg += '\n  b2: %s' % b2
                    dtslogger.warn(msg)
        # command.extend(['-C', fake_dir])
        env = {}

        extra_environment = dict(username=USERNAME, uid=UID, USER=USERNAME, HOME=dir_fake_home_guest)

        env.update(extra_environment)

        dtslogger.debug('Volumes:\n\n%s' % yaml.safe_dump(volumes, default_flow_style=False))

        dtslogger.debug('Environment:\n\n%s' % yaml.safe_dump(env, default_flow_style=False))

        url = get_duckietown_server_url()
        dtslogger.info('The server URL is: %s' % url)
        if 'localhost' in url:
            h = socket.gethostname()
            replacement = h + '.local'

            dtslogger.warning('There is "localhost" inside, so I will try to change it to %r' % replacement)
            dtslogger.warning('This is because Docker cannot see the host as "localhost".')

            url = url.replace("localhost", replacement)
            dtslogger.warning('The new url is: %s' % url)
            dtslogger.warning('This will be passed to the evaluator in the Docker container.')

        env['DTSERVER'] = url

        container_name = 'local-evaluator'
        image = parsed.image
        name, tag = image.split(':')
        if not parsed.no_pull:
            dtslogger.info('Updating container %s' % image)

            dtslogger.info('This might take some time.')
            client.images.pull(name, tag)
        #
        try:
            container = client.containers.get(container_name)
        except:
            pass
        else:
            dtslogger.error('stopping previous %s' % container_name)
            container.stop()
            dtslogger.error('removing')
            container.remove()

        dtslogger.info('Starting container %s with %s' % (container_name, image))

        detach = True

        env[DTShellConstants.DT1_TOKEN_CONFIG_KEY] = shell.get_dt1_token()
        dtslogger.info('Container command: %s' % " ".join(command))

        # add all the groups
        on_mac = 'Darwin' in platform.system()
        if on_mac:
            group_add = []
        else:
            group_add = [g.gr_gid for g in grp.getgrall() if USERNAME in g.gr_mem]

        # group_add = [g.gr_name for g in grp.getgrall() if USERNAME in g.gr_mem]
        interactive = False
        if parsed.shell:
            interactive = True
            detach=False
            command = ['/bin/bash','-l']

        params = dict(working_dir=os.getcwd(),
                      user=UID,
                      group_add=group_add,
                      command=command,
                      tty=interactive,
                      volumes=volumes,
                      environment=env,
                      remove=True,
                      network_mode='host',
                      detach=detach,
                      name=container_name)
        dtslogger.info('Parameters:\n%s' % json.dumps(params, indent=4))
        client.containers.run(image,
                              **params)
        continuously_monitor(client, container_name)
        # dtslogger.debug('evaluate exited with code %s' % ret_code)
        # sys.exit(ret_code)


import json


def continuously_monitor(client, container_name):
    dtslogger.debug('Monitoring container %s' % container_name)
    last_log_timestamp = None
    while True:
        try:
            container = client.containers.get(container_name)
        except Exception as e:
            msg = 'Cannot get container %s: %s' % (container_name, e)
            # dtslogger.error(msg)
            break
            # dtslogger.info('Will wait.')
            # time.sleep(5)
            # continue

        dtslogger.info('status: %s' % container.status)
        if container.status == 'exited':

            msg = 'The container exited.'

            logs = ''
            for c in container.logs(stdout=True, stderr=True, stream=True, since=last_log_timestamp):
                last_log_timestamp = datetime.datetime.now()
                logs += c.decode()
            dtslogger.error(msg)

            tf = 'evaluator.log'
            with open(tf, 'w') as f:
                f.write(logs)

            msg = 'Logs saved at %s' % tf
            dtslogger.info(msg)

            # return container.exit_code
            return  # XXX
        try:
            for c in container.logs(stdout=True, stderr=True, stream=True, follow=True, since=last_log_timestamp):
                if six.PY2:
                    sys.stdout.write(c)
                else:
                    sys.stdout.write(c.decode('utf-8'))

                last_log_timestamp = datetime.datetime.now()

            time.sleep(3)
        except KeyboardInterrupt:
            dtslogger.info('Received CTRL-C. Stopping container...')
            try:
                container.stop()
                dtslogger.info('Removing container')
                container.remove()
                dtslogger.info('Container removed.')
            except NotFound:
                pass
            except APIError as e:
                # if e.errno == 409:
                #
                pass
            break
        except BaseException:
            dtslogger.error(traceback.format_exc())
            dtslogger.info('Will try to re-attach to container.')
            time.sleep(3)
    dtslogger.debug('monitoring graceful exit')


def logs_for_container(client, container_id):
    logs = ''
    container = client.containers.get(container_id)
    for c in container.logs(stdout=True, stderr=True, stream=True, timestamps=True):
        logs += c.decode('utf-8')
    return logs


import grp
