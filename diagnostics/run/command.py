import sys
import json
import argparse
import subprocess

from utils.duckietown_utils import get_robot_types, get_distro_version
from utils.avahi_utils import wait_for_service
from utils.dtproject_utils import CANONICAL_ARCH
from utils.docker_utils import DEFAULT_MACHINE

from dt_shell import DTCommandAbs, dtslogger

DEFAULT_TARGET = DEFAULT_MACHINE
DOCKER_SOCKET = "/var/run/docker.sock"
LOG_API_DEFAULT_DATABASE = "db_log_default"
LOG_DEFAULT_SUBGROUP = "default"
LOG_DEFAULT_APP_ID = "duckietown_user_443_dts_daffy_diagnostics_run"
LOG_DEFAULT_APP_SECRET = "VvXITEzPuaGwdXC03vCeHnYYjqUOoEc9ZZIJu8oO9UacID3B"
AVAHI_SOCKET_FILE = "/var/run/avahi-daemon/socket"

LOG_API_PROTOCOL = "https"
LOG_API_HOSTNAME = "dashboard.duckietown.org"
LOG_API_VERSION = "1.0"

DIAGNOSTICS_IMAGE = "duckietown/dt-system-monitor:{version}-{arch}"


class DTCommand(DTCommandAbs):

    help = "Runs a diagnostics on a Duckietown device"

    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        supported_robot_types = ["auto"] + get_robot_types()
        parser.add_argument(
            "-H",
            "--machine",
            default=DEFAULT_MACHINE,
            help="Docker socket or hostname where to run the image "
            + "(NOTE: this is not the target of the diagnostics)",
        )
        parser.add_argument(
            "-T", "--target", default=DEFAULT_TARGET, help="Specify a Docker endpoint to monitor"
        )
        parser.add_argument(
            "--type",
            default="auto",
            choices=supported_robot_types,
            help="Specify a device type (e.g., duckiebot, watchtower)",
        )
        parser.add_argument(
            "--app-id",
            type=str,
            default=None,
            help="ID of the API App used to authenticate the push to the server. "
            + "Must have access to the 'data/set' API endpoint",
        )
        parser.add_argument(
            "--app-secret",
            type=str,
            default=None,
            help="Secret of the API App used to authenticate the push to the server",
        )
        parser.add_argument(
            "-D",
            "--database",
            default=LOG_API_DEFAULT_DATABASE,
            type=str,
            help="Name of the logging database. Must be an existing database.",
        )
        parser.add_argument(
            "-G", "--group", required=True, type=str, help="Name of the experiment (e.g., new_fan)"
        )
        parser.add_argument(
            "-S",
            "--subgroup",
            default=LOG_DEFAULT_SUBGROUP,
            type=str,
            help="Name of the test within the experiment (e.g., fan_model_X)",
        )
        parser.add_argument(
            "-d",
            "--duration",
            type=int,
            required=True,
            help="Length of the analysis in seconds, (-1: indefinite)",
        )
        parser.add_argument(
            "-F",
            "--filter",
            action="append",
            default=[],
            help="Specify regexes used to filter the monitored containers",
        )
        parser.add_argument(
            "-m", "--notes", default="(empty)", type=str, help="Custom notes to attach to the log"
        )
        parser.add_argument(
            "--no-pull",
            action="store_true",
            default=False,
            help="Whether we do not try to pull the diagnostics image before " "running the experiment",
        )
        parser.add_argument("--debug", action="store_true", default=False, help="Run in debug mode")
        parser.add_argument(
            "-vv", "--verbose", dest="verbose", action="store_true", default=False, help="Run in verbose mode"
        )
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        if parsed.app_id is None:
            parsed.app_id = LOG_DEFAULT_APP_ID
        if parsed.app_secret is None:
            parsed.app_secret = LOG_DEFAULT_APP_SECRET
        # we can't get the type if we are running locally
        fetch_type_from = None
        if parsed.machine == DEFAULT_MACHINE and parsed.target == DEFAULT_TARGET and parsed.type == "auto":
            dtslogger.error(
                "You have to specify a device type (--type) when the target " + "is the local Docker endpoint"
            )
            sys.exit(1)
        if parsed.machine == DEFAULT_MACHINE and parsed.target != DEFAULT_TARGET:
            fetch_type_from = parsed.target
        if parsed.machine != DEFAULT_MACHINE and parsed.target == DEFAULT_TARGET:
            fetch_type_from = parsed.machine
        # get info about docker endpoint
        dtslogger.info("Retrieving info about Docker endpoint...")
        epoint = _run_cmd(
            ["docker", "-H=%s" % parsed.machine, "info", "--format", "{{json .}}"], get_output=True
        )
        epoint = json.loads(epoint)
        if "ServerErrors" in epoint:
            dtslogger.error("\n".join(epoint["ServerErrors"]))
            return
        image_arch = CANONICAL_ARCH[epoint["Architecture"]]
        # get robot_type
        if parsed.type == "auto":
            # retrieve robot type from device
            dtslogger.info(f'Waiting for device "{fetch_type_from}"...')
            hostname = fetch_type_from.replace(".local", "")
            _, _, data = wait_for_service("DT::ROBOT_TYPE", hostname)
            parsed.type = data["type"]
            dtslogger.info(f'Detected device type is "{parsed.type}".')
        else:
            dtslogger.info(f'Device type forced to "{parsed.type}".')
        # create options
        options = [
            "-it",
            "--rm",
            "--net=host",
            "--volume={avahi_socket:s}:{avahi_socket:s}".format(avahi_socket=AVAHI_SOCKET_FILE),
        ]
        # create image name
        image = DIAGNOSTICS_IMAGE.format(version=get_distro_version(shell), arch=image_arch)
        # mount option
        if parsed.target == "unix://" + DOCKER_SOCKET:
            options += ["-v", "{:s}:{:s}".format(DOCKER_SOCKET, DOCKER_SOCKET)]
        # pass arguments using env variables
        options += ["-e", "LOG_API_PROTOCOL=" + LOG_API_PROTOCOL]
        options += ["-e", "LOG_API_HOSTNAME=" + LOG_API_HOSTNAME]
        options += ["-e", "LOG_API_VERSION=" + LOG_API_VERSION]
        # pass notes as env variable to better handle spaces and symbols
        options += ["-e", 'LOG_NOTES="%s"' % parsed.notes]
        # pass cli arguments
        cli_args = ["--"]
        cli_args += ["--target", parsed.target]
        cli_args += ["--type", parsed.type]
        cli_args += ["--app-id", parsed.app_id]
        cli_args += ["--app-secret", parsed.app_secret]
        cli_args += ["--database", parsed.database]
        cli_args += ["--filter", ",".join(parsed.filter)]
        cli_args += ["--group", parsed.group]
        cli_args += ["--subgroup", parsed.subgroup]
        cli_args += ["--duration", str(parsed.duration)]
        if parsed.debug:
            cli_args += ["--debug"]
        if parsed.verbose:
            cli_args += ["--verbose"]
        # container name
        container_name = "dts-run-diagnostics-system-monitor"
        options += ["--name", container_name]
        # update image
        if not parsed.no_pull:
            dtslogger.info(f'Attempting to update image "{image}"...')
            _run_cmd(["docker", "-H=%s" % parsed.machine, "pull", image])
        # run
        dtslogger.info(f'Running monitor on "{parsed.machine}", monitoring "{parsed.target}".')
        _run_cmd(["docker", "-H=%s" % parsed.machine, "run"] + options + [image] + cli_args)

    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(cmd, shell=False, get_output=False):
    if shell:
        cmd = " ".join([str(s) for s in cmd])
    dtslogger.debug("$ %s" % cmd)
    if get_output:
        return subprocess.check_output(cmd, shell=shell)
    else:
        subprocess.check_call(cmd, shell=shell)
