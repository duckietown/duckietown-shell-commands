import os
import re
import copy
import json
import yaml
import subprocess
import requests
import docker

from docker.errors import APIError, ImageNotFound
from types import SimpleNamespace

from dt_shell import UserError
from utils.docker_utils import sanitize_docker_baseurl


REQUIRED_METADATA_KEYS = {"*": ["TYPE_VERSION"], "1": ["TYPE", "VERSION"], "2": ["TYPE", "VERSION"]}

CANONICAL_ARCH = {
    "arm": "arm32v7",
    "arm32v7": "arm32v7",
    "armv7l": "arm32v7",
    "armhf": "arm32v7",
    "x64": "amd64",
    "x86_64": "amd64",
    "amd64": "amd64",
    "Intel 64": "amd64",

    # TODO: @afdaniele. Forward arm64v8 -> arm32v7 until the arm64v8 family of images is fixed
    # "arm64": "arm64v8",
    # "arm64v8": "arm64v8",
    # "armv8": "arm64v8",
    # "aarch64": "arm64v8",

    "arm64": "arm32v7",
    "arm64v8": "arm32v7",
    "armv8": "arm32v7",
    "aarch64": "arm32v7",

    "FAKE": "arm64v8"
}

BUILD_COMPATIBILITY_MAP = {
    "arm32v7": ["arm32v7"],
    "arm64v8": ["arm32v7", "arm64v8"],
    "amd64": ["amd64"]
}

DOCKER_LABEL_DOMAIN = "org.duckietown.label"

CLOUD_BUILDERS = {
    "arm32v7": "ec2-3-215-236-113.compute-1.amazonaws.com",
    "arm64v8": "ec2-3-215-236-113.compute-1.amazonaws.com",
    "amd64": "ec2-3-210-65-73.compute-1.amazonaws.com",
}

TEMPLATE_TO_SRC = {
    "template-basic": {
        "1": lambda repo: ("code", "/packages/{:s}/".format(repo)),
        "2": lambda repo: ("", "/code/{:s}/".format(repo)),
    },
    "template-ros": {
        "1": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo)),
        "2": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo)),
    },
    "template-core": {
        "1": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo)),
        "2": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo)),
    },
    "template-exercise": {
        "1": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo))
    },
}

TEMPLATE_TO_LAUNCHFILE = {
    "template-basic": {
        "1": lambda repo: ("launch.sh", "/launch/{:s}/launch.sh".format(repo)),
        "2": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
    },
    "template-ros": {
        "1": lambda repo: ("launch.sh", "/launch/{:s}/launch.sh".format(repo)),
        "2": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
    },
    "template-core": {
        "1": lambda repo: ("launch.sh", "/launch/{:s}/launch.sh".format(repo)),
        "2": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
    },
    "template-exercise": {
        "1": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
    },
}

DISTRO_KEY = {"1": "MAJOR", "2": "DISTRO"}

DOCKER_HUB_API_URL = {
    "token": "https://auth.docker.io/token?scope=repository:{image}:pull&service=registry.docker.io",
    "digest": "https://registry-1.docker.io/v2/{image}/manifests/{tag}",
    "inspect": "https://registry-1.docker.io/v2/{image}/blobs/{digest}",
}


