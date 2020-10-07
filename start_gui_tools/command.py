import os
import json
import argparse
import platform
import subprocess

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import remove_if_running, pull_if_not_exist, get_endpoint_architecture
from utils.duckietown_utils import get_distro_version

DEFAULT_IMAGE_FMT = "duckietown/dt-gui-tools:{}-{}"
AVAHI_SOCKET = "/var/run/avahi-daemon/socket"
USAGE = """
GUI Tools: 

    {}
"""


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts start_gui_tools DUCKIEBOT_NAME"
        parser = argparse.ArgumentParser(prog=prog, usage=USAGE.format(prog))
        parser.add_argument("hostname", nargs="?", default=None, help="Name of the Duckiebot")
        parser.add_argument(
            "--network", default="host", help="Name of the network to connect the container to"
        )
        parser.add_argument(
            "--sim", action="store_true", default=False, help="Are we running in simulator?",
        )
        parser.add_argument(
            "--image", default=None, help="The Docker image to use. Advanced users only.",
        )
        parser.add_argument(
            "--vnc", action="store_true", default=False, help="Run the novnc server",
        )
        # parse arguments
        parsed = parser.parse_args(args)
        # change hostname if we are in SIM mode
        if parsed.sim or parsed.hostname is None:
            machine = parsed.hostname = "localhost"
        else:
            machine = (
                f"{parsed.hostname}.local" if not parsed.hostname.endswith(".local") else parsed.hostname
            )
        # pick the right architecture if not set
        arch = get_endpoint_architecture()
        dtslogger.info(f"Target architecture automatically set to {arch}.")
        # compile image name
        image = parsed.image if parsed.image else DEFAULT_IMAGE_FMT.format(get_distro_version(shell), arch)
        # open Docker client
        client = check_docker_environment()
        # create container name and make there is no name clash
        container_name = f"dts_gui_tools_{parsed.hostname}{'_vnc' if parsed.vnc else ''}"
        remove_if_running(client, container_name)
        # setup common env
        env = {
            "VEHICLE_NAME": parsed.hostname,
            "ROS_MASTER": parsed.hostname,
            "DUCKIEBOT_NAME": parsed.hostname,
            "ROS_MASTER_URI": "http://%s:11311" % machine,
            "HOSTNAME": "default" if parsed.sim else parsed.hostname,
        }
        volumes = {}
        # configure mDNS
        if os.path.exists(AVAHI_SOCKET):
            volumes[AVAHI_SOCKET] = {"bind": AVAHI_SOCKET, "mode": "rw"}
        else:
            dtslogger.warning(
                "Avahi socket not found ({}). The container might not be able "
                "to resolve *.local hostnames.".format(AVAHI_SOCKET)
            )

        p = platform.system().lower()
        if "darwin" in p:
            running_on_mac = True
        else:
            running_on_mac = False
        # configure X11 forwarding
        if not parsed.vnc:
            env["QT_X11_NO_MITSHM"] = 1
            # we mount the X11 socket
            volumes["/tmp/.X11-unix"] = {"bind": "/tmp/.X11-unix", "mode": "rw"}
            # configure X forwarding for different systems
            if running_on_mac:
                subprocess.call(["xhost", "+", "127.0.0.1"])
                env["DISPLAY"] = "host.docker.internal:0"
            else:
                subprocess.call(["xhost", "+"])
                env["DISPLAY"] = os.environ["DISPLAY"]
        # print some stats
        dtslogger.debug(
            f"Running {container_name} with environment vars:\n\n"
            f"{json.dumps(env, sort_keys=True, indent=4)}\n"
        )
        # pull image
        pull_if_not_exist(client, image)
        # collect container config

        params = {
            "image": image,
            "name": container_name,
            "environment": env,
            "stdin_open": True,
            "tty": True,
            "detach": True,
            "remove": True,
            "stream": True,
            "command": f"dt-launcher-{'vnc' if parsed.vnc else 'default'}",
            "volumes": volumes,
        }
        if not running_on_mac:
            params["privileged"] = True
            params["network_mode"] = parsed.network

        if parsed.vnc:
            params["ports"] = {"8087/tcp": ("0.0.0.0", 8087)}


        # print some info
        if parsed.vnc:
            dtslogger.info(
                "Running novnc. Navigate to http://localhost:8087/ in your browser. "
            )
        dtslogger.debug(
            f"Running container with configuration:\n\n" f"{json.dumps(params, sort_keys=True, indent=4)}\n"
        )
        # run the container
        client.containers.run(**params)
        # attach to the container with an interactive session
        attach_cmd = "docker attach %s" % container_name
        start_command_in_subprocess(attach_cmd)
        # ---
        dtslogger.info("Done. Have a nice day")
