import argparse
import json
import os
import subprocess

from dt_shell import DTCommandAbs, dtslogger

from dtproject import DTProject

from utils.docker_utils import (
    DEFAULT_MACHINE,
    get_endpoint_architecture,
    get_registry_to_use,
)

DEFAULT_MOUNTS = ["/var/run/avahi-daemon/socket", "/data"]
DEFAULT_NETWORK_MODE = "host"
DEFAULT_REMOTE_USER = "duckie"
DEFAULT_REMOTE_SYNC_LOCATION = "/code"

DEFAULT_TRUE = object()

DEVCONTAINER_TEMPLATE = {
    "name": "Duckietown Dev Container",
    "image": "${{localEnv:DOCKER_REGISTRY}}/duckietown/${{localWorkspaceFolderBasename}}:ente-amd64",  # Replace with the actual Docker image tag
    "workspaceFolder": f"{DEFAULT_REMOTE_SYNC_LOCATION}/src/${{localWorkspaceFolderBasename}}",
    "mounts": [f"source={m},target={m},type=bind" for m in DEFAULT_MOUNTS],
    "containerEnv": {},
    "runArgs": [
        "-it",
        f"--net={DEFAULT_NETWORK_MODE}",
    ],
    "customizations": {
        "vscode": {
            "settings":{
                "ros.distro": "noetic"
            },
            "extensions": [
                "ms-iot.vscode-ros",
                "ms-python.python",
                "ms-vscode.cpptools"
            ]
        }
    }
}

