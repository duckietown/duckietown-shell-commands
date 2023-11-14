import copy
import glob
import json
import os
import re
import subprocess
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Optional, List, Dict, Tuple, Callable

import docker
import requests
import yaml
from docker.errors import APIError, ImageNotFound

from dt_shell import UserError, dtslogger
from utils.docker_utils import sanitize_docker_baseurl
from utils.exceptions import RecipeProjectNotFound
from utils.recipe_utils import get_recipe_project_dir, update_recipe, clone_recipe

REQUIRED_METADATA_KEYS = {
    "*": ["TYPE_VERSION"],
    "1": ["TYPE", "VERSION"],
    "2": ["TYPE", "VERSION"],
    "3": ["TYPE", "VERSION"],
}

REQUIRED_METADATA_PER_TYPE_KEYS = {
    "template-exercise": {
        "3": ["NAME", "RECIPE_REPOSITORY", "RECIPE_BRANCH", "RECIPE_LOCATION"],
    },
}

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

BUILD_COMPATIBILITY_MAP = {"arm32v7": ["arm32v7"], "arm64v8": ["arm32v7", "arm64v8"], "amd64": ["amd64"]}

DOCKER_LABEL_DOMAIN = "org.duckietown.label"

CLOUD_BUILDERS: Dict[str, List[str]] = {
    "arm32v7": [
        "172.27.0.102:2376",
        "172.27.0.250:2376"
    ],
    "arm64v8": [
        "172.27.0.102:2376",
        "172.27.0.250:2376"
    ],
    "amd64": ["172.27.0.101:2376"],
}

ARCH_TO_PLATFORM = {"arm32v7": "linux/arm/v7", "arm64v8": "linux/arm64", "amd64": "linux/amd64"}

ARCH_TO_PLATFORM_OS = {"arm32v7": "linux", "arm64v8": "linux", "amd64": "linux"}

ARCH_TO_PLATFORM_ARCH = {"arm32v7": "arm", "arm64v8": "arm64", "amd64": "amd64"}

ARCH_TO_PLATFORM_VARIANT = {"arm32v7": "v7", "arm64v8": "", "amd64": ""}

TEMPLATE_TO_SRC: Dict[str, Dict[str, Callable[[str], Tuple[str, str]]]] = {
    # NOTE: these are not templates, they only serve the project matching their names
    "dt-commons": {
        "1": lambda repo: ("code", "/packages/{:s}/".format(repo)),
        "2": lambda repo: ("", "/code/{:s}/".format(repo)),
        "3": lambda repo: ("", "/code/{:s}/".format(repo)),
    },
    "dt-ros-commons": {
        "1": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo)),
        "2": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo)),
        "3": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo)),
    },
    # NOTE: these are templates and are shared by multiple projects
    "template-basic": {
        "1": lambda repo: ("code", "/packages/{:s}/".format(repo)),
        "2": lambda repo: ("", "/code/{:s}/".format(repo)),
        "3": lambda repo: ("", "/code/{:s}/".format(repo)),
    },
    "template-ros": {
        "1": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo)),
        "2": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo)),
        "3": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo)),
    },
    "template-core": {
        "1": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo)),
        "2": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo)),
        "3": lambda repo: ("", "/code/catkin_ws/src/{:s}/".format(repo)),
    },
    "template-exercise-recipe": {
        "3": lambda repo: ("packages", "/code/catkin_ws/src/{:s}/packages".format(repo))
    },
    "template-exercise": {"3": lambda repo: ("packages/*", "/code/catkin_ws/src/{:s}/packages".format(repo))},
}

TEMPLATE_TO_LAUNCHFILE: Dict[str, Dict[str, Callable[[str], Tuple[str, str]]]] = {
    # NOTE: these are not templates, they only serve the project matching their names
    "dt-commons": {
        "1": lambda repo: ("launch.sh", "/launch/{:s}/launch.sh".format(repo)),
        "2": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
        "3": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
    },
    "dt-ros-commons": {
        "1": lambda repo: ("launch.sh", "/launch/{:s}/launch.sh".format(repo)),
        "2": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
        "3": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
    },
    # NOTE: these are templates and are shared by multiple projects
    "template-basic": {
        "1": lambda repo: ("launch.sh", "/launch/{:s}/launch.sh".format(repo)),
        "2": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
        "3": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
    },
    "template-ros": {
        "1": lambda repo: ("launch.sh", "/launch/{:s}/launch.sh".format(repo)),
        "2": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
        "3": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
    },
    "template-core": {
        "1": lambda repo: ("launch.sh", "/launch/{:s}/launch.sh".format(repo)),
        "2": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
        "3": lambda repo: ("launchers", "/launch/{:s}".format(repo)),
    },
    "template-exercise-recipe": {"3": lambda repo: ("launchers", "/launch/{:s}".format(repo))},
    "template-exercise": {"3": lambda repo: ("launchers", "/launch/{:s}".format(repo))},
}

