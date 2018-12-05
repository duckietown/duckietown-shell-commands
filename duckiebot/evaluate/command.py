import argparse
import getpass
import os
import subprocess
import threading
import time

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment

from utils.docker_utils import push_image_to_duckiebot, run_image_on_duckiebot, run_image_on_localhost, \
    start_slimremote_duckiebot_container, stop_container, \
    continuously_monitor, get_remote_client, record_bag
from utils.networking_utils import get_duckiebot_ip

usage = """

## Basic usage

    Evaluates the current submission on the Duckiebot:

        $ dts duckiebot evaluate

"""


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        prog = 'dts duckiebot evaluate'
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        group = parser.add_argument_group('Basic')

        parser.add_argument('hostname', default=None,
                            help="Name of the Duckiebot on which to perform evaluation")

        group.add_argument('--image', help="Image to evaluate",
                           default="duckietown/challenge-aido1_lf1-template-ros:v3")

        group.add_argument('--duration', help="Number of seconds to run evaluation", default=30)

        group.add_argument('--remotely', action='store_true', default=True,
                           help="Run the image on the laptop without pushing to Duckiebot")

        parsed = parser.parse_args(args)

        slimremote_container = start_slimremote_duckiebot_container(parsed.hostname)
        time.sleep(2)

        volumes = setup_expected_volumes(parsed.hostname)

        bag_container = record_bag(parsed.hostname, parsed.duration)

        env = {'username': 'root',
               'challenge_step_name': 'step1-simulation',
               'uid': 0,
               'challenge_name': 'aido1_LF1_r3-v3',
               'VEHICLE_NAME': parsed.hostname
               }

        if parsed.remotely:
            evaluate_remotely(parsed.hostname, parsed.image, int(parsed.duration), env, volumes)
        else:
            evaluate_locally(parsed.hostname, parsed.image, int(parsed.duration), env, volumes)

        #       image_view_container = start_rqt_image_view(parsed.hostname)
        stop_container(bag_container)
        stop_container(slimremote_container)


def setup_expected_volumes(hostname):
    tmpdir = '/tmp'

    USERNAME = getpass.getuser()
    dir_home_guest = os.path.expanduser('~')
    dir_fake_home_host = os.path.join(tmpdir, 'fake-%s-home' % USERNAME)
    if not os.path.exists(dir_fake_home_host):
        os.makedirs(dir_fake_home_host)

    challenge_description_dir = dir_fake_home_host + '/challenge-description'
    if not os.path.exists(challenge_description_dir):
        os.makedirs(challenge_description_dir)
        with(open(challenge_description_dir + '/description.yaml', 'w+')) as f:
            f.write("env: Duckietown-Lf-Lfv-Navv-Silent-v1")

    local_slimremote_dir = dir_fake_home_host + '/duckietown-slimremote'
    if not os.path.exists(local_slimremote_dir):
        setup_slimremote(local_slimremote_dir)

    dir_fake_home_guest = dir_home_guest
    dir_dtshell_host = os.path.join(dir_home_guest, '.dt-shell')
    dir_dtshell_guest = os.path.join(dir_fake_home_guest, '.dt-shell')
    dir_tmpdir_host = '/tmp'
    dir_tmpdir_guest = '/tmp'
    get_calibration_files(dir_fake_home_host, hostname)
    local_calibration_dir = dir_fake_home_host + '/config/calibrations'

    return {'/var/run/docker.sock': {'bind': '/var/run/docker.sock', 'mode': 'rw'},
            #            os.getcwd(): {'bind': os.getcwd(), 'mode': 'ro'}, # LP: why do we need this ?
            dir_tmpdir_host: {'bind': dir_tmpdir_guest, 'mode': 'rw'},
            dir_dtshell_host: {'bind': dir_dtshell_guest, 'mode': 'ro'},
            dir_fake_home_host: {'bind': dir_fake_home_guest, 'mode': 'rw'},
            '/etc/group': {'bind': '/etc/group', 'mode': 'ro'},
            challenge_description_dir: {'bind': '/challenge-description', 'mode': 'rw'},
            local_slimremote_dir: {'bind': '/workspace/src/duckietown-slimremote', 'mode': 'rw'},
            local_calibration_dir: {'bind': '/data/config/calibrations', 'mode': 'rw'},
            }


# get the calibration files off the robot
def get_calibration_files(tmp_dir, host, username='duckie'):
    dtslogger.info("Getting calibration files")
    p = subprocess.Popen(["scp", "-r", "%s@%s.local:/data/config" % (username, host), tmp_dir])
    sts = os.waitpid(p.pid, 0)

    dtslogger.info("%s/config/calibrations/camera_instrisic/%s.yaml" % (tmp_dir, host))
    ## for now we rename them to default.yaml - should change but it's the easiest way for now
    os.rename(tmp_dir + '/config/calibrations/camera_intrinsic/' + host + '.yaml',
              tmp_dir + '/config/calibrations/camera_intrinsic/default.yaml')
    os.rename(tmp_dir + '/config/calibrations/camera_extrinsic/' + host + '.yaml',
              tmp_dir + '/config/calibrations/camera_extrinsic/default.yaml')
    os.rename(tmp_dir + '/config/calibrations/kinematics/' + host + '.yaml',
              tmp_dir + '/config/calibrations/kinematics/default.yaml')


def setup_slimremote(destination_dir):
    from git import Repo
    dtslogger.info("Cloning duckietown/duckietown-slimremote locally to %s" % destination_dir)
    Repo.clone_from("https://github.com/duckietown/duckietown-slimremote", destination_dir, branch='testing')


# Runs everything on the Duckiebot

def evaluate_locally(duckiebot_name, image_name, duration, env, volumes):
    dtslogger.info("Running %s on %s" % (image_name, duckiebot_name))
    push_image_to_duckiebot(image_name, duckiebot_name)
    evaluation_container = run_image_on_duckiebot(image_name, duckiebot_name, env, volumes)
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    duckiebot_client = get_remote_client(duckiebot_ip)
    monitor_thread = threading.Thread(target=continuously_monitor, args=(duckiebot_client, evaluation_container.name))
    monitor_thread.start()
    dtslogger.info("Letting %s run for %d s..." % (image_name, duration))
    time.sleep(duration)
    stop_container(evaluation_container)


# Sends actions over the local network

def evaluate_remotely(duckiebot_name, image_name, duration, env, volumes):
    dtslogger.info("Running %s on localhost" % image_name)
    evaluation_container = run_image_on_localhost(image_name, duckiebot_name, env, volumes)
    local_client = check_docker_environment()
    monitor_thread = threading.Thread(target=continuously_monitor, args=(local_client, evaluation_container.name))
    monitor_thread.start()
    dtslogger.info("Letting %s run for %d s..." % (image_name, duration))
    time.sleep(duration)
    stop_container(evaluation_container)
