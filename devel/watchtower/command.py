import os
import argparse
import subprocess
from dt_shell import DTCommandAbs, dtslogger
from termcolor import colored

WATCHTOWER_IMAGE = 'v2tec/watchtower'
DEFAULT_MACHINE = 'unix:///var/run/docker.sock'
VALID_COMMANDS = ['stop', 'start', 'status']


class DTCommand(DTCommandAbs):

    help = 'Manages a Docker watchtower instance'


    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('action', nargs=1, choices=VALID_COMMANDS,
                            help="Action to perform on the watchtower instance")
        parser.add_argument('-H', '--machine', default=DEFAULT_MACHINE,
                            help="Docker socket or hostname where the watchtower is running")
        parsed, _ = parser.parse_known_args(args=args)
        action = parsed.action[0]
        # ---
        # get info about containers running on the docker endpoint
        container_id = _get_container_id(parsed.machine, all=False)
        is_running = container_id is not None
        # action: status
        if action == 'status':
            bg_color = 'on_green' if is_running else 'on_red'
            msg = '[RUNNING]' if is_running else '[NOT RUNNING]'
            info = 'with ID {}'.format(container_id) if is_running else ''
            print("{}: Watchtower {}".format(colored(msg, 'white', bg_color), info))
            return
        # action: stop
        if action == 'stop' and not is_running:
            msg = 'No watchtower instance found. Nothing to do.'
            dtslogger.info(msg)
            return
        # action: start
        if action == 'start':
            if is_running:
                msg = 'Watchtower already running. Nothing to do.'
                dtslogger.info(msg)
                return
            else:
                container_id = _get_container_id(parsed.machine, all=True)
                if container_id is None:
                    msg = 'Watchtower instance not found. Run `docker run ...` first.'
                    dtslogger.info(msg)
                    return
        # action: [stop, start]
        dtslogger.info('{}ing watchtower container...'.format(action.title()))
        _ = _run_cmd([
            'docker',
                '-H=%s' % parsed.machine,
                action,
                    container_id
        ], get_output=True)
        dtslogger.info('Done!')



    @staticmethod
    def complete(shell, word, line):
        return []


    @staticmethod
    def is_running(machine):
        container_id = _get_container_id(machine, all=False)
        is_running = container_id is not None
        return is_running


def _run_cmd(cmd, get_output=False):
    dtslogger.debug('$ %s' % cmd)
    if get_output:
        return [l for l in subprocess.check_output(cmd).decode('utf-8').split('\n') if l]
    else:
        subprocess.check_call(cmd)


def _get_container_id(machine, all):
    dtslogger.info('Retrieving info about the containers running on the Docker endpoint...')
    containers = _run_cmd([
        'docker',
            '-H=%s' % machine,
            'ps',
                '--format',
                '("{{.ID}}", "{{.Image}}")',
                '--all=%d' % int(all)
    ], get_output=True)
    # check if there is a watchtower instance running
    for id_im in containers:
        id, im = eval(id_im)
        if im.startswith(WATCHTOWER_IMAGE):
            return id
    return None