class DTProject:

    def __init__(self, path: str):
        self._adapters = []
        self._repository = None
        # use `fs` adapter by default
        self._path = os.path.abspath(path)
        self._adapters.append('fs')
        # use `dtproject` adapter (required)
        self._project_info = self._get_project_info(self._path)
        self._type = self._project_info["TYPE"]
        self._type_version = self._project_info["TYPE_VERSION"]
        self._version = self._project_info["VERSION"]
        self._adapters.append('dtproject')
        # use `git` adapter if available
        if os.path.isdir(os.path.join(self._path, '.git')):
            repo_info = self._get_repo_info(self._path)
            self._repository = SimpleNamespace(
                name=repo_info["REPOSITORY"],
                sha=repo_info["SHA"],
                detached=repo_info["BRANCH"] == "HEAD",
                branch=repo_info["BRANCH"],
                head_version=repo_info["VERSION.HEAD"],
                closest_version=repo_info["VERSION.CLOSEST"],
                repository_url=repo_info["ORIGIN.URL"],
                repository_page=repo_info["ORIGIN.HTTPS.URL"],
                index_nmodified=repo_info["INDEX_NUM_MODIFIED"],
                index_nadded=repo_info["INDEX_NUM_ADDED"],
            )
            self._adapters.append('git')

    @property
    def path(self):
        return self._path

    @property
    def name(self):
        return self._repository.name if self._repository else os.path.basename(self.path)

    @property
    def type(self):
        return self._type

    @property
    def type_version(self):
        return self._type_version

    @property
    def distro(self):
        return self._repository.branch.split("-")[0] if self._repository else 'latest'

    @property
    def version(self):
        return self._version

    @property
    def head_version(self):
        return self._repository.head_version if self._repository else 'latest'

    @property
    def closest_version(self):
        return self._repository.closest_version if self._repository else 'latest'

    @property
    def version_name(self):
        return self._repository.branch if self._repository else 'latest'

    @property
    def url(self):
        return self._repository.repository_page if self._repository else None

    @property
    def sha(self):
        return self._repository.sha if self._repository else 'ND'

    @property
    def adapters(self):
        return copy.copy(self._adapters)

    def is_release(self):
        return self.head_version != "ND" if self._repository else False

    def is_clean(self):
        if self._repository:
            return (self._repository.index_nmodified + self._repository.index_nadded) == 0
        return True

    def is_dirty(self):
        return not self.is_clean()

    def is_detached(self):
        return self._repository.detached if self._repository else False

    def image(self, arch: str, loop: bool = False, docs: bool = False, owner: str = "duckietown") -> str:
        assert_canonical_arch(arch)
        loop = "-LOOP" if loop else ""
        docs = "-docs" if docs else ""
        version = re.sub(r"[^\w\-.]", "-", self.version_name)
        return f"{owner}/{self.name}:{version}{loop}{docs}-{arch}"

    def image_release(self, arch: str, docs: bool = False, owner: str = "duckietown") -> str:
        if not self.is_release():
            raise ValueError("The project repository is not in a release state")
        assert_canonical_arch(arch)
        docs = "-docs" if docs else ""
        version = re.sub(r"[^\w\-.]", "-", self.head_version)
        return f"{owner}/{self.name}:{version}{docs}-{arch}"

    def configurations(self) -> dict:
        if int(self._type_version) < 2:
            raise NotImplementedError(
                "Project configurations were introduced with template "
                "types v2. Your project does not support them."
            )
        # ---
        configurations = {}
        if self._type_version == "2":
            configurations_file = os.path.join(self._path, "configurations.yaml")
            if os.path.isfile(configurations_file):
                configurations = _parse_configurations(configurations_file)
        # ---
        return configurations

    def configuration(self, name: str) -> dict:
        configurations = self.configurations()
        if name not in configurations:
            raise KeyError(f"Configuration with name '{name}' not found.")
        return configurations[name]

    def code_paths(self):
        # make sure we support this project version
        if self.type not in TEMPLATE_TO_SRC or self.type_version not in TEMPLATE_TO_SRC[self.type]:
            raise ValueError(
                "Template {:s} v{:s} for project {:s} is not supported".format(
                    self.type, self.type_version, self.path
                )
            )
        # ---
        return TEMPLATE_TO_SRC[self.type][self.type_version](self.name)

    def launch_paths(self):
        # make sure we support this project version
        if (
            self.type not in TEMPLATE_TO_LAUNCHFILE
            or self.type_version not in TEMPLATE_TO_LAUNCHFILE[self.type]
        ):
            raise ValueError(
                "Template {:s} v{:s} for project {:s} is not supported".format(
                    self.type, self.type_version, self.path
                )
            )
        # ---
        return TEMPLATE_TO_LAUNCHFILE[self.type][self.type_version](self.name)

    def image_metadata(self, endpoint, arch: str, owner: str = "duckietown"):
        client = _docker_client(endpoint)
        image_name = self.image(arch, owner=owner)
        try:
            image = client.images.get(image_name)
            return image.attrs
        except (APIError, ImageNotFound):
            return None

    def image_labels(self, endpoint, arch: str, owner: str = "duckietown"):
        client = _docker_client(endpoint)
        image_name = self.image(arch, owner=owner)
        try:
            image = client.images.get(image_name)
            return image.labels
        except (APIError, ImageNotFound):
            return None

    def remote_image_metadata(self, arch: str, owner: str = "duckietown"):
        assert_canonical_arch(arch)
        image = f"{owner}/{self.name}"
        tag = f"{self.version_name}-{arch}"
        return self.inspect_remote_image(image, tag)

    @staticmethod
    def _get_project_info(path):
        metafile = os.path.join(path, ".dtproject")
        # if the file '.dtproject' is missing
        if not os.path.exists(metafile):
            msg = "The path '%s' does not appear to be a Duckietown project. " % (metafile)
            msg += "\nThe metadata file '.dtproject' is missing."
            raise UserError(msg)
        # load '.dtproject'
        with open(metafile, "rt") as metastream:
            metadata = metastream.readlines()
        # empty metadata?
        if not metadata:
            msg = "The metadata file '.dtproject' is empty."
            raise UserError(msg)
        # parse metadata
        metadata = {p[0].strip().upper(): p[1].strip() for p in [line.split("=") for line in metadata]}
        # look for version-agnostic keys
        for key in REQUIRED_METADATA_KEYS["*"]:
            if key not in metadata:
                msg = "The metadata file '.dtproject' does not contain the key '%s'." % key
                raise UserError(msg)
        # validate version
        version = metadata["TYPE_VERSION"]
        if version == "*" or version not in REQUIRED_METADATA_KEYS:
            msg = "The project version %s is not supported." % version
            raise UserError(msg)
        # validate metadata
        for key in REQUIRED_METADATA_KEYS[version]:
            if key not in metadata:
                msg = "The metadata file '.dtproject' does not contain the key '%s'." % key
                raise UserError(msg)
        # metadata is valid
        metadata["PATH"] = path
        return metadata

    @staticmethod
    def _get_repo_info(path):
        sha = _run_cmd(["git", "-C", f'"{path}"', "rev-parse", "HEAD"])[0]
        branch = _run_cmd(["git", "-C", f'"{path}"', "rev-parse", "--abbrev-ref", "HEAD"])[0]
        head_tag = _run_cmd(
            [
                "git",
                "-C",
                f'"{path}"',
                "describe",
                "--exact-match",
                "--tags",
                "HEAD",
                "2>/dev/null",
                "||",
                ":",
            ]
        )
        head_tag = head_tag[0] if head_tag else "ND"
        closest_tag = _run_cmd(["git", "-C", f'"{path}"', "tag"])
        closest_tag = closest_tag[-1] if closest_tag else "ND"
        origin_url = _run_cmd(["git", "-C", f'"{path}"', "config", "--get", "remote.origin.url"])[0]
        if origin_url.endswith(".git"):
            origin_url = origin_url[:-4]
        if origin_url.endswith("/"):
            origin_url = origin_url[:-1]
        repo = origin_url.split("/")[-1]
        # get info about current git INDEX
        nmodified = len(_run_cmd(["git", "-C", f'"{path}"', "status", "--porcelain", "--untracked-files=no"]))
        nadded = len(_run_cmd(["git", "-C", f'"{path}"', "status", "--porcelain"]))
        # return info
        return {
            "REPOSITORY": repo,
            "SHA": sha,
            "BRANCH": branch,
            "VERSION.HEAD": head_tag,
            "VERSION.CLOSEST": closest_tag,
            "ORIGIN.URL": origin_url,
            "ORIGIN.HTTPS.URL": _remote_url_to_https(origin_url),
            "INDEX_NUM_MODIFIED": nmodified,
            "INDEX_NUM_ADDED": nadded,
        }

    @staticmethod
    def inspect_remote_image(image, tag):
        res = requests.get(DOCKER_HUB_API_URL["token"].format(image=image)).json()
        token = res["token"]
        # ---
        res = requests.get(
            DOCKER_HUB_API_URL["digest"].format(image=image, tag=tag),
            headers={
                "Accept": "application/vnd.docker.distribution.manifest.v2+json",
                "Authorization": "Bearer {0}".format(token),
            },
        ).text
        digest = json.loads(res)["config"]["digest"]
        # ---
        res = requests.get(
            DOCKER_HUB_API_URL["inspect"].format(image=image, tag=tag, digest=digest),
            headers={"Authorization": "Bearer {0}".format(token)},
        ).json()
        return res


