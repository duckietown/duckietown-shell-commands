import copy
import json
import os
import random
import re
import subprocess
import traceback
from types import SimpleNamespace
from typing import Optional

import docker
import requests
import yaml
from docker.errors import APIError, ImageNotFound

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
    "arm64": "arm64v8",
    "arm64v8": "arm64v8",
    "armv8": "arm64v8",
    "aarch64": "arm64v8",
}

BUILD_COMPATIBILITY_MAP = {
    "arm32v7": ["arm32v7"],
    "arm64v8": ["arm32v7", "arm64v8"],
    "amd64": ["amd64"]
}

DOCKER_LABEL_DOMAIN = "org.duckietown.label"

CLOUD_BUILDERS = {
    "arm32v7": ["172.27.0.102"],
    "arm64v8": ["172.27.0.102"],
    "amd64": ["172.27.0.101"],
}

ARCH_TO_PLATFORM = {
    "arm32v7": "linux/arm/v7",
    "arm64v8": "linux/arm64",
    "amd64": "linux/amd64"
}

ARCH_TO_PLATFORM_OS = {
    "arm32v7": "linux",
    "arm64v8": "linux",
    "amd64": "linux"
}

ARCH_TO_PLATFORM_ARCH = {
    "arm32v7": "arm",
    "arm64v8": "arm64",
    "amd64": "amd64"
}

