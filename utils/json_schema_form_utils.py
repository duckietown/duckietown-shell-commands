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

from utils.assets_utils import load_schema, get_schema_icon_filepath, get_schema_html_filepath
from utils.docker_utils import get_registry_to_use, get_endpoint_architecture
from utils.misc_utils import indent_block, pretty_json

UTILITY_DASHBORD_IMAGE = "{registry}/duckietown/jsonschema-form:{distro}-{arch}"
UTILITY_DASHBORD_PORT = "8080"


def open_form_from_schema(shell: DTShell, name: str, version: str, title: str, **kwargs) -> Optional[dict]:
    schema: dict = load_schema(name, version)
    icon: Optional[str] = get_schema_icon_filepath(name, version)
    header: Optional[str] = get_schema_html_filepath(name, version, "header.html")
    footer: Optional[str] = get_schema_html_filepath(name, version, "footer.html")
    return open_form(
        shell, title, schema, icon_fpath=icon, header_fpath=header, footer_fpath=footer, **kwargs
    )


def open_form(
    shell: DTShell,
    title: str,
    schema: dict,
    *,
    subtitle: str = "",
    completion_message: Optional[str] = None,
    icon_fpath: Optional[str] = None,
    header_fpath: Optional[str] = None,
    footer_fpath: Optional[str] = None,
) -> Optional[dict]:
    values: Optional[dict] = None
    distro: str = shell.profile.distro.name
    registry: str = get_registry_to_use()
    # copy schema object
    data: dict = copy.deepcopy(schema)
    # add page info
    data["page"] = {"title": title, "subtitle": subtitle}
    # completion message
    if completion_message:
        data["page"]["completion_message"] = completion_message
    # open temporary input directory
    with tempfile.TemporaryDirectory() as input_dir:
        data_fpath = os.path.join(input_dir, "schema.json")
        # dump data
        with open(data_fpath, "wt") as fout:
            json.dump(data, fout)
        # add icon (if given)
        if icon_fpath is not None:
            if not os.path.exists(icon_fpath):
                raise FileNotFoundError(icon_fpath)
            if not icon_fpath.endswith(".png"):
                raise ValueError("Only PNG icons are supported")
            icon_dst_fpath = os.path.join(input_dir, "icon.png")
            dtslogger.debug(f"Copying [{icon_fpath}] -> [{icon_dst_fpath}]...")
            shutil.copyfile(icon_fpath, icon_dst_fpath)
        # add header and footer HTML
        for role, html_fpath in {"header": header_fpath, "footer": footer_fpath}.items():
            if html_fpath is None:
                continue
            if not os.path.exists(html_fpath):
                raise FileNotFoundError(html_fpath)
            assert html_fpath.endswith(".html")
            html_dst_fpath = os.path.join(input_dir, f"{role}.html")
            dtslogger.debug(f"Copying [{html_fpath}] -> [{html_dst_fpath}]...")
            shutil.copyfile(html_fpath, html_dst_fpath)
        # open temporary output directory
        with tempfile.TemporaryDirectory() as output_dir:
            # open connection to Docker engine
            docker = DockerClient()
            # pick the right architecture
            dtslogger.info("Retrieving info about Docker endpoint...")
            arch: str = get_endpoint_architecture()
            dtslogger.info(f"Target architecture automatically set to {arch}.")
            # compile image name
            image: str = UTILITY_DASHBORD_IMAGE.format(registry=registry, distro=distro, arch=arch)
            dtslogger.debug(f"Using image '{image}'...")
            # configure image
            container_cfg = {
                "image": image,
                "volumes": [
                    (input_dir, "/input", "ro"),
                    (output_dir, "/output", "rw"),
                ],
                "publish": [(f"127.0.0.1:0", UTILITY_DASHBORD_PORT, "tcp")],
                "detach": True,
            }
            dtslogger.debug(
                f"Creating container with the following configuration:\n"
                f"{indent_block(json.dumps(container_cfg, indent=4, sort_keys=True))}"
            )
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
            browser = SimpleWindowBrowser()
            browser.open(url)
            user_terminated: bool = False
            container_name: str = container.name

            # register SIGINT handler
            def handler(_, __):
                dtslogger.info("Interrupting...")
                nonlocal user_terminated
                user_terminated = True
                container.kill()

            original_handler = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, handler)

            # wait for the container to finish
            try:
                container.execute(["sleep", "infinity"])
            except DockerException as e:
                exit_code = container.state.exit_code
                dtslogger.debug(f"Container '{container_name}' exited with code {exit_code}")
                # remove SIGINT handler
                signal.signal(signal.SIGINT, original_handler)
                # remove container
                container.remove()
                # parse exit code
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
                        dtslogger.debug(
                            f"Container '{container_name}' returned values:\n"
                            f"{pretty_json(values, indent=4)}"
                        )
                elif not user_terminated:
                    raise e
            # user terminated
            if user_terminated:
                exit(0)
                dtslogger.info("Done")
    # ---
    return values


class SimpleWindowBrowser:
    def __init__(self):
        self._browser = webbrowser.get()
        # with Chrome, we can use --app to open a simple window
        if isinstance(self._browser, webbrowser.Chrome):
            self._browser.remote_args = ["--app=%s"]

    def open(self, url: str) -> bool:
        try:
            return self._browser.open(url)
        except:
            webbrowser.open(url)
