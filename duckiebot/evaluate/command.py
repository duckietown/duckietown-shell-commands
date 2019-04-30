import argparse
import getpass
import os
import subprocess
import threading
import time

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment

from utils.docker_utils import push_image_to_duckiebot, run_image_on_duckiebot, run_image_on_localhost, \
     stop_container, remove_container, default_env, \
    continuously_monitor, get_remote_client, record_bag
from utils.networking_utils import get_duckiebot_ip

usage = """

## Basic usage

    Evaluates the current submission on the Duckiebot:

        $ dts duckiebot evaluate --duckiebot_name ![DUCKIEBOT_HOSTNAME]

"""


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        prog = 'dts duckiebot evaluate'
        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        group = parser.add_argument_group('Basic')
        group.add_argument('--duckiebot_name', default=None,
                            help="Name of the Duckiebot on which to perform evaluation")
        group.add_argument('--duckiebot_username', default="duckie",
                           help="The duckiebot username")
        group.add_argument('--image', dest='image_name',
                           help="Image to evaluate, if none specified then we will build your current context",
                           default=None)
        group.add_argument('--glue_node_image', default="duckietown/challenge-aido_lf-duckiebot:aido2",
                           help="The node that glues your submission with ROS on the duckiebot. Probably don't change")
        group.add_argument('--duration', help="Number of seconds to run evaluation", default=15)
        group.add_argument('--remotely', action='store_true', default=True,
                           help="If true run the image over network without pushing to Duckiebot")
        group.add_argument('--record_bag', action='store_true', default=False,
                           help="If true record a rosbag")
        group.add_argument('--max_vel', help="the max velocity for the duckiebot", default=0.7)
        group.add_argument('--challenge', help="Specific challenge to evaluate")
        parsed = parser.parse_args(args)

        tmpdir = '/tmp'
        USERNAME = getpass.getuser()
        dir_home_guest = os.path.expanduser('~')
        dir_fake_home = os.path.join(tmpdir, 'fake-%s-home' % USERNAME)
        if not os.path.exists(dir_fake_home):
            os.makedirs(dir_fake_home)
        get_calibration_files(dir_fake_home, parsed.duckiebot_username, parsed.duckiebot_name)

        client = check_docker_environment()
        agent_container_name = "agent"
        glue_container_name = "aido_glue"

        # remove the containers if they are already running
        remove_if_running(client, agent_container_name)
        remove_if_running(client, glue_container_name)

        # setup the fifos2 volume (requires pruning it if it's still hanging around from last time)
        try:
            client.volumes.prune()
            fifo2_volume=client.volumes.create(name='fifos2')
        except Exception as e:
            dtslogger.warn("error creating volume: %s" % e)


        duckiebot_ip = get_duckiebot_ip(parsed.duckiebot_name)

        duckiebot_client = get_remote_client(duckiebot_ip)
        drivers_container = duckiebot_client.containers.get('drivers')
        if drivers_container is None:
            dtslogger.warn("The drivers are not running on the duckiebot")


        # let's start building stuff for the "glue" node
        glue_volumes =  {fifo2_volume.name: {'bind': '/fifos', 'mode': 'rw'}}
        glue_env = {'HOSTNAME':parsed.duckiebot_name,
                    'DUCKIEBOT_NAME':parsed.duckiebot_name,
                    'ROS_MASTER_URI':'http://%s:11311' % duckiebot_ip}

        dtslogger.info("Running %s on localhost with environment vars: %s" %
                       (parsed.glue_node_image, glue_env))
        params = {'image': parsed.glue_node_image,
                  'name': glue_container_name,
                  'network_mode': 'host',
                  'privileged': True,
                  'environment': glue_env,
                  'detach': True,
                  'tty': True,
                  'volumes': glue_volumes}

        # run the glue container
        glue_container = client.containers.run(**params)

        monitor_thread = threading.Thread(target=continuously_monitor, args=(client, glue_container.name))
        monitor_thread.start()

        if parsed.image_name is None:
            # if we didn't get an `image_name` we try need to build the local container
            path = '.'
            dockerfile = os.path.join(path, 'Dockerfile')
            if not os.path.exists(dockerfile):
                msg = 'No Dockerfile'
                raise Exception(msg)
            tag='myimage'
            cmd = ['docker', 'build', '-t', tag, '-f', dockerfile]
            cmd.append(path)
            subprocess.check_call(cmd)
            image_name = tag
        else:
            image_name = parsed.image_name


        # start to build the agent stuff
        agent_env = {'AIDONODE_DATA_IN':'/fifos/agent-in',
                    'AIDONODE_DATA_OUT':'fifo:/fifos/agent-out'}

        agent_volumes = {fifo2_volume.name: {'bind': '/fifos', 'mode': 'rw'},
                         dir_fake_home: {'bind': '/data/config', 'mode': 'rw'}
                         }


        params = {'image': image_name,
                  'remove': True,
                  'name': agent_container_name,
                  'environment': agent_env,
                  'detach': True,
                  'tty': True,
                  'volumes': agent_volumes}

        dtslogger.info("Running %s on localhost with environment vars: %s" % (image_name, agent_env))
        agent_container = client.containers.run(**params)
        monitor_thread = threading.Thread(target=continuously_monitor,args=(client, agent_container_name))
        monitor_thread.start()

        duration = int(parsed.duration)
        # should we record a bag?
        if parsed.record_bag:
            bag_container = record_bag(parsed.hostname, duration)

        dtslogger.info("Running for %d s" % duration)
        time.sleep(duration)
        stop_container(glue_container)
        stop_container(agent_container)

        if parsed.record_bag:
            stop_container(bag_container)

        # TODO remotely vs. locally

def remove_if_running(client, container_name):
        try:
            container = client.containers.get(container_name)
            dtslogger.info("%s already running - stopping it first.." % container_name)
            stop_container(container)
            dtslogger.info("removing %s" % container_name)
            remove_container(container)
        except Exception as e:
            dtslogger.warn("couldn't remove existing container: %s" % e)


# get the calibration files off the robot
def get_calibration_files(dir, duckiebot_username, duckiebot_name):
    dtslogger.info("Getting calibration files")
    p = subprocess.Popen(["scp", "-r", "%s@%s.local:/data/config" % (duckiebot_username, duckiebot_name),
                          dir])
    sts = os.waitpid(p.pid, 0)


# Runs everything on the Duckiebot

#def evaluate_locally(duckiebot_name, image_name, duration, env, volumes):
#    dtslogger.info("Running %s on %s" % (image_name, duckiebot_name))
#    push_image_to_duckiebot(image_name, duckiebot_name)
#    evaluation_container = run_image_on_duckiebot(image_name, duckiebot_name, env, volumes)
#    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
#    duckiebot_client = get_remote_client(duckiebot_ip)
#    monitor_thread = threading.Thread(target=continuously_monitor, args=(duckiebot_client, evaluation_container.name))
#    monitor_thread.start()
#    dtslogger.info("Letting %s run for %d s..." % (image_name, duration))
#    time.sleep(duration)
#    stop_container(evaluation_container)


