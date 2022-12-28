import argparse
import copy
import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from typing import Optional, List

from utils.exceptions import ShellNeedsUpdate

# NOTE: this is to avoid breaking the user workspace
try:
    import dockertown
except ImportError:
    raise ShellNeedsUpdate("5.4.0+")
# NOTE: this is to avoid breaking the user workspace

from docker.errors import ImageNotFound
from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError
from duckietown_docker_utils import ENV_REGISTRY
from dockertown import DockerClient
from termcolor import colored
from utils.buildx_utils import install_buildx, DOCKER_INFO, ensure_buildx_version
from utils.cli_utils import ask_confirmation
from utils.docker_utils import (
    DEFAULT_MACHINE,
    DEFAULT_REGISTRY,
    copy_docker_env_into_configuration,
    get_endpoint_architecture,
    get_endpoint_ncpus,
    get_registry_to_use,
    login_client,
    pull_image,
    sanitize_docker_baseurl,
    get_client,
    ensure_docker_version,
)
from utils.dtproject_utils import (
    CANONICAL_ARCH,
    CLOUD_BUILDERS,
    DISTRO_KEY,
    dtlabel,
    DTProject,
    get_cloud_builder,
    ARCH_TO_PLATFORM,
)
from utils.duckietown_utils import DEFAULT_OWNER
from utils.misc_utils import human_size, human_time, sanitize_hostname
from utils.multi_command_utils import MultiCommand
from utils.pip_utils import get_pip_index_url

from dockertown.components.buildx.imagetools.models import Manifest
from dockertown.exceptions import NoSuchManifest
from utils.recipe_utils import RECIPE_STAGE_NAME, MEAT_STAGE_NAME
from .image_analyzer import EXTRA_INFO_SEPARATOR, ImageAnalyzer


class DTCommand(DTCommandAbs):
    help = "Builds the current project"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the project to build"
        )
        parser.add_argument(
            "-a",
            "--arch",
            default=None,
            help="Target architecture(s) for the image to build",
        )
        parser.add_argument(
            "-H", "--machine", default=None, help="Docker socket or hostname where to build the image"
        )
        parser.add_argument(
            "--pull",
            default=False,
            action="store_true",
            help="Whether to pull the latest base image used by the Dockerfile",
        )
        parser.add_argument(
            "--pull-for-cache",
            default=False,
            action="store_true",
            help="Whether to pull the image we are about to build to facilitate cache",
        )
        parser.add_argument(
            "--no-cache", default=False, action="store_true", help="Whether to use the Docker cache"
        )
        parser.add_argument(
            "--force-cache",
            default=False,
            action="store_true",
            help="Whether to force Docker to use an old version of the same " "image as cache",
        )
        parser.add_argument(
            "--no-multiarch",
            default=False,
            action="store_true",
            help="Whether to disable multiarch support (based on bin_fmt)",
        )
        parser.add_argument(
            "-f",
            "--force",
            default=False,
            action="store_true",
            help="Whether to force the build when the git index is not clean",
        )
        parser.add_argument(
            "-A",
            "--build-arg",
            default=[],
            action="append",
            nargs=2,
            metavar=("key", "value"),
            help="Build arguments to pass to Docker buildx",
        )
        parser.add_argument(
            "-B",
            "--build-context",
            default=[],
            action="append",
            nargs=2,
            metavar=("name", "path"),
            help="Additional build contexts to pass to Docker buildx",
        )
        parser.add_argument(
            "--push", default=False, action="store_true", help="Whether to push the resulting image"
        )
        parser.add_argument(
            "--manifest",
            default=False,
            action="store_true",
            help="Whether to create/update the corresponding manifest",
        )
        parser.add_argument(
            "--rm",
            default=False,
            action="store_true",
            help="Remove the images once the build succeded (after pushing)",
        )
        parser.add_argument(
            "--loop",
            default=False,
            action="store_true",
            help="(Developers only) Reuse the same base image, speed up the build",
        )
        parser.add_argument(
            "-u",
            "--username",
            default="duckietown",
            help="The docker registry username to tag the image with",
        )
        parser.add_argument(
            "--registry",
            default=None,
            help="Docker registry to use",
        )
        parser.add_argument(
            "--file",
            default=None,
            help="Path to the Dockerfile to use, relative to the project path",
        )
        parser.add_argument(
            "--recipe",
            default=None,
            help="Path to a recipe to use",
        )
        parser.add_argument(
            "-b",
            "--base-tag",
            default=None,
            help="Docker tag for the base image. Use when the base image is a development version",
        )
        parser.add_argument(
            "--ci",
            default=False,
            action="store_true",
            help="Overwrites configuration for CI (Continuous Integration) builds",
        )
        parser.add_argument(
            "--ci-force-builder-arch",
            dest="ci_force_builder_arch",
            default=None,
            choices=set(CANONICAL_ARCH.values()),
            help="Forces CI to build on a specific architecture node",
        )
        parser.add_argument(
            "--cloud", default=False, action="store_true", help="Build the image on the cloud"
        )
        parser.add_argument(
            "--stamp", default=False, action="store_true", help="Stamp image with the build time"
        )
        parser.add_argument(
            "-D", "--destination", default=None, help="Docker socket or hostname where to deliver the image"
        )
        parser.add_argument(
            "--docs", default=False, action="store_true", help="Build the code documentation as well"
        )
        parser.add_argument("--quiet", default=False, action="store_true", help="Be less verbose")
        parser.add_argument(
            "--ncpus", default=None, type=int, help="Value to pass as build-arg `NCPUS` to docker build."
        )
        parser.add_argument("-v", "--verbose", default=False, action="store_true", help="Be verbose")
        parser.add_argument(
            "--tag", default=None, help="Overrides 'version' (usually taken to be branch name)"
        )

        # get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            # try to interpret it as a multi-command
            multi = MultiCommand(DTCommand, shell, [("-H", "--machine")], args)
            if multi.is_multicommand:
                multi.execute()
                return
        if not parsed:
            # FIXME: this ignores other arguments
            parsed, remaining = parser.parse_known_args(args=args)

            if remaining:
                dtslogger.info(f"I do not know about these arguments: {remaining}")
        else:
            # combine given args with default values
            default_parsed = parser.parse_args(args=[])
            for k, v in parsed.__dict__.items():
                setattr(default_parsed, k, v)
            parsed = default_parsed
        # ---

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
        recipe: Optional[DTProject] = project.recipe

        # tag
        version = project.version_name
        if parsed.tag:
            dtslogger.info(f"Overriding version {version!r} with {parsed.tag!r}")
            version = parsed.tag

        # read project template version
        try:
            project_template_ver = int(project.type_version)
        except ValueError:
            project_template_ver = -1

        # check if the git HEAD is detached
        if project.is_detached():
            dtslogger.error(
                "The repository HEAD is detached. Create a branch or check one out "
                "before continuing. Aborting."
            )
            exit(8)

        # sanitize hostname
        if parsed.machine is not None:
            parsed.machine = sanitize_hostname(parsed.machine)

        # duckietown token
        if parsed.ci:
            token: str = os.environ["DUCKIETOWN_CI_DT_TOKEN"]
        else:
            token: Optional[str] = None
            try:
                token = shell.get_dt1_token()
            except Exception:
                dtslogger.warning(
                    "No Duckietown tokens were set using 'dts tok set', some "
                    "functionalities might not be available."
                )
                pass

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
            # in CI we can force builds on specific architectures
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

        # check if the index is clean
        if project.is_dirty():
            dtslogger.warning("Your index is not clean (some files are not committed).")
            dtslogger.warning("If you know what you are doing, use --force (-f) to force.")
            if not parsed.force:
                exit(1)
            dtslogger.warning("Forced!")
        # add configuration labels (template v2+)
        if project_template_ver >= 2:
            for cfg_name, cfg_data in project.configurations().items():
                label = dtlabel(f"image.configuration.{cfg_name}")
                labels[label] = json.dumps(cfg_data)

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

        # TODO: this should be removed, use dockertown only
        client = get_client(parsed.machine)

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

        # login client
        copy_docker_env_into_configuration(shell.shell_config)
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
        if project_template_ver >= 2:
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
            docker_build_args[DISTRO_KEY[str(project_template_ver)]] = parsed.base_tag

        # loop mode (Experimental)
        if parsed.loop:
            docker_build_args["BASE_IMAGE"] = project.name
            docker_build_args["BASE_TAG"] = "-".join([project.version_name, parsed.arch])
            labels[dtlabel("image.loop")] = "1"
            # ---
            msg = "WARNING: Experimental mode 'loop' is enabled!. Use with caution."
            dtslogger.warn(msg)

        # custom pip registry
        docker_build_args["PIP_INDEX_URL"] = pip_index_url_to_use
        docker_build_args[ENV_REGISTRY] = registry_to_use

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
                client.images.get(image)
                is_present = True
            except (ImageNotFound, BaseException):
                is_present = False
            # ---
            if not is_present:
                if parsed.pull_for_cache:
                    # try to pull the same image so Docker can use it as cache source
                    dtslogger.info(f'Pulling image "{image}" to use as cache...')
                    try:
                        pull_image(image, endpoint=client, progress=not parsed.ci)
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
                # NOTE: this is usually the repo's branch name
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
        dimage = client.images.get(image)
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
            docker.buildx.imagetools.create(tag=manifest, source=manifest_images)
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
            historylog = [(layer["Id"], layer["Size"], layer["CreatedBy"]) for layer in dimage.history()]

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
                {"registry": registry_to_use, "version": version},
                # NOTE: this image tag is pure (no CLI remapping) and refers to the public registry
                {"registry": DEFAULT_REGISTRY, "version": project.version_name},
            ]
            for tag_data in tags_data:
                with NamedTemporaryFile("wt") as fout:
                    metadata = project.ci_metadata(client, arch=parsed.arch, owner=DEFAULT_OWNER, **tag_data)
                    # add build metadata
                    metadata["build"] = {
                        "args": copy.deepcopy(buildargs),
                        "time": build_time,
                    }
                    metadata["sha"] = dimage.id
                    del metadata["build"]["args"]["labels"]
                    # write to temporary file
                    json.dump(metadata, fout, sort_keys=True, indent=4)
                    fout.flush()
                    # push temporary file
                    remote_fnames = [
                        f"docker/image/{metadata['tag']}/latest.json",
                        f"docker/image/{metadata['tag']}/{dimage.id}.json",
                    ]
                    for remote_fname in remote_fnames:
                        remote_fname = remote_fname.replace(":", "/")
                        dtslogger.debug(f"Pushing metadata file [{remote_fname}]...")
                        shell.include.data.push.command(
                            shell,
                            [],
                            parsed=SimpleNamespace(
                                file=[fout.name],
                                object=[remote_fname],
                                token=token,
                                space="public",
                            ),
                        )

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
