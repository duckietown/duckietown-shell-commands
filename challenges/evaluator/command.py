import argparse
import os
import socket

from dt_shell import dtslogger, DTCommandAbs
from dt_shell.remote import get_duckietown_server_url


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        home = os.path.expanduser('~')
        parser = argparse.ArgumentParser()
        parser.add_argument('--no-watchtower', dest='no_watchtower', action='store_true', default=False,
                            help="Disable starting of watchtower")
        # parser.add_argument('--no-submit', dest='no_submit', action='store_true', default=False,
        #                     help="Disable submission (only build and push)")
        # parser.add_argument('--no-cache', dest='no_cache', action='store_true', default=False)
        parsed = parser.parse_args(args)

        import docker
        client = docker.from_env()

        image = 'andreacensi/dt-challenges-evaluator:latest'
        command = ['dt-challenges-evaluator', '--continuous']
        volumes = {
            '/var/run/docker.sock': {'bind': '/var/run/docker.sock', 'mode': 'rw'},
            os.path.join(home, '.dt-shell'): {'bind': '/root/.dt-shell', 'mode': 'ro'},
            '/tmp': {'bind': '/tmp', 'mode': 'rw'}
        }
        env = {}

        if not parsed.no_watchtower:
            ensure_watchtower_active(client)

        h = socket.gethostname()
        env['DTSERVER'] = get_duckietown_server_url().replace("localhost", h + '.local')

        dtslogger.info('Starting container %s' % image)
        container = client.containers.run(image, command, volumes=volumes, environment=env,
                                          network_mode='host', detach=True,
                                          tty=True)
        try:
            for line in container.logs(stdout=True, stderr=True, stream=True, follow=True):
                sys.stdout.write(line)
                # print(line)
        except KeyboardInterrupt:
            dtslogger.info('Received CTRL-C. Stopping container...')
            container.stop()
            dtslogger.info('Container stopped.')

import sys

def ensure_watchtower_active(client):
    containers = client.containers.list(filters=dict(status='running'))
    watchtower_tag = 'v2tec/watchtower'
    found = None
    for c in containers:
        tags = c.image.attrs['RepoTags']
        for t in tags:
            if watchtower_tag in t:
                found = c

    if found is not None:
        print('I found watchtower active.')
    else:
        print('Starting watchtower')
        env = {}
        volumes = {
            '/var/run/docker.sock': {'bind': '/var/run/docker.sock', 'mode': 'rw'},
            # os.path.join(home, '.dt-shell'): {'bind': '/root/.dt-shell', 'mode': 'ro'}
        }
        container = client.containers.run(watchtower_tag, volumes=volumes, environment=env, network_mode='host',
                                          detach=True)
        print('Detached: %s' % container)
