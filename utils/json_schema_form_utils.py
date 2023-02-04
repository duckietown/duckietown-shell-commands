import copy
import json
import os.path
import shutil
import signal
import tempfile
import time
import webbrowser
from typing import Optional

from dockertown import DockerClient, Container, DockerException
from dt_shell import DTShell, dtslogger

from utils.docker_utils import get_registry_to_use
from utils.duckietown_utils import get_distro_version
from utils.misc_utils import indent_block

UTILITY_DASHBORD_IMAGE = "{registry}/duckietown/jsonschema-form:{distro}"
UTILITY_DASHBORD_PORT = "8080"


def open_form(
        shell: DTShell,
        title: str,
        schema: dict,
        subtitle: str = "",
        icon: Optional[str] = None,
    ) -> Optional[dict]:
    values: Optional[dict] = None
    distro: str = get_distro_version(shell)
    registry: str = get_registry_to_use()
    image: str = UTILITY_DASHBORD_IMAGE.format(registry=registry, distro=distro)
    dtslogger.debug(f"Using image '{image}'...")
    # copy schema object
    data: dict = copy.deepcopy(schema)
    # add page info
    data["page"] = {
        "title": title,
        "subtitle": subtitle
    }
    # open temporary input directory
    with tempfile.TemporaryDirectory() as input_dir:
        data_fpath = os.path.join(input_dir, "schema.json")
        # dump data
        with open(data_fpath, "wt") as fout:
            json.dump(data, fout)
        # add icon (if given)
        if icon is not None:
            if not os.path.exists(icon):
                raise FileNotFoundError(icon)
            if not icon.endswith(".png"):
                raise ValueError("Only PNG icons are supported")
            icon_fpath = os.path.join(input_dir, "icon.png")
            shutil.copyfile(icon, icon_fpath)
        # open temporary output directory
        with tempfile.TemporaryDirectory() as output_dir:
            # open connection to Docker engine
            docker = DockerClient()
            # configure image
            container_cfg = {
                "image": image,
                "volumes": [
                    (input_dir, "/input", "ro"),
                    (output_dir, "/output", "rw"),
                ],
                "publish": [(f"127.0.0.1:0", UTILITY_DASHBORD_PORT, "tcp")],
                "remove": True,
                "detach": True,
            }
            dtslogger.debug(f"Creating container with the following configuration:\n"
                            f"{indent_block(json.dumps(container_cfg, indent=4, sort_keys=True))}")
            container: Container = docker.container.run(**container_cfg)
            # get the IP address to the container
            port: str = container.network_settings.ports[f"{UTILITY_DASHBORD_PORT}/tcp"][0]["HostPort"]
            url: str = f"http://localhost:{port}/form"
            # print out URL
            bar: str = "=" * len(url)
            spc: str = " " * len(url)
            dtslogger.info(
                f"\n\n"
                f"====================={bar}===========================================\n"
                f"|                    {spc}                                          |\n"
                f"|    A page in the browser should open automatically.{spc}          |\n"
                f"|    Alternatively, you can click on:{spc}                          |\n"
                f"|                    {spc}                                          |\n"
                f"|        >   {url}                                                  |\n"
                f"|                    {spc}                                          |\n"
                f"====================={bar}===========================================\n"
            )
            # open web browser tab, give the web browser a second to get up
            time.sleep(1)
            webbrowser.open_new_tab(url)
            user_terminated: bool = False

            # register SIGINT handler
            def handler(_, __):
                nonlocal user_terminated
                user_terminated = True
                container.kill()

            signal.signal(signal.SIGINT, handler)

            # wait for the container to finish
            try:
                container.execute(["sleep", "infinity"])
            except DockerException as e:
                exit_code = container.state.exit_code
                dtslogger.debug(f"Container exited with code {exit_code}")
                if exit_code == 99:
                    # 99 means generic error
                    raise e
                elif exit_code == 10:
                    # 10 means the user cancelled from the browser
                    pass
                elif exit_code == 0:
                    # 0 means the user completed the form
                    values_fpath = os.path.join(output_dir, "values.json")
                    assert os.path.exists(values_fpath)
                    with open(values_fpath, "rt") as fin:
                        values = json.load(fin)
                elif not user_terminated:
                    raise e
            # user terminated
            if user_terminated:
                exit(0)
    # ---
    return values