TEMPLATE_TO_ASSETS: Dict[str, Dict[str, Callable[[str], Tuple[str, str]]]] = {
    "template-exercise-recipe": {
        "3": lambda repo: ("assets/*", "/code/catkin_ws/src/{:s}/assets".format(repo))
    },
    "template-exercise": {"3": lambda repo: ("assets/*", "/code/catkin_ws/src/{:s}/assets".format(repo))},
}

DISTRO_KEY = {"1": "MAJOR", "2": "DISTRO", "3": "DISTRO"}

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
        self._custom_recipe_dir: Optional[str] = None
        self._recipe_version: Optional[str] = None
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
    def metadata(self) -> Dict[str, str]:
        return copy.deepcopy(self._project_info)

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
        return (
            (self._repository.branch if self._repository.branch != "HEAD" else self.head_version)
            if self._repository
            else "latest"
        )

    @property
    def safe_version_name(self) -> str:
        return re.sub(r"[^\w\-.]", "-", self.version_name)

    @property
    def url(self):
        return self._repository.repository_page if self._repository else None

    @property
    def sha(self):
        return self._repository.sha if self._repository else "ND"

    @property
    def adapters(self):
        return copy.copy(self._adapters)

    @property
    def needs_recipe(self) -> bool:
        return self.type == "template-exercise"

    @property
    def recipe_dir(self) -> Optional[str]:
        if not self.needs_recipe:
            return None
        return (
            self._custom_recipe_dir
            if self._custom_recipe_dir
            else get_recipe_project_dir(
                self.metadata["RECIPE_REPOSITORY"],
                self._recipe_version or self.metadata["RECIPE_BRANCH"],
                self.metadata["RECIPE_LOCATION"],
            )
        )

    @property
    def recipe(self) -> Optional["DTProject"]:
        # load recipe project
        return DTProject(self.recipe_dir) if self.needs_recipe else None

    @property
    def dockerfile(self) -> str:
        if self.needs_recipe:
            # this project needs a recipe to build
            recipe: DTProject = self.recipe
            return recipe.dockerfile
        # this project carries its own Dockerfile
        return os.path.join(self.path, "Dockerfile")

    @property
    def vscode_dockerfile(self) -> Optional[str]:
        # this project's vscode Dockerfile
        vscode_dockerfile: str = os.path.join(self.path, "Dockerfile.vscode")
        if os.path.exists(vscode_dockerfile):
            return vscode_dockerfile
        # it might be in the recipe (if any)
        if self.needs_recipe:
            # this project needs a recipe to build
            recipe: DTProject = self.recipe
            return recipe.vscode_dockerfile
        # this project does not have a Dockerfile.vscode
        return None

    @property
    def vnc_dockerfile(self) -> Optional[str]:
        # this project's vnc Dockerfile
        vnc_dockerfile: str = os.path.join(self.path, "Dockerfile.vnc")
        if os.path.exists(vnc_dockerfile):
            return vnc_dockerfile
        # it might be in the recipe (if any)
        if self.needs_recipe:
            # this project needs a recipe to build
            recipe: DTProject = self.recipe
            return recipe.vnc_dockerfile
        # this project does not have a Dockerfile.vnc
        return None

    @property
    def launchers(self) -> List[str]:
        # read project template version
        try:
            project_template_ver = int(self.type_version)
        except ValueError:
            project_template_ver = -1
        # search for launchers (template v2+)
        if project_template_ver < 2:
            raise NotImplementedError("Only projects with template type v2+ support launchers.")
        # we return launchers from both recipe and meat
        paths: List[str] = [self.path]
        if self.needs_recipe:
            paths.append(self.recipe.path)
        # find launchers
        launchers = []
        for root in paths:
            launchers_dir = os.path.join(root, "launchers")
            if not os.path.exists(launchers_dir):
                continue
            files = [
                os.path.join(launchers_dir, f)
                for f in os.listdir(launchers_dir)
                if os.path.isfile(os.path.join(launchers_dir, f))
            ]

            def _has_shebang(f):
                with open(f, "rt") as fin:
                    return fin.readline().startswith("#!")

            launchers = [Path(f).stem for f in files if os.access(f, os.X_OK) or _has_shebang(f)]
        # ---
        return launchers

    def set_recipe_dir(self, path: str):
        self._custom_recipe_dir = path

    def set_recipe_version(self, branch: str):
        self._recipe_version = branch

    def ensure_recipe_exists(self):
        if not self.needs_recipe:
            return
        # clone the project specified recipe (if necessary)
        if not os.path.exists(self.recipe_dir):
            cloned: bool = clone_recipe(
                self.metadata["RECIPE_REPOSITORY"],
                self._recipe_version or self.metadata["RECIPE_BRANCH"],
                self.metadata["RECIPE_LOCATION"],
            )
            if not cloned:
                raise RecipeProjectNotFound(f"Recipe repository could not be downloaded.")
        # make sure the recipe exists
        if not os.path.exists(self.recipe_dir):
            raise RecipeProjectNotFound(f"Recipe not found at '{self.recipe_dir}'")

    def ensure_recipe_updated(self) -> bool:
        return self.update_cached_recipe()

    def update_cached_recipe(self) -> bool:
        """Update recipe if not using custom given recipe"""
        if self.needs_recipe and not self._custom_recipe_dir:
            return update_recipe(
                self.metadata["RECIPE_REPOSITORY"],
                self._recipe_version or self.metadata["RECIPE_BRANCH"],
                self.metadata["RECIPE_LOCATION"],
            )  # raises: UserError if the recipe has not been cloned
        return False

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
        extra: Optional[str] = None,
    ) -> str:
        assert_canonical_arch(arch)
        loop = "-LOOP" if loop else ""
        docs = "-docs" if docs else ""
        extra = f"-{extra}" if extra else ""
        if version is None:
            version = self.safe_version_name
        return f"{registry}/{owner}/{self.name}:{version}{extra}{loop}{docs}-{arch}"

    def image_vscode(
        self,
        *,
        arch: str,
        registry: str,
        owner: str,
        version: Optional[str] = None,
        docs: bool = False,
    ) -> str:
        return self.image(
            arch=arch, registry=registry, owner=owner, version=version, docs=docs, extra="vscode"
        )

    def image_vnc(
        self,
        *,
        arch: str,
        registry: str,
        owner: str,
        version: Optional[str] = None,
        docs: bool = False,
    ) -> str:
        return self.image(arch=arch, registry=registry, owner=owner, version=version, docs=docs, extra="vnc")

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

    def ci_metadata(self, endpoint, *, arch: str, registry: str, owner: str, version: str):
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

    def code_paths(self, root: Optional[str] = None) -> Tuple[List[str], List[str]]:
        # make sure we support this project version
        if self.type not in TEMPLATE_TO_SRC or self.type_version not in TEMPLATE_TO_SRC[self.type]:
            raise ValueError(
                "Template {:s} v{:s} for project {:s} is not supported".format(
                    self.type, self.type_version, self.path
                )
            )
        # ---
        # root is either a custom given root (remote mounting) or the project path
        root: str = os.path.abspath(root or self.path).rstrip("/")
        # local and destination are fixed given project type and version
        local, destination = TEMPLATE_TO_SRC[self.type][self.type_version](self.name)
        # 'local' can be a pattern
        if local.endswith("*"):
            # resolve 'local' with respect to the project path
            local_abs: str = os.path.join(self.path, local)
            # resolve pattern
            locals = glob.glob(local_abs)
            # we only support mounting directories
            locals = [loc for loc in locals if os.path.isdir(loc)]
            # replace 'self.path' prefix with 'root'
            locals = [os.path.join(root, os.path.relpath(loc, self.path)) for loc in locals]
            # destinations take the stem of the source
            destinations = [os.path.join(destination, Path(loc).stem) for loc in locals]
        else:
            # by default, there is only one local and one destination
            locals: List[str] = [os.path.join(root, local)]
            destinations: List[str] = [destination]
        # ---
        return locals, destinations

    def launch_paths(self, root: Optional[str] = None) -> Tuple[str, str]:
        # make sure we support this project version
        if (
            self.type not in TEMPLATE_TO_LAUNCHFILE
            or self.type_version not in TEMPLATE_TO_LAUNCHFILE[self.type]
        ):
            raise ValueError(
                f"Template {self.type} v{self.type_version} for project {self.path} not supported"
            )
        # ---
        # root is either a custom given root (remote mounting) or the project path
        root: str = os.path.abspath(root or self.path).rstrip("/")
        src, dst = TEMPLATE_TO_LAUNCHFILE[self.type][self.type_version](self.name)
        src = os.path.join(root, src)
        # ---
        return src, dst

    def assets_paths(self, root: Optional[str] = None) -> Tuple[List[str], List[str]]:
        # make sure we support this project version
        if self.type not in TEMPLATE_TO_ASSETS or self.type_version not in TEMPLATE_TO_ASSETS[self.type]:
            raise ValueError(
                "Template {:s} v{:s} for project {:s} is not supported".format(
                    self.type, self.type_version, self.path
                )
            )
        # ---
        # root is either a custom given root (remote mounting) or the project path
        root: str = os.path.abspath(root or self.path).rstrip("/")
        # local and destination are fixed given project type and version
        local, destination = TEMPLATE_TO_ASSETS[self.type][self.type_version](self.name)
        # 'local' can be a pattern
        if local.endswith("*"):
            # resolve 'local' with respect to the project path
            local_abs: str = os.path.join(self.path, local)
            # resolve pattern
            locals = glob.glob(local_abs)
            # we only support mounting directories
            locals = [loc for loc in locals if os.path.isdir(loc)]
            # replace 'self.path' prefix with 'root'
            locals = [os.path.join(root, os.path.relpath(loc, self.path)) for loc in locals]
            # destinations take the stem of the source
            destinations = [os.path.join(destination, Path(loc).stem) for loc in locals]
        else:
            # by default, there is only one local and one destination
            locals: List[str] = [os.path.join(root, local)]
            destinations: List[str] = [destination]
        # ---
        return locals, destinations

    def image_metadata(self, endpoint, arch: str, owner: str, registry: str, version: str):
        client = _docker_client(endpoint)
        image_name = self.image(arch=arch, owner=owner, version=version, registry=registry)
        try:
            image = client.images.get(image_name)
            return image.attrs
        except (APIError, ImageNotFound):
            raise Exception(f"Cannot get image metadata for {image_name!r}: \n {traceback.format_exc()}")

    def image_labels(self, endpoint, *, arch: str, owner: str, registry: str, version: str):
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
    def _get_project_info(path: str):
        if not os.path.exists(path):
            msg = f"The project path {path!r} does not exist."
            raise UserError(msg)

        # look for newer (unsupported) versions first
        metadir = os.path.join(path, "dtproject")
        # if the directory 'dtproject' exists
        if os.path.exists(metadir) and os.path.isdir(metadir):
            msg = f"The path '{path}' appears to contain a Duckietown project of a newer format that this " \
                  f"version of the shell does not support.\nPlease, upgrade the shell to your current " \
                  f"distribution as instructed on 'https://docs.duckietown.com/daffy/devmanual-software/' " \
                  f"before continuing."
            raise UserError(msg)

        metafile = os.path.join(path, ".dtproject")
        # if the file '.dtproject' is missing
        if not os.path.exists(metafile):
            msg = f"The path '{path}' does not appear to be a Duckietown project. "
            msg += "\nThe metadata file '.dtproject' is missing."
            raise UserError(msg)
        # load '.dtproject'
        with open(metafile, "rt") as metastream:
            lines: List[str] = metastream.readlines()
        # empty metadata?
        if not lines:
            msg = f"The metadata file '{metafile}' is empty."
            raise UserError(msg)
        # strip lines
        lines = [line.strip() for line in lines]
        # remove empty lines and comments
        lines = [line for line in lines if len(line) > 0 and not line.startswith("#")]
        # parse metadata
        metadata = {key.strip().upper(): val.strip() for key, val in [line.split("=") for line in lines]}
        # look for version-agnostic keys
        for key in REQUIRED_METADATA_KEYS["*"]:
            if key not in metadata:
                msg = f"The metadata file '{metafile}' does not contain the key '{key}'."
                raise UserError(msg)
        # validate version
        version = metadata["TYPE_VERSION"]
        if version == "*" or version not in REQUIRED_METADATA_KEYS:
            msg = "The project version %s is not supported." % version
            raise UserError(msg)
        # validate metadata
        for key in REQUIRED_METADATA_KEYS[version]:
            if key not in metadata:
                msg = f"The metadata file '{metafile}' does not contain the key '{key}'."
                raise UserError(msg)
        # validate metadata keys specific to project type and version
        type = metadata["TYPE"]
        for key in REQUIRED_METADATA_PER_TYPE_KEYS.get(type, {}).get(version, []):
            if key not in metadata:
                msg = f"The metadata file '{metafile}' does not contain the key '{key}'."
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
    from .docker_utils import get_endpoint_architecture
    arch = canonical_arch(arch)
    for builder in CLOUD_BUILDERS[arch]:
        dtslogger.info(f"Attempting to reach cloud builder '{builder}'...")
        try:
            get_endpoint_architecture(*builder.split(":"))
            return builder
        except:
            dtslogger.warning(f"Failed to reach cloud builder '{builder}'")
            dtslogger.debug(f"Error:\n{traceback.format_exc()}")
    raise RuntimeError(f"No cloud builders could be reached for architecture '{arch}'. "
                       f"We tried with these: {CLOUD_BUILDERS[arch]}")


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
