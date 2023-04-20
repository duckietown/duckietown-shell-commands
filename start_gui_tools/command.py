import argparse
import json
import os
import platform
import subprocess
from datetime import datetime
import docker

import pytz
from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.env_checks import check_docker_environment

from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import (
    get_endpoint_architecture,
    pull_if_not_exist,
    pull_image_OLD,
    remove_if_running,
    get_registry_to_use,
)

from utils.duckietown_utils import get_distro_version
from utils.git_utils import get_last_commit
from utils.misc_utils import sanitize_hostname
from utils.networking_utils import get_duckiebot_ip

DEFAULT_IMAGE_FMT = "duckietown/dt-gui-tools:{}-{}"
AVAHI_SOCKET = "/var/run/avahi-daemon/socket"
USAGE = """
GUI Tools:

    {}
"""


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        prog = "dts start_gui_tools DUCKIEBOT_NAME"
        parser = argparse.ArgumentParser(prog=prog, usage=USAGE.format(prog))
        parser.add_argument("hostname", nargs="?", default=None, help="Name of the Duckiebot")
        parser.add_argument(
            "--network", default="host", help="Name of the network to connect the container to"
        )
        parser.add_argument("--port", action="append", default=[], type=str)
        parser.add_argument(
            "--sim",
            action="store_true",
            default=False,
            help="Are we running in simulator?",
        )
        parser.add_argument(
            "--pull",
            action="store_true",
            default=False,
            help="Pull the dt-gui-tools image",
        )
        parser.add_argument(
            "--image",
            default=None,
            help="The Docker image to use. Advanced users only.",
        )
        parser.add_argument(
            "--vnc",
            action="store_true",
            default=False,
            help="Run the novnc server",
        )
        parser.add_argument(
            "--ip",
            action="store_true",
            help="(Optional) Use the IP address to reach the robot instead of mDNS",
        )
        parser.add_argument(
            "--mount",
            default=None,
            help="(Optional) Mount a directory to the container",
        )
        parser.add_argument(
            "--wkdir",
            default=None,
            help="(Optional) Working directory inside the container",
        )
        parser.add_argument(
            "-L",
            "--launcher",
            type=str,
            default="default",
            help="(Optional) Launcher to run inside the container",
        )
        parser.add_argument(
            "--name",
            type=str,
            default=None,
            help="(Optional) Container name",
        )
        parser.add_argument(
            "--nvidia",
            action="store_true",
            default=False,
            help="should we use the NVIDIA runtime?",
        )

        parser.add_argument(
            "--uid",
            type=int,
            default=None,
            help="(Optional) User ID inside the container",
        )
        parser.add_argument(
            "--no-scream",
            action="store_true",
            default=False,
            help="(Optional) Scream if the container ends with a non-zero exit code",
        )
        parser.add_argument(
            "--detach",
            "-d",
            action="store_true",
            default=False,
            help="Detach from container",
        )
        parser.add_argument("cmd_args", nargs="*", default=[])
        # parse arguments
        parsed = parser.parse_args(args)
        if "parsed" in kwargs:
            parsed.__dict__.update(kwargs["parsed"].__dict__)
        dtslogger.debug(f"Arguments: {str(parsed)}")
        # hostname = "LOCAL" is same as None
        if parsed.hostname == "LOCAL":
            parsed.hostname = None
        # change hostname if we are in SIM mode
        if parsed.sim or parsed.hostname is None:
            robot_host = parsed.hostname = "localhost"
        else:
            hostname = parsed.hostname if not parsed.ip else get_duckiebot_ip(parsed.hostname)
            robot_host = sanitize_hostname(hostname)

        # pick the right architecture if not set
        arch = get_endpoint_architecture()
        dtslogger.info(f"Target architecture automatically set to {arch}.")
        # compile image name
        # let's assume that if they specified an image name that we don't want to add the registry to it
        # this is need for dts exercises lab for example
        client = check_docker_environment()
        if parsed.image is None:
            REGISTRY = get_registry_to_use()
            image = REGISTRY + "/" + DEFAULT_IMAGE_FMT.format(get_distro_version(shell), arch)
        else:
            image = parsed.image

        # pull image
        if parsed.pull:
            pull_image_OLD(image, client)
        else:
            pull_if_not_exist(client, image)

        if parsed.image is None:
            try:
                ci = get_last_commit("duckietown", "dt-gui-tools", "ente")
            except Exception:
                dtslogger.warning("We could not check for updates, just a heads up.")
                ci = None

            if ci is not None:
                im = client.images.get(image)
                dtslogger.debug(json.dumps(im.labels, indent=2))
                sha = im.labels["org.duckietown.label.code.sha"]
                if ci.sha != sha:
                    n = datetime.now(tz=pytz.utc)
                    delta = n - ci.date
                    hours = delta.total_seconds() / (60 * 60)
                    if hours > 0.10:  # allow some minutes to pass before warning
                        msg = (
                            f"The image  {image} is not up to date.\n"
                            f"There was a new release {hours:.1f} hours ago.\n"
                            f'Use "dts desktop update" to update'
                        )
                        dtslogger.error(msg)
                    else:
                        dtslogger.warn(f"There is a new commit but too early to warn ({hours:.2f} hours). ")
                else:
                    dtslogger.debug(f"OK, local image and repo have sha {sha}")

        # create container name and make there is no name clash
        default_container_name = f"dts_gui_tools_{parsed.hostname}{'_vnc' if parsed.vnc else ''}"
        container_name = parsed.name or default_container_name
        remove_if_running(client, container_name)
        # setup common env
        env = {
            "VEHICLE_NAME": parsed.hostname,
            "ROS_MASTER": parsed.hostname,
            "ROS_MASTER_URI": "http://%s:11311" % robot_host,
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
                if "DISPLAY" in os.environ:
                    subprocess.call(["xhost", "+"])
                    env["DISPLAY"] = os.environ["DISPLAY"]
        # custom volumes
        if parsed.mount:
            src, dst, *_ = f"{parsed.mount}:{parsed.mount}".split(":")
            volumes[src] = {"bind": dst, "mode": "rw"}
        # print some stats
        dtslogger.debug(
            f"Running {container_name} with environment vars:\n\n"
            f"{json.dumps(env, sort_keys=True, indent=4)}\n"
        )

        # collect container config
        # docker arguments
        if not parsed.cmd_args:
            parsed.cmd_args = []
        cmd = f"dt-launcher-{'vnc' if parsed.vnc else parsed.launcher} "
        cmd += " ".join(parsed.cmd_args)
        params = {
            "image": image,
            "name": container_name,
            "environment": env,
            "stdin_open": True,
            "tty": True,
            "detach": True,
            "privileged": True,
            "remove": True,
            "stream": True,
            "command": cmd,
            "volumes": volumes,
            "network_mode": parsed.network,
            "ports": {},
        }

        # custom UID
        if parsed.uid is not None:
            params["user"] = f"{parsed.uid}"

        if parsed.nvidia:
            params["runtime"] = "nvidia"
            params["device_requests"] = [docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])]

        # custom wkdir
        if parsed.wkdir is not None:
            params["working_dir"] = f"{parsed.wkdir}"

        # custom ports
        for port in parsed.port:
            src, dst_type, *_ = port.split(":") * 2
            dst, ptype, *_ = dst_type.split("/") + ["tcp"]
            params["ports"][f"{dst}/{ptype}"] = ("0.0.0.0", int(src))

        if parsed.vnc and parsed.network != "host":
            params["ports"]["8087/tcp"] = ("0.0.0.0", 8087)

        # print some info
        if parsed.vnc:
            dtslogger.info("Running novnc. Navigate to http://localhost:8087/ in your browser. ")
        dtslogger.debug(
            f"Running container with configuration:\n\n" f"{json.dumps(params, sort_keys=True, indent=4)}\n"
        )
        # run the container
        client.containers.run(**params)

        # attach to the container with an interactive session
        if not parsed.detach:
            attach_cmd = "docker attach %s" % container_name
            try:
                start_command_in_subprocess(attach_cmd)
            except Exception as e:
                if not parsed.no_scream:
                    raise e
                else:
                    dtslogger.error(str(e))
            # ---
            dtslogger.info("Done. Have a nice day")
