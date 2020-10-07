import argparse
import datetime
import getpass
import json
import os
import socket
import sys
import time
import traceback

from docker import DockerClient

from challenges.challenges_cmd_utils import check_duckietown_challenges_version
from dt_shell import DTCommandAbs, dtslogger, UserError
from dt_shell.env_checks import check_docker_environment

from utils.docker_utils import replace_important_env_vars

EVALUATOR_IMAGE = "${AIDO_REGISTRY}/duckietown/dt-challenges-evaluator:daffy"

usage = """

## Basic usage

    Run the evaluator continuously:
    
        $ dts challenges evaluator
    
    This will evaluate your submissions preferentially, or others if yours are not available.
    
    
    Run the evaluator on a specific submission:
    
        $ dts challenges evaluator --submission ID
        
    This evaluates a specific submission.
    
    
    
    To re-evaluate after the first time, use --reset:
    
        $ dts challenges evaluator --submission ID --reset


## Advanced usage

    Pretend that you have a GPU:
    
        $ dts challenges evaluator --features 'gpu: 1'
        
    Use '--name' to distinguish multiple evaluators on the same machine.
    Otherwise the name is autogenerated.
    
        $ dts challenges evaluator --name Instance1 &
        $ dts challenges evaluator --name Instance2 &
        

"""

from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):

        check_duckietown_challenges_version()
        check_docker_environment()

        home = os.path.expanduser("~")
        prog = "dts challenges evaluator"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        group = parser.add_argument_group("Basic")

        group.add_argument("--submission", type=int, default=None, help="Run a specific submission.")
        group.add_argument(
            "--reset",
            dest="reset",
            action="store_true",
            default=False,
            help="(needs --submission) Re-evaluate the specific submission.",
        )

        group = parser.add_argument_group("Advanced")

        group.add_argument(
            "--no-watchtower",
            dest="no_watchtower",
            action="store_true",
            default=False,
            help="Disable starting of watchtower",
        )
        group.add_argument(
            "--no-pull",
            dest="no_pull",
            action="store_true",
            default=False,
            help="Disable pulling of containers",
        )
        group.add_argument(
            "--no-upload",
            dest="no_upload",
            action="store_true",
            default=False,
            help="Disable upload of artifacts",
        )
        group.add_argument(
            "--no-delete",
            dest="no_delete",
            action="store_true",
            default=False,
            help="Does not erase temporary files in /tmp/duckietown",
        )

        group.add_argument(
            "--image", help="Evaluator image to run", default=EVALUATOR_IMAGE,
        )

        group.add_argument("--name", default=None, help="Name for this evaluator")
        group.add_argument("--features", default=None, help="Pretend to be what you are not.")

        group.add_argument("--ipfs", action="store_true", default=False, help="Run with IPFS available")
        group.add_argument("--one", action="store_true", default=False, help="Only run 1 submission")

        # dtslogger.debug('args: %s' % args)
        parsed = parser.parse_args(args)

        machine_id = socket.gethostname()

        if parsed.name is None:
            container_name = "%s-%s" % (socket.gethostname(), os.getpid())
        else:
            container_name = parsed.name

        client = check_docker_environment()

        command = ["dt-challenges-evaluator"]

        if parsed.submission:
            command += ["--submission", str(parsed.submission)]

            if parsed.reset:
                command += ["--reset"]
        else:
            if not parsed.one:
                command += ["--continuous"]

        command += ["--name", container_name]
        command += ["--machine-id", machine_id]

        if parsed.no_upload:
            command += ["--no-upload"]
        if parsed.no_pull:
            command += ["--no-pull"]
        if parsed.no_delete:
            command += ["--no-delete"]

        if parsed.one:
            command += ["--one"]
        if parsed.features:
            dtslogger.debug("Passing features %r" % parsed.features)
            command += ["--features", parsed.features]
        mounts = []
        volumes = {
            "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
            os.path.join(home, ".dt-shell"): {"bind": "/root/.dt-shell", "mode": "ro"},
            "/tmp": {"bind": "/tmp", "mode": "rw"},
        }

        if parsed.ipfs:
            if not ipfs_available():
                msg = "IPFS not available/mounted correctly."
                raise UserError(msg)

            command += ["--ipfs"]
            # volumes['/ipfs'] = {'bind': '/ipfs', 'mode': 'ro'}
            from docker.types import Mount

            mount = Mount(type="bind", source="/ipfs", target="/ipfs", read_only=True)
            mounts.append(mount)
        env = {}

        UID = os.getuid()
        USERNAME = getpass.getuser()
        extra_environment = dict(username=USERNAME, uid=UID)

        env.update(extra_environment)
        if not parsed.no_watchtower:
            ensure_watchtower_active(client)

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

        image = replace_important_env_vars(parsed.image)
        dtslogger.info("Using evaluator image %s" % image)
        name, _, tag = image.rpartition(":")
        if not parsed.no_pull:
            dtslogger.info("Updating container %s" % image)
            make_sure_image_pulled(client, name, tag)
            # client.images.pull(name, tag)

        # noinspection PyBroadException
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

        dtslogger.info("Container command: %s" % " ".join(command))

        # add all the groups
        import grp

        group_add = [g.gr_gid for g in grp.getgrall() if USERNAME in g.gr_mem]

        client.containers.run(
            image,
            group_add=group_add,
            command=command,
            volumes=volumes,
            environment=env,
            mounts=mounts,
            network_mode="host",
            detach=True,
            name=container_name,
            tty=True,
        )
        last_log_timestamp = None

        while True:
            try:
                container = client.containers.get(container_name)
            except Exception as e:
                msg = "Cannot get container %s: %s" % (container_name, e)
                dtslogger.error(msg)
                dtslogger.info("Will wait.")
                time.sleep(5)
                continue

            dtslogger.info("status: %s" % container.status)
            if container.status == "exited":

                logs = ""
                for c in container.logs(stdout=True, stderr=True, stream=True, since=last_log_timestamp):
                    logs += c.decode("utf-8")
                    last_log_timestamp = datetime.datetime.now()

                tf = "evaluator.log"
                with open(tf, "w") as f:
                    f.write(logs)

                msg = "The container exited."
                msg += "\nLogs saved at %s" % tf
                dtslogger.info(msg)

                break

            try:
                if last_log_timestamp is not None:
                    print("since: %s" % last_log_timestamp.isoformat())
                for c0 in container.logs(
                    stdout=True, stderr=True, stream=True, since=last_log_timestamp, tail=0,  # follow=True,
                ):
                    c: bytes = c0
                    try:
                        s = c.decode("utf-8")
                    except:
                        s = c.decode("utf-8", errors="replace")
                    sys.stdout.write(s)
                    last_log_timestamp = datetime.datetime.now()

                time.sleep(3)
            except KeyboardInterrupt:
                dtslogger.info("Received CTRL-C. Stopping container...")
                container.stop()
                dtslogger.info("Removing container")
                container.remove()
                dtslogger.info("Container removed.")
                break
            except BaseException:
                s = traceback.format_exc()
                if "Read timed out" in s:
                    dtslogger.debug("(reattaching)")
                else:
                    dtslogger.error(s)
                    dtslogger.info("Will try to re-attach to container.")
                    time.sleep(3)