def assert_canonical_arch(arch):
    if arch not in CANONICAL_ARCH.values():
        raise ValueError(
            f"Given architecture {arch} is not supported. " 
            f"Valid choices are: {', '.join(list(set(CANONICAL_ARCH.values())))}"
        )


def canonical_arch(arch):
    if arch not in CANONICAL_ARCH:
        raise ValueError(
            f"Given architecture {arch} is not supported. " 
            f"Valid choices are: {', '.join(list(set(CANONICAL_ARCH.values())))}"
        )
    # ---
    return CANONICAL_ARCH[arch]


def dtlabel(key, value=None):
    label = f"{DOCKER_LABEL_DOMAIN}.{key.lstrip('.')}"
    if value is not None:
        label = f"{label}={value}"
    return label


def _remote_url_to_https(remote_url):
    ssh_pattern = "git@([^:]+):([^/]+)/(.+)"
    res = re.search(ssh_pattern, remote_url, re.IGNORECASE)
    if res:
        return f"https://{res.group(1)}/{res.group(2)}/{res.group(3)}"
    return remote_url


def _run_cmd(cmd):
    cmd = " ".join(cmd)
    return [line for line in subprocess.check_output(cmd, shell=True).decode("utf-8").split("\n") if line]


def _parse_configurations(config_file: str) -> dict:
    with open(config_file, "rt") as fin:
        configurations_content = yaml.load(fin, Loader=yaml.SafeLoader)
    if "version" not in configurations_content:
        raise ValueError("The configurations file must have a root key 'version'.")
    if configurations_content["version"] == "1.0":
        return configurations_content["configurations"]


def _docker_client(endpoint):
    return (
        endpoint
        if isinstance(endpoint, docker.DockerClient)
        else docker.DockerClient(base_url=sanitize_docker_baseurl(endpoint))
    )