ARCH_TO_PLATFORM_VARIANT = {
    "arm32v7": "v7",
    "arm64v8": "",
    "amd64": ""
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
    "template-exercise": {"1": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo))},
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
        self._adapters.append("fs")
        # use `dtproject` adapter (required)
        self._project_info = self._get_project_info(self._path)
        self._type = self._project_info["TYPE"]
        self._type_version = self._project_info["TYPE_VERSION"]
        self._version = self._project_info["VERSION"]
        self._adapters.append("dtproject")
        # use `git` adapter if available
        if os.path.isdir(os.path.join(self._path, ".git")):
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
            self._adapters.append("git")

    @property
    def path(self):
        return self._path

    @property
    def name(self):
        return (self._repository.name if self._repository else os.path.basename(self.path)).lower()

    @property
    def type(self):
        return self._type

    @property
    def type_version(self):
        return self._type_version

    @property
    def distro(self):
        return self._repository.branch.split("-")[0] if self._repository else "latest"

    @property
    def version(self):
        return self._version

    @property
    def head_version(self):
        return self._repository.head_version if self._repository else "latest"

    @property
    def closest_version(self):
        return self._repository.closest_version if self._repository else "latest"

    @property
    def version_name(self):
        return self._repository.branch if self._repository else "latest"

    @property
    def url(self):
        return self._repository.repository_page if self._repository else None

    @property
    def sha(self):
        return self._repository.sha if self._repository else "ND"

    @property
    def adapters(self):
        return copy.copy(self._adapters)

    def is_release(self):
        if not self.is_clean():
            return False
        if self._repository and self.head_version != "ND":
            return True
        return False

    def is_clean(self):
        if self._repository:
            return (self._repository.index_nmodified + self._repository.index_nadded) == 0
        return True

    def is_dirty(self):
        return not self.is_clean()

    def is_detached(self):
        return self._repository.detached if self._repository else False

    def image(
        self,
        *,
        arch: str,
        registry: str,
        owner: str,
        version: Optional[str] = None,
        loop: bool = False,
        docs: bool = False,
    ) -> str:
        assert_canonical_arch(arch)
        loop = "-LOOP" if loop else ""
        docs = "-docs" if docs else ""
        if version is None:
            version = re.sub(r"[^\w\-.]", "-", self.version_name)

        return f"{registry}/{owner}/{self.name}:{version}{loop}{docs}-{arch}"

    def image_release(
        self,
        *,
        arch: str,
        owner: str,
        registry: str,
        docs: bool = False,
    ) -> str:
        if not self.is_release():
            raise ValueError("The project repository is not in a release state")
        assert_canonical_arch(arch)
        docs = "-docs" if docs else ""
        version = re.sub(r"[^\w\-.]", "-", self.head_version)
        return f"{registry}/{owner}/{self.name}:{version}{docs}-{arch}"

    def manifest(
        self,
        *,
        registry: str,
        owner: str,
        version: Optional[str] = None,
    ) -> str:
        if version is None:
            version = re.sub(r"[^\w\-.]", "-", self.version_name)

        return f"{registry}/{owner}/{self.name}:{version}"

    def ci_metadata(
        self,
        endpoint,
        *,
        arch: str,
        registry: str,
        owner: str,
        version: str
    ):
        image_tag = self.image(arch=arch, owner=owner, version=version, registry=registry)
        try:
            configurations = self.configurations()
        except NotImplementedError:
            configurations = {}
        # do docker inspect
        inspect = self.image_metadata(endpoint, arch=arch, owner=owner, version=version, registry=registry)

        # remove useless data
        del inspect["ContainerConfig"]
        del inspect["Config"]["Labels"]
        # compile metadata
        meta = {
            "version": "1.0",
            "tag": image_tag,
            "image": inspect,
            "project": {
                "path": self.path,
                "name": self.name,
                "type": self.type,
                "type_version": self.type_version,
                "distro": self.distro,
                "version": self.version,
                "head_version": self.head_version,
                "closest_version": self.closest_version,
                "version_name": self.version_name,
                "url": self.url,
                "sha": self.sha,
                "adapters": self.adapters,
                "is_release": self.is_release(),
                "is_clean": self.is_clean(),
                "is_dirty": self.is_dirty(),
                "is_detached": self.is_detached(),
            },
            "configurations": configurations,
            "labels": self.image_labels(
                endpoint,
                arch=arch,
                registry=registry,
                owner=owner,
                version=version,
            ),
        }
        # ---
        return meta

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

    def image_metadata(
        self,
        endpoint,
        arch: str,
        owner: str,
        registry: str,
        version: str
    ):
        client = _docker_client(endpoint)
        image_name = self.image(arch=arch, owner=owner, version=version, registry=registry)
        try:
            image = client.images.get(image_name)
            return image.attrs
        except (APIError, ImageNotFound):
            raise Exception(f"Cannot get image metadata for {image_name!r}: \n {traceback.format_exc()}")

    def image_labels(
        self,
        endpoint,
        *,
        arch: str,
        owner: str,
        registry: str,
        version: str
    ):
        client = _docker_client(endpoint)
        image_name = self.image(arch=arch, owner=owner, version=version, registry=registry)
        try:
            image = client.images.get(image_name)
            return image.labels
        except (APIError, ImageNotFound):
            return None

    def remote_image_metadata(self, arch: str, owner: str, registry: str):
        assert_canonical_arch(arch)
        image = f"{registry}/{owner}/{self.name}"
        tag = f"{self.version_name}-{arch}"
        return self.inspect_remote_image(image, tag)

    @staticmethod
    def _get_project_info(path):
        metafile = os.path.join(path, ".dtproject")
        # if the file '.dtproject' is missing
        if not os.path.exists(metafile):
            msg = f"The path '{metafile}' does not appear to be a Duckietown project. "
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
        metadata = {
            p[0].strip().upper(): p[1].strip() for p in [line.split("=") for line in metadata if line.strip()]
        }
        # look for version-agnostic keys
        for key in REQUIRED_METADATA_KEYS["*"]:
            if key not in metadata:
                msg = f"The metadata file '.dtproject' does not contain the key '{key}'."
                raise UserError(msg)
        # validate version
        version = metadata["TYPE_VERSION"]
        if version == "*" or version not in REQUIRED_METADATA_KEYS:
            msg = "The project version %s is not supported." % version
            raise UserError(msg)
        # validate metadata
        for key in REQUIRED_METADATA_KEYS[version]:
            if key not in metadata:
                msg = f"The metadata file '.dtproject' does not contain the key '{key}'."
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
        porcelain = ["git", "-C", f'"{path}"', "status", "--porcelain"]
        modified = _run_cmd(porcelain + ["--untracked-files=no"])
        nmodified = len(modified)
        added = _run_cmd(porcelain)
        # we are not counting files with .resolved extension
        added = list(filter(lambda f: not f.endswith(".resolved"), added))
        nadded = len(added)
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


def get_cloud_builder(arch: str) -> str:
    arch = canonical_arch(arch)
    return random.choice(CLOUD_BUILDERS[arch])


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