def ipfs_available():
    if os.path.exists("/ipfs"):
        fn = "/ipfs/QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG/readme"
        try:
            d = open(fn).read()
        except:
            msg = f"Could not open an IPFS file: {traceback.format_exc()}"
            dtslogger.warning(msg)
            return False

        if "Hello" in d:
            return True
        else:
            dtslogger.warning(d)
            return False
    else:
        return False


def make_sure_image_pulled(client: DockerClient, repository: str, tag: str = None) -> None:
    dtslogger.info(f"Pulling tag {repository!r} tag {tag!r}")
    i = 0
    cols = 80
    for outs in client.api.pull(repository=repository, tag=tag, stream=True):
        try:
            outs2 = outs.decode().strip()
            # print(outs2.__repr__())
            out = json.loads(outs2)
            s = out.get("status", "")
            s = "%d: %s" % (i, s)
            i += 1
            s = s.ljust(cols)
            sys.stderr.write(s + "\r")
        except:
            pass
    sys.stderr.write("\n")
    dtslogger.info("pull complete")


def ensure_watchtower_active(client: DockerClient):
    containers = client.containers.list(filters=dict(status="running"))
    watchtower_tag = "v2tec/watchtower"
    found = None
    for c in containers:
        tags = c.image.attrs["RepoTags"]
        for t in tags:
            if watchtower_tag in t:
                found = c

    make_sure_image_pulled(client, watchtower_tag, "latest")

    if found is not None:
        dtslogger.info("I found watchtower active.")
    else:

        dtslogger.info("Starting watchtower")
        env = {}
        volumes = {
            "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
            # os.path.join(home, '.dt-shell'): {'bind': '/root/.dt-shell', 'mode': 'ro'}
        }

        container = client.containers.run(
            watchtower_tag, volumes=volumes, environment=env, network_mode="host", detach=True,
        )
        dtslogger.info("Detached: %s" % container)


def indent(s, prefix, first=None):
    s = str(s)
    assert isinstance(prefix, str)
    lines = s.split("\n")
    if not lines:
        return ""

    if first is None:
        first = prefix

    m = max(len(prefix), len(first))

    prefix = " " * (m - len(prefix)) + prefix
    first = " " * (m - len(first)) + first

    # differnet first prefix
    res = ["%s%s" % (prefix, line.rstrip()) for line in lines]
    res[0] = "%s%s" % (first, lines[0].rstrip())
    return "\n".join(res)