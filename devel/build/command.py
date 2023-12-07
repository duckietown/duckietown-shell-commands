import argparse
import copy
import datetime
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Optional, List, Set

import requests

from dt_shell.exceptions import ShellNeedsUpdate
from utils.hub_utils import DTHUB_API_URL

# NOTE: this is to avoid breaking the user workspace
try:
    import dockertown
except ImportError:
    raise ShellNeedsUpdate("5.4.0+")
# NOTE: this is to avoid breaking the user workspace

from docker.errors import ImageNotFound
from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError
from dockertown import DockerClient, Image
from termcolor import colored
from utils.buildx_utils import install_buildx, DOCKER_INFO, ensure_buildx_version
from utils.cli_utils import ask_confirmation
from utils.docker_utils import (
    DEFAULT_MACHINE,
    DEFAULT_REGISTRY,
    CLOUD_BUILDERS,
    copy_docker_env_into_configuration,
    get_endpoint_architecture,
    get_endpoint_ncpus,
    get_registry_to_use,
    login_client,
    sanitize_docker_baseurl,
    ensure_docker_version,
    get_cloud_builder,
    pull_image,
)

import dtproject
from dtproject import DTProject
from dtproject.constants import ARCH_TO_PLATFORM, DISTRO_KEY
from dtproject.utils.misc import dtlabel

from utils.duckietown_utils import DEFAULT_OWNER
from utils.misc_utils import human_size, human_time, sanitize_hostname, parse_version, pretty_json
from utils.multi_command_utils import MultiCommand
from utils.pip_utils import get_pip_index_url

from dockertown.components.buildx.imagetools.models import Manifest
from dockertown.exceptions import NoSuchManifest, NoSuchImage
from utils.recipe_utils import RECIPE_STAGE_NAME, MEAT_STAGE_NAME
from .image_analyzer import EXTRA_INFO_SEPARATOR, ImageAnalyzer


MIN_FORMAT_PER_DISTRO = {
    "daffy": 1,
    "ente": 4,
}


class DTCommand(DTCommandAbs):
    help = "Builds the current project"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parser: argparse.ArgumentParser = DTCommand.parser

        # get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            # try to interpret it as a multi-command
            multi = MultiCommand(DTCommand, shell, [("-H", "--machine")], args)
            if multi.is_multicommand:
                multi.execute()
                return
        if not parsed:
            parsed = parser.parse_args(args=args)
        else:
            # combine given args with default values
            default_parsed = parser.parse_args(args=[])
            for k, v in parsed.__dict__.items():
                setattr(default_parsed, k, v)
            parsed = default_parsed
        # ---

        # check version of dtproject
        if parse_version(dtproject.__version__) < (1, 0, 4):
            dtslogger.error("You need a version of 'dtproject' that is newer than or equal to 1.0.4. "
                            f"Detected {dtproject.__version__}. Please, update before continuing.")
            exit(10)

        # CI checks
        if parsed.ci:
            is_production: bool = os.environ["DUCKIETOWN_CI_IS_PRODUCTION"] == "1"
            if is_production:
                release_check_args: SimpleNamespace = SimpleNamespace(ci=True)
                shell.include.devel.release.check.command(shell, [], parsed=release_check_args)

        # variables
        docker_build_args: dict = {}
        labels: dict = {}
        cache_from: Optional[str] = None
        stime: float = time.time()
        registry_to_use: str = parsed.registry or get_registry_to_use(parsed.quiet)
        pip_index_url_to_use: str = get_pip_index_url()
        debug: bool = dtslogger.level <= logging.DEBUG

        # conflicting arguments
        if parsed.push and parsed.loop:
            msg = "Forbidden: You cannot push an image when using the flag `--loop`."
            dtslogger.warn(msg)
            exit(9)

        # load project
        parsed.workdir = os.path.abspath(parsed.workdir)
        project = DTProject(parsed.workdir)

        # check format of dtproject
        if project.distro not in MIN_FORMAT_PER_DISTRO:
            dtslogger.warning(f"Distro '{project.distro}' not recognized, things might not work properly.")
        else:
            min_format_version: int = MIN_FORMAT_PER_DISTRO[project.distro]
            if project.format.version < min_format_version:
                dtslogger.error(f"The distro '{project.distro}' requires a project format version "
                                f"newer than or equal to v{min_format_version}. "
                                f"Detected v{project.format.version}. Please, upgrade your project first.")
                exit(11)

        # project-defined build arguments
        for key, value in project.build_args.items():
            docker_build_args[key] = value

        # show info about project
        if not parsed.quiet:
            dtslogger.info("Project workspace: {}".format(parsed.workdir))
            shell.include.devel.info.command(shell, args)

        # recipe
        if parsed.recipe is not None:
            if project.needs_recipe:
                recipe_dir: str = os.path.abspath(parsed.recipe)
                dtslogger.info(f"Using custom recipe from '{recipe_dir}'")
                project.set_recipe_dir(recipe_dir)
            else:
                raise UserError("This project does not support recipes")
        elif parsed.recipe_version:
            project.set_recipe_version(parsed.recipe_version)
            dtslogger.info(f"Using recipe version on branch '{parsed.recipe_version}'")
        recipe: Optional[DTProject] = project.recipe

        # tag
        version: str = project.distro

        # override version
        if parsed.tag:
            dtslogger.info(f"Overriding version {version!r} with {parsed.tag!r}")
            version = parsed.tag

        # sanitize hostname
        if parsed.machine is not None:
            parsed.machine = sanitize_hostname(parsed.machine)

        # duckietown token
        if parsed.ci:
            token: str = os.environ["DUCKIETOWN_CI_DT_TOKEN"]
        else:
            token: str = shell.profile.secrets.dt_token

        # CI builds
        if parsed.ci:
            parsed.pull = True
            parsed.pull_for_cache = True
            parsed.cloud = True
            parsed.push = True
            parsed.rm = True
            parsed.stamp = True
            parsed.manifest = True
            parsed.force_cache = True
            keys_required = ["DT_TOKEN"]
            # TODO: this is temporary given that we have separate accounts for pulling/pushing
            #  from/to DockerHub

            # check that the env variables are set
            for key in keys_required:
                if "DUCKIETOWN_CI_" + key not in os.environ:
                    dtslogger.error(
                        "Variable DUCKIETOWN_CI_{:s} required when building with --ci".format(key)
                    )
                    exit(5)

            # set configuration
            labels[dtlabel("image.authoritative")] = "1"

        # cloud build
        if parsed.cloud:
            if parsed.arch is None:
                dtslogger.error(
                    "When building on the cloud you need to explicitly specify "
                    "a target architecture. Aborting..."
                )
                exit(6)
            if parsed.machine is not None:
                dtslogger.error(
                    "The parameter --machine (-H) cannot be set together with "
                    + "--cloud. Use --destination (-D) if you want to specify "
                    + "a destination for the image. Aborting..."
                )
                exit(4)
            # route the build to the native node
            if parsed.arch not in CLOUD_BUILDERS:
                dtslogger.error(f"No cloud machines found for target architecture {parsed.arch}.")
                exit(3)
            # update machine parameter
            parsed.machine = get_cloud_builder(parsed.arch)
            # in CI, we can force builds on specific architectures
            if parsed.ci_force_builder_arch is not None:
                # force routing to the given architecture node
                if parsed.ci_force_builder_arch not in CLOUD_BUILDERS:
                    dtslogger.error(
                        f"No cloud machines found for (forced) architecture "
                        f"{parsed.ci_force_builder_arch}. Aborting..."
                    )
                    exit(7)
                # update machine parameter
                parsed.machine = get_cloud_builder(parsed.ci_force_builder_arch)
                dtslogger.info(f"Build forced to happen on {parsed.ci_force_builder_arch} CI node")
            # we are not transferring the image back to local when,
            # - we build on CI
            # - we build to push
            if parsed.ci or parsed.push:
                parsed.destination = parsed.machine
            # update destination parameter
            if not parsed.destination:
                parsed.destination = DEFAULT_MACHINE

        # add code labels
        project_head_version = project.head_version if project.is_clean() else "ND"
        project_closest_version = project.closest_version
        labels[dtlabel("code.distro")] = project.distro
        labels[dtlabel("code.version.head")] = project_head_version
        labels[dtlabel("code.version.closest")] = project_closest_version

        # git-based project
        if "git" in project.adapters:
            labels[dtlabel("code.vcs")] = "git"
            labels[dtlabel("code.repository")] = project.name
            labels[dtlabel("code.branch")] = project.version_name
            labels[dtlabel("code.url")] = project.url
        else:
            labels[dtlabel("code.vcs")] = "ND"
            labels[dtlabel("code.repository")] = "ND"
            labels[dtlabel("code.branch")] = "ND"
            labels[dtlabel("code.url")] = "ND"

        # add template labels
        labels[dtlabel("template.name")] = project.type
        labels[dtlabel("template.version")] = project.type_version

        # add configuration labels (template v2+)
        if project.format.version < 4:
            try:
                for cfg_name, cfg_data in project.configurations().items():
                    label = dtlabel(f"image.configuration.{cfg_name}")
                    labels[label] = json.dumps(cfg_data)
            except NotImplementedError:
                # configurations were never used in old project formats, this is ok
                pass
        elif project.format.version >= 4:
            # TODO: use containers layer
            pass

        # create docker client
        host: Optional[str] = sanitize_docker_baseurl(parsed.machine)
        docker = DockerClient(host=host, debug=debug)

        # make sure buildx is installed
        if not docker.buildx.is_installed():
            if not parsed.ci:
                install = ask_confirmation(
                    "The CLI plugin for docker 'buildx' is not installed.",
                    question="Do you want to install it?",
                )
                if not install:
                    dtslogger.info("Aborting.")
                    exit(2)
            # install buildx
            dtslogger.info("Installing buildx...")
            install_buildx()
            dtslogger.info("Buildx installed!")

        # ensure docker version
        ensure_docker_version(docker, "1.4.0+")

        # ensure buildx version
        ensure_buildx_version(docker, "0.8.0+")

        # build-arg NCPUS
        ncpu: str = str(get_endpoint_ncpus(parsed.machine)) if parsed.ncpus is None else str(parsed.ncpus)
        docker_build_args["NCPUS"] = ncpu
        dtslogger.debug(f"NCPU set to {ncpu}.")

        # get info about docker endpoint
        if not parsed.quiet:
            dtslogger.info("Retrieving info about Docker endpoint...")
            epoint = docker.info().dict()
            epoint["mem_total"] = human_size(epoint["mem_total"])
            print(DOCKER_INFO.format(**epoint))

        # login client (unless skipped)
        if parsed.login:
            # TODO: fix this
            copy_docker_env_into_configuration(shell.shell_config)
            # TODO: fix this
            login_client(docker, shell.shell_config, registry_to_use, raise_on_error=parsed.ci)

        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f"Target architecture automatically set to {parsed.arch}.")

        # architecture target
        docker_build_args["ARCH"] = parsed.arch

        # create defaults
        image = project.image(
            arch=parsed.arch,
            loop=parsed.loop,
            owner=parsed.username,
            registry=registry_to_use,
            version=version,
        )
        manifest = project.manifest(
            owner=parsed.username,
            registry=registry_to_use,
            version=version,
        )

        # search for launchers (template v2+)
        launchers = []
        if project.format.version >= 2:
            launchers_dir = os.path.join(parsed.workdir, "launchers")
            files = (
                [
                    os.path.join(launchers_dir, f)
                    for f in os.listdir(launchers_dir)
                    if os.path.isfile(os.path.join(launchers_dir, f))
                ]
                if os.path.isdir(launchers_dir)
                else []
            )

            def _has_shebang(f):
                with open(f, "rt") as fin:
                    return fin.readline().startswith("#!")

            launchers = [Path(f).stem for f in files if os.access(f, os.X_OK) or _has_shebang(f)]
            # add launchers to image labels
            labels[dtlabel("code.launchers")] = ",".join(sorted(launchers))

        # development base images
        if parsed.base_tag is not None:
            docker_build_args[DISTRO_KEY[str(project.format.version)]] = parsed.base_tag

        # loop mode (Experimental)
        if parsed.loop:
            docker_build_args["BASE_IMAGE"] = project.name
            docker_build_args["BASE_TAG"] = "-".join([project.distro, parsed.arch])
            labels[dtlabel("image.loop")] = "1"
            # ---
            msg = "WARNING: Experimental mode 'loop' is enabled!. Use with caution."
            dtslogger.warn(msg)

        # custom pip registry
        docker_build_args["PIP_INDEX_URL"] = pip_index_url_to_use
        docker_build_args["DOCKER_REGISTRY"] = project.base_registry or registry_to_use

        # custom build arguments
        for key, value in parsed.build_arg:
            docker_build_args[key] = value

        # additional build contexts
        docker_build_contexts = {}
        # - given via CLI
        for name, path in parsed.build_context:
            docker_build_contexts[name] = path
        # - recipe contexts
        if project.needs_recipe:
            docker_build_contexts[RECIPE_STAGE_NAME] = recipe.path
            docker_build_contexts[MEAT_STAGE_NAME] = project.path

        # cache
        if not parsed.no_cache:
            # check if the endpoint contains an image with the same name
            try:
                docker.image.inspect(image)
                is_present = True
            except NoSuchImage:
                is_present = False
            # ---
            if not is_present:
                if parsed.pull_for_cache:
                    # try to pull the same image so Docker can use it as cache source
                    dtslogger.info(f'Pulling image "{image}" to use as cache...')
                    try:
                        pull_image(image, endpoint=docker, progress=not parsed.ci)
                        is_present = True
                    except KeyboardInterrupt:
                        dtslogger.info("Aborting.")
                        return
                    except (ImageNotFound, BaseException):
                        dtslogger.warning(
                            f'An error occurred while pulling the image "{image}", maybe the '
                            "image does not exist"
                        )
            else:
                dtslogger.info("Found an image with the same name. Using it as cache source.")
            # configure cache
            if parsed.force_cache and is_present:
                cache_from = image

        # stamp image
        build_time = "ND"
        if parsed.stamp:
            if project.is_dirty():
                dtslogger.warning(
                    "Your git index is not clean. You can't stamp an image built "
                    "from a dirty index. The image will not be stamped."
                )
            else:
                # project is clean
                build_time = None
                local_sha = project.sha
                image_labels = None
                # get remote image metadata
                try:
                    image_labels = project.image_labels(
                        parsed.machine,
                        arch=parsed.arch,
                        registry=registry_to_use,
                        owner=parsed.username,
                        version=version,
                    )
                except BaseException as e:
                    dtslogger.warning(f"Cannot fetch image metadata. Reason: {str(e)}")
                if image_labels is None:
                    dtslogger.warning(f"Cannot fetch image metadata for '{image}'.")
                    image_labels = {}
                # ---
                time_label = dtlabel("time")
                sha_label = dtlabel("code.sha")
                dtslogger.debug(
                    f"Remote image labels:\n{json.dumps(image_labels, indent=4, sort_keys=True)}\n"
                )
                if time_label in image_labels and sha_label in image_labels:
                    remote_time = image_labels[time_label]
                    remote_sha = image_labels[sha_label]
                    if remote_sha == local_sha and remote_time != "ND":
                        dtslogger.debug("Identical image found. Reusing cache.")
                        # local and remote SHA match, reuse time
                        build_time = remote_time

        # default build_time
        build_time = build_time or datetime.datetime.utcnow().isoformat()
        dtslogger.debug(f"Image timestamp: {build_time}")
        # add timestamp label
        labels[dtlabel("time")] = build_time
        # add code SHA label (CI only)
        code_sha = project.sha if project.is_clean() else "ND"
        labels[dtlabel("code.sha")] = code_sha

        # path to Dockerfile
        dockerfile: str = os.path.join(parsed.workdir, "Dockerfile")
        if project.needs_recipe:
            dockerfile = recipe.dockerfile
        if parsed.file is not None:
            if project.needs_recipe:
                dockerfile = os.path.abspath(os.path.join(recipe.path, parsed.file))
            else:
                dockerfile = os.path.abspath(os.path.join(parsed.workdir, parsed.file))

        # build options
        buildargs = {
            "file": dockerfile,
            "build_args": docker_build_args,
            "build_contexts": docker_build_contexts,
            "labels": labels,
            "cache": not parsed.no_cache,
            "pull": parsed.pull,
            "push": parsed.push,
            "tags": [image],
            "platforms": [ARCH_TO_PLATFORM[arch] for arch in parsed.arch.split(",")],
        }

        # when building on CI, we also want to push the real tag to the public default registry
        if parsed.ci:
            pimage = project.image(
                arch=parsed.arch,
                loop=parsed.loop,
                owner=parsed.username,
                # NOTE: this is the public default registry
                registry=DEFAULT_REGISTRY,
                # NOTE: this is the repo's branch name only in CI
                version=project.version_name,
            )
            buildargs["tags"].append(pimage)

        # explicit cache source
        if cache_from:
            buildargs["cache_from"] = cache_from

        # tag release images
        if project.is_release():
            rimage = project.image_release(
                arch=parsed.arch,
                owner=parsed.username,
                registry=registry_to_use,
            )
            buildargs["tags"].append(rimage)

        dtslogger.debug("Build arguments:\n%s\n" % json.dumps(buildargs, sort_keys=True, indent=4))

        # build image
        dtslogger.info("Packaging project...")
        buildlog = []
        build = docker.buildx.build(path=parsed.workdir, progress="plain", stream_logs=True, **buildargs)
        try:
            for line in build:
                if not line:
                    continue
                # removed useless counter
                line = _build_line(line)
                try:
                    sys.stdout.write(line)
                    buildlog.append(line)
                except UnicodeEncodeError:
                    pass
                sys.stdout.flush()
        except Exception as e:
            dtslogger.error(f"An error occurred while building the project image:\n{str(e)}")
            exit(1)

        # get resulting image
        dimage: Image = docker.image.inspect(image)
        dtslogger.info("Project packaged successfully!")

        # update manifest
        dmanifest: Optional[Manifest] = None
        if parsed.manifest:
            dtslogger.info(f"Creating manifest with name '{manifest}'...")
            # find list of images available online
            manifest_images: List[str] = []
            for manifest_arch in ARCH_TO_PLATFORM:
                manifest_image = project.image(
                    arch=manifest_arch,
                    loop=parsed.loop,
                    owner=parsed.username,
                    registry=registry_to_use,
                    version=version,
                )
                dtslogger.debug(f" - Checking image {manifest_image}....")
                try:
                    docker.manifest.inspect(manifest_image)
                except NoSuchManifest:
                    dtslogger.debug(f"Image {manifest_image}' not found")
                    continue
                dtslogger.debug(f'Found image {manifest_image} for architecture "{manifest_arch}"')
                manifest_images.append(manifest_image)
            # update manifest
            dtslogger.debug(f"Creating manifest '{manifest}' with images: {manifest_images}")
            docker.buildx.imagetools.create(tags=[manifest], sources=manifest_images)
            # get manifest
            dmanifest = docker.manifest.inspect(manifest)

        # build code docs
        if parsed.docs:
            docs_args = ["--quiet"] * int(not parsed.verbose)
            # build docs
            dtslogger.info("Building documentation...")
            shell.include.devel.docs.build.command(shell, args + docs_args)

        # print out image analysis
        if not parsed.quiet:
            # get image history
            historylog = [
                (layer.id, layer.size, layer.created_by)
                for layer in docker.image.history(image)
            ]

            # round up extra info
            extra_info = []
            # - launchers info
            if len(launchers) > 0:
                extra_info.append("Image launchers:")
                for launcher in sorted(launchers):
                    extra_info.append(" - {:s}".format(launcher))
                extra_info.append(EXTRA_INFO_SEPARATOR)
            # - timing
            extra_info.append("Time: {}".format(human_time(time.time() - stime)))
            # - documentation
            extra_info.append(
                "Documentation: {}".format(
                    colored("Built", "green") if parsed.docs else colored("Skipped", "yellow")
                )
            )
            # - manifest
            if parsed.manifest:
                extra_info.append(f"Manifest: {manifest}")
                for m in dmanifest.manifests:
                    extra_info.append(f" - {str(m.platform.as_string())}")
            # compile extra info
            extra_info = "\n".join(extra_info)

            # run docker image analysis
            ImageAnalyzer.process(buildlog, historylog, codens=100, extra_info=extra_info, nocolor=parsed.ci)

        # perform metadata push (if needed)
        if parsed.ci:
            tags_data = [
                # NOTE: this image tag is modified by the CLI arguments, e.g., X-staging -> X
                {"registry": registry_to_use, "version": project.distro},
                # NOTE: this image tag is pure (no CLI remapping) and refers to the public registry
                {"registry": DEFAULT_REGISTRY, "version": project.version_name},
            ]
            already_pushed: Set[str] = set()
            for tag_data in tags_data:
                metadata = project.ci_metadata(docker, arch=parsed.arch, owner=DEFAULT_OWNER, **tag_data)
                # add build metadata
                metadata["build"] = {
                    "args": copy.deepcopy(buildargs),
                    "time": build_time,
                }
                metadata["sha"] = dimage.id
                del metadata["build"]["args"]["labels"]
                # define metadata
                identifier: str = metadata["tag"].replace(":", "/")
                _, sha256 = dimage.id.split(":")
                assert _ == "sha256"
                uri: str = f"docker/image/metadata/{identifier}/sha256/{sha256}.json"
                if uri in already_pushed:
                    continue
                url: str = f"{DTHUB_API_URL}/{uri}"
                dtslogger.info(f"Pushing image metadata to [{url}]...")
                dtslogger.debug(f"Pushing image metadata:\n{pretty_json(metadata, indent=4)}")
                already_pushed.add(uri)
                response: Optional[dict] = None
                try:
                    response = requests.post(
                        url,
                        json=metadata,
                        headers={"Authorization": f"Token {token}"}
                    ).json()
                    if not response["success"]:
                        if response["code"] == 208:
                            # already reported
                            dtslogger.warning("The server warned us that this image metadata already exists.")
                        else:
                            msg: str = "\n".join(response["messages"])
                            dtslogger.error("An error occurred while pushing the image metadata to the HUB. "
                                            f"Error reads:\n{msg}")
                            exit(12)
                    else:
                        dtslogger.info("Image metadata pushed successfully!")
                except:
                    dtslogger.error("An error occurred while talking to images metadata server. Error:")
                    dtslogger.error(f" > Response: {response}")
                    traceback.print_exc()
                    exit(13)

        # perform remove (if needed)
        if parsed.rm:
            # noinspection PyBroadException
            try:
                shell.include.devel.clean.command(shell, [], parsed=copy.deepcopy(parsed))
            except BaseException:
                dtslogger.warn(
                    "We had some issues cleaning up the image on '{:s}'".format(parsed.machine)
                    + ". Just a heads up!"
                )

        # ---
        return True

    @staticmethod
    def complete(shell, word, line):
        return []


class ProjectBuildError(Exception):
    pass


def _build_line(line):
    # each line has format "#{i} [\s*{cur_step}/{tot_steps}] {command}"
    # - remove useless counter "#{i} "
    line: str = line.split(" ", maxsplit=1)[-1]
    # ---
    return line