class DTCommand(DTCommandAbs):
    help = "Runs the current project"
    
    @staticmethod
    def command(shell, args: list):
        # configure arguments
        parser = argparse.ArgumentParser()

        parser.add_argument(
            "-R",
            "--ros",
            default=None,
            help="Hostname of the machine hosting the ROS Master node",
        )
        parser.add_argument("-n", "--name", default=None, help="Name of the container")

        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the project to run"
        )

        parser.add_argument(
            "-u",
            "--username",
            default="duckietown",
            help="The docker registry username that owns the Docker image",
        )

        parser.add_argument(
            "--net",
            "--network_mode",
            dest="network_mode",
            default=DEFAULT_NETWORK_MODE,
            type=str,
            help="Docker network mode",
        )

        parser.add_argument("docker_args", nargs="*", default=[])

        # Create a dictionary for the devcontainer.json from the template

        # add a fake positional argument to avoid missing the first argument starting with `-`
        try:
            idx = args.index("--")
            args = args[:idx] + ["--", "--fake"] + args[idx + 1:]
        except ValueError:
            pass
        # parse arguments
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        parsed.workdir = os.path.abspath(parsed.workdir)

        dtslogger.info("Project workspace: {}".format(parsed.workdir))
        # show info about project
        shell.include.devel.info.command(shell, args)

        # get info about project
        project = DTProject(parsed.workdir)

        # registry
        registry_to_use = get_registry_to_use()

        # pick the right architecture
        arch = get_endpoint_architecture(DEFAULT_MACHINE)
        dtslogger.info(f"Target architecture automatically set to {arch}.")

        # get the module configuration
        # noinspection PyListCreation
        module_configuration_args = []
        # apply default module configuration
        module_configuration_args.append(f"--net={parsed.network_mode}")
        
        # Set docker network mode TODO

        if parsed.ros is not None:
            # Add VEHICLE_NAME as an environment variable of the container
            DEVCONTAINER_TEMPLATE["containerEnv"]["VEHICLE_NAME"] = parsed.ros
        
        # add default mount points
        for mountpoint in DEFAULT_MOUNTS:
            # check if the mountpoint exists
            if not os.path.exists(mountpoint):
                dtslogger.warning(
                    f"The mountpoint '{mountpoint}' does not exist. "
                    f"This can create issues inside the container."
                )
                continue

        # mount source code (if requested)
        projects_to_mount = [parsed.workdir]

        # create mount points definitions
        for project_path in projects_to_mount:
            # make sure that the project exists
            if not os.path.isdir(project_path):
                dtslogger.error(f"The path '{project_path}' is not a Duckietown project")
            # get project info
            proj = DTProject(project_path)
            
            root =  proj.path
            # get local and remote paths to code
            local_srcs, destination_srcs = proj.code_paths(root)
            # compile mountpoints
            for local_src, destination_src in zip(local_srcs, destination_srcs):
                # Append to the list of mount points in DEVCONTAINER_TEMPLATE
                DEVCONTAINER_TEMPLATE["mounts"].append(f"source={local_src},target={destination_src},type=bind")

            # get local and remote paths to launchers
            local_launchs, destination_launchs = proj.launch_paths(root)
            if isinstance(local_launchs, str):
                local_launchs = [local_launchs]
                destination_launchs = [destination_launchs]
            # compile mountpoints
            for local_launch, destination_launch in zip(local_launchs, destination_launchs):
                # Append to the list of mount points in DEVCONTAINER_TEMPLATE
                DEVCONTAINER_TEMPLATE["mounts"].append(f"source={local_launch},target={destination_launch},type=bind")
                # make sure the launchers are executable
                try:
                    _run_cmd(["chmod", "a+x", os.path.join(local_launch, "*")], shell=True)
                except Exception:
                    dtslogger.warning("An error occurred while making the launchers executable. "
                                        "Things might not work as expected.")

        # create image name
        image = project.image(
            arch=arch,
            registry=registry_to_use,
            owner=parsed.username,
            version=project.distro,
        )

        DEVCONTAINER_TEMPLATE["image"] = image

        # docker arguments
        if not parsed.docker_args:
            parsed.docker_args = []

        # escape spaces in arguments
        parsed.docker_args = [a.replace(" ", "\\ ") for a in parsed.docker_args]

        DEVCONTAINER_TEMPLATE["runArgs"].extend(parsed.docker_args)

        # Write DEVCONTAINER_TEMPLATE to .devcontainer/devcontainer.json
        output_file_path = ".devcontainer/devcontainer.json"

        # Create .devcontainer folder
        if not os.path.exists('.devcontainer') and not os.path.isdir('.devcontainer'):
            os.mkdir('.devcontainer')
        with open(output_file_path, 'w') as json_file:
            json.dump(DEVCONTAINER_TEMPLATE, json_file, indent=4,)

        dtslogger.info(f'DEVCONTAINER_TEMPLATE written to {output_file_path}')
        dtslogger.info("You can now open the devcontainer in your favorite editor")

        # Open the devcontainer in VSCode
        try:
            # _run_cmd(["devcontainer", "build", parsed.workdir], shell=True)
            _run_cmd(["dts", "devel", "build"], shell=True)
            _run_cmd(["devcontainer", "open"], shell=True)
        except subprocess.CalledProcessError as e:
            # Handle the exception and output a human-friendly message
            print(f"An error occurred while running 'devcontainer open': {e}")
            print(f"Return code: {e.returncode}")
            # You can add more details as needed
            if e.returncode == 127:
                print("The 'devcontainer' command is not installed. Please install it by running:\n\n")
                print("     sudo npm install -g @devcontainers/cli")

    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(
        cmd, get_output=False, print_output=False, suppress_errors=False, shell=False, return_exitcode=False
):
    if shell and isinstance(cmd, (list, tuple)):
        cmd = " ".join([str(s) for s in cmd])
    dtslogger.debug("$ %s" % cmd)
    if get_output:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=shell)
        proc.wait()
        if proc.returncode != 0:
            if not suppress_errors:
                msg = "The command {} returned exit code {}".format(cmd, proc.returncode)
                dtslogger.error(msg)
                raise RuntimeError(msg)
        out = proc.stdout.read().decode("utf-8").rstrip()
        if print_output:
            print(out)
        return out
    else:
        if return_exitcode:
            res = subprocess.run(cmd, shell=shell)
            return res.returncode
        else:
            try:
                subprocess.check_call(cmd, shell=shell)
            except subprocess.CalledProcessError as e:
                if not suppress_errors:
                    raise e
