import argparse
import getpass
import grp
import json
import os
import platform
import socket

import yaml

from challenges.challenges_cmd_utils import check_duckietown_challenges_version
from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.constants import DTShellConstants
from dt_shell.env_checks import check_docker_environment
from utils.docker_utils import continuously_monitor, replace_important_env_vars, start_rqt_image_view

usage = """

## Basic usage

    Evaluate the current submission:

        $ dts challenges evaluate
 
"""


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):

        check_duckietown_challenges_version()

        prog = "dts challenges evaluate"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        group = parser.add_argument_group("Basic")

        group.add_argument("--no-cache", action="store_true", default=False, help="")
        group.add_argument("--no-build", action="store_true", default=False, help="")
        group.add_argument("--no-pull", action="store_true", default=False, help="")
        group.add_argument("--challenge", help="Specific challenge to evaluate")

        group.add_argument(
            "--image", help="Evaluator image to run", default="${AIDO_REGISTRY}/duckietown/dt-challenges-evaluator:daffy",
        )
        group.add_argument(
            "--shell", action="store_true", default=False, help="Runs a shell in the container",
        )
        group.add_argument("--output", help="", default="output")
        group.add_argument(
            "--visualize", help="Visualize the evaluation", action="store_true", default=False,
        )
        parser.add_argument("--impersonate", type=str, default=None)
        group.add_argument("-C", dest="change", default=None)

        parsed = parser.parse_args(args)

        if parsed.change:
            os.chdir(parsed.change)

        client = check_docker_environment()

        command = ["dt-challenges-evaluate-local"]
        if parsed.no_cache:
            command.append("--no-cache")
        if parsed.no_build:
            command.append("--no-build")
        if parsed.challenge:
            command.extend(["--challenge", parsed.challenge])
        if parsed.impersonate:
            command.extend(["--impersonate", parsed.impersonate])
        output_rp = os.path.realpath(parsed.output)
        command.extend(["--output", parsed.output])
        #
        # if parsed.features:
        #     dtslogger.debug('Passing features %r' % parsed.features)
        #     command += ['--features', parsed.features]
        # fake_dir = '/submission'
        tmpdir = "/tmp"

        UID = os.getuid()
        USERNAME = getpass.getuser()
        dir_home_guest = "/fake-home/%s" % USERNAME  # os.path.expanduser('~')
        dir_fake_home_host = os.path.join(tmpdir, "fake-%s-home" % USERNAME)
        if not os.path.exists(dir_fake_home_host):
            os.makedirs(dir_fake_home_host)

        dir_fake_home_guest = dir_home_guest
        dir_dtshell_host = os.path.join(os.path.expanduser("~"), ".dt-shell")
        dir_dtshell_guest = os.path.join(dir_fake_home_guest, ".dt-shell")
        dir_tmpdir_host = "/tmp"
        dir_tmpdir_guest = "/tmp"

        volumes = {"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"}}
        d = os.path.join(os.getcwd(), parsed.output)
        if not os.path.exists(d):
            os.makedirs(d)
        volumes[output_rp] = {"bind": d, "mode": "rw"}
        volumes[os.getcwd()] = {"bind": os.getcwd(), "mode": "ro"}
        volumes[dir_tmpdir_host] = {"bind": dir_tmpdir_guest, "mode": "rw"}
        volumes[dir_dtshell_host] = {"bind": dir_dtshell_guest, "mode": "ro"}
        volumes[dir_fake_home_host] = {"bind": dir_fake_home_guest, "mode": "rw"}
        volumes["/etc/group"] = {"bind": "/etc/group", "mode": "ro"}

        binds = [_["bind"] for _ in volumes.values()]
        for b1 in binds:
            for b2 in binds:
                if b1 == b2:
                    continue
                if b1.startswith(b2):
                    msg = "Warning, it might be a problem to have binds with overlap"
                    msg += "\n  b1: %s" % b1
                    msg += "\n  b2: %s" % b2
                    dtslogger.warn(msg)
        # command.extend(['-C', fake_dir])
        env = {}

        extra_environment = dict(username=USERNAME, uid=UID, USER=USERNAME, HOME=dir_fake_home_guest)

        env.update(extra_environment)

        dtslogger.debug("Volumes:\n\n%s" % yaml.safe_dump(volumes, default_flow_style=False))

        dtslogger.debug("Environment:\n\n%s" % yaml.safe_dump(env, default_flow_style=False))

        from duckietown_challenges.rest import get_duckietown_server_url

        url = get_duckietown_server_url()
        dtslogger.info("The server URL is: %s" % url)
        if "localhost" in url:
            h = socket.gethostname()
            replacement = h + ".local"

            dtslogger.warning('There is "localhost" inside, so I will try to change it to %r' % replacement)
            dtslogger.warning('This is because Docker cannot see the host as "localhost".')

            url = url.replace("localhost", replacement)
            dtslogger.warning("The new url is: %s" % url)
            dtslogger.warning("This will be passed to the evaluator in the Docker container.")

        env["DTSERVER"] = url

        container_name = "local-evaluator"
        image = replace_important_env_vars(parsed.image)
        name, _, tag = image.rpartition(":")

        if not parsed.no_pull:
            dtslogger.info("Updating container %s" % image)

            dtslogger.info("This might take some time.")
            client.images.pull(name, tag)
        #
        try:
            container = client.containers.get(container_name)
        except:
            pass
        else:
            dtslogger.error("stopping previous %s" % container_name)
            container.stop()
            dtslogger.error("removing")
            container.remove()

        dtslogger.info("Starting container %s with %s" % (container_name, image))

        detach = True

        env[DTShellConstants.DT1_TOKEN_CONFIG_KEY] = shell.get_dt1_token()
        dtslogger.info("Container command: %s" % " ".join(command))

        # add all the groups
        on_mac = "Darwin" in platform.system()
        if on_mac:
            group_add = []
        else:
            group_add = [g.gr_gid for g in grp.getgrall() if USERNAME in g.gr_mem]

        interactive = False
        if parsed.shell:
            interactive = True
            detach = False
            command = ["/bin/bash", "-l"]

        params = dict(
            working_dir=os.getcwd(),
            user=UID,
            group_add=group_add,
            command=command,
            tty=interactive,
            volumes=volumes,
            environment=env,
            remove=True,
            network_mode="host",
            detach=detach,
            name=container_name,
        )
        dtslogger.info("Parameters:\n%s" % json.dumps(params, indent=4))
        client.containers.run(image, **params)

        if parsed.visualize:
            start_rqt_image_view()

        continuously_monitor(client, container_name)
        # dtslogger.debug('evaluate exited with code %s' % ret_code)
        # sys.exit(ret_code)
