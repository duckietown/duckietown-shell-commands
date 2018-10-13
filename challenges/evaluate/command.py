import argparse
import getpass
import os
import socket

from dt_shell import dtslogger, DTCommandAbs
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
        check_docker_environment()

        home = os.path.expanduser('~')
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
                           default='duckietown/dt-challenges-evaluator:local-eval')

        group.add_argument('--output', help="", default='output')

        group.add_argument('-C', dest='change', default=None)

        parsed = parser.parse_args(args)

        if parsed.change:
            os.chdir(parsed.change)

        command = [
            'dt-challenges-evaluate-local'
        ]
        if parsed.no_cache:
            command.append('--no-cache')
        if parsed.no_build:
            command.append('--no-build')


        output_rp = os.path.realpath(parsed.output)
        command.extend(['--output', output_rp])
        #
        # if parsed.features:
        #     dtslogger.debug('Passing features %r' % parsed.features)
        #     command += ['--features', parsed.features]
        fake_dir = '/submission'
        volumes = {
            '/var/run/docker.sock': {'bind': '/var/run/docker.sock', 'mode': 'rw'},
            os.path.join(home, '.dt-shell'): {'bind': '/root/.dt-shell', 'mode': 'ro'},
            output_rp: {'bind': output_rp, 'mode': 'rw'},
            '/tmp': {'bind': '/tmp', 'mode': 'rw'},
            os.getcwd(): {'bind': fake_dir, 'mode': 'ro'}
        }
        command.extend(['-C', fake_dir])
        env = {}

        UID = os.getuid()
        USERNAME = getpass.getuser()
        extra_environment = dict(username=USERNAME, uid=UID)

        env.update(extra_environment)

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

        import docker
        client = docker.from_env()

        container_name = 'local-evaluator'
        image = parsed.image
        name, tag = image.split(':')
        if not parsed.no_pull:
            dtslogger.info('Updating container %s' % image)

            client.images.pull(name, tag)

        if not parsed.no_pull:
            dtslogger.info('Updating container %s' % image)

            client.images.pull(name, tag)

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

        dtslogger.info('Container command: %s' % " ".join(command))

        try:
            logs = client.containers.run(image,
                                         # remove=True,
                                         command=command,
                                         volumes=volumes,
                                         environment=env,
                                         network_mode='host',
                                         detach=False,
                                         name=container_name,
                                         tty=True)
        finally:
            print logs_for_container(client, container_name)

        print(logs)



def logs_for_container(client, container_id):
    logs = ''
    container = client.containers.get(container_id)
    for c in container.logs(stdout=True, stderr=True, stream=True, timestamps=True):
        logs += c
    return logs
