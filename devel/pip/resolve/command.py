import argparse
import json
import logging
import os
from types import SimpleNamespace
from typing import Optional, List, Union, Dict, Set

from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError
from requirements.requirement import Requirement

from dockertown import DockerClient
from dtproject import DTProject
from utils.assets_utils import get_asset_path
from utils.docker_utils import (
    get_endpoint_architecture,
    get_registry_to_use,
    get_cloud_builder,
    sanitize_docker_baseurl,
)
from utils.exceptions import UnpinnedDependenciesError
from utils.misc_utils import sanitize_hostname, indent_block


Raw = Comment = str

STRICT_SPECS: Set[str] = {
    "==",
}
GOOD_SPECS: Set[str] = {
    "==",
    "<=",
    "<",
}


class DTCommand(DTCommandAbs):
    help = "Resolves and/or makes sure that a project's pip dependencies are properly pinned"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parser: argparse.ArgumentParser = DTCommand.parser
        # configure arguments
        parsed, _ = parser.parse_known_args(args=args)
        if "parsed" in kwargs:
            parsed.__dict__.update(kwargs["parsed"].__dict__)
        # ---
        parsed.workdir = os.path.abspath(parsed.workdir)
        project = DTProject(parsed.workdir)

        # dependent options
        if parsed.strict:
            parsed.check = True
        if parsed.ci:
            parsed.check = True

        # incompatible options
        if parsed.check and parsed.in_place:
            raise UserError(
                "The options --check/--strict and -i/--in-place cannot be used together."
            )

        # use a cloud machine
        if parsed.ci:
            if parsed.arch is None:
                raise UserError("The argument --arch is required when --ci is used")
            parsed.machine = get_cloud_builder(parsed.arch)

        # support both non-dt and dt dependencies lists
        deps_files = {
            "dependencies-py3.txt": project.py3_dependencies(comments=True),
            "dependencies-py3.dt.txt": project.py3_dependencies_dt(comments=True),
        }

        # strict check
        if parsed.check:
            for deps_file, wanted in deps_files.items():
                DTCommand._check_pinned(deps_file, wanted, strict=parsed.strict)
            return

        # create docker client
        debug: bool = dtslogger.level <= logging.DEBUG
        host: Optional[str] = sanitize_docker_baseurl(parsed.machine)
        docker = DockerClient(host=host, debug=debug)

        # get Dockerfile from our assets
        assets_path = get_asset_path("dockerfile", "pip-resolver", "v1")
        dockerfile_path = get_asset_path(
            "dockerfile", "pip-resolver", "v1", "Dockerfile"
        )

        # sanitize hostname
        if parsed.machine is not None:
            parsed.machine = sanitize_hostname(parsed.machine)

        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f"Target architecture automatically set to {parsed.arch}.")

        # make an image name
        image_tag: str = f"{project.safe_version_name}-pip-resolver"

        # build environment (this is the step that performs the resolution)
        dtslogger.info(
            f"Building pip-resolver environment image for project '{project.name}'..."
        )
        buildx_namespace: SimpleNamespace = SimpleNamespace(
            workdir=parsed.workdir,
            machine=parsed.machine,
            arch=parsed.arch,
            file=dockerfile_path,
            username="duckietown",
            tag=image_tag,
            build_context=[
                ("assets", assets_path),
                ("project", project.path),
            ],
            pull=not parsed.no_pull,
            verbose=parsed.verbose,
            quiet=not parsed.verbose,
            force=True,
        )
        dtslogger.debug(
            f"Calling command 'devel/build' with arguments: {str(buildx_namespace)}"
        )
        shell.include.devel.build.command(shell, [], parsed=buildx_namespace)

        # recreate image name
        registry_to_use = get_registry_to_use()
        image = project.image(
            arch=parsed.arch,
            registry=registry_to_use,
            owner="duckietown",
            extra="pip-resolver",
            version=project.distro
        )

        # run pip freeze
        dtslogger.info(f"Exporting list of resolved dependencies...")
        args = {
            "image": image,
            "remove": True,
        }
        dtslogger.debug(
            f"Calling docker.run with arguments:\n"
            f"{json.dumps(args, indent=4, sort_keys=True)}\n"
        )
        logs: str = docker.run(**args)
        lines: List[str] = logs.splitlines()

        # extract pip-freeze output
        s, e = lines.index("PIP-FREEZE:BEGIN"), lines.index("PIP-FREEZE:END")
        pinned: List[str] = lines[s + 1 : e]

        for deps_file, wanted in deps_files.items():
            # combine pinned list with dependencies list
            resolved: List[str] = DTCommand._resolve_deps(wanted, pinned)

            # in-place edit
            if parsed.in_place:
                DTCommand._write_deps_file(project, deps_file, resolved)
                dtslogger.info(f"File '{deps_file}' modified")
            else:
                # print out file content
                sep: str = "-" * 30
                content: str = "\n".join(resolved)
                print(f"\n{deps_file}:\n{sep}\n{indent_block(content)}\n{sep}\n")

    @staticmethod
    def complete(shell, word, line):
        return []

    @staticmethod
    def _check_pinned(deps_file: str, wanted: List[str], strict: bool):
        # parse all deps and remove all comments
        deps: Dict[int, Requirement] = {
            i: Requirement.parse(d)
            for i, d in enumerate(wanted)
            if not DTCommand._is_comment(d)
        }
        # select what specs to use
        specs: Set[str] = STRICT_SPECS if strict else GOOD_SPECS
        extras: str = " strictly" if strict else ""
        # make sure our lists are pinned
        for i, dep in deps.items():
            found: bool = (
                len(specs.intersection(set(map(lambda s: s[0], dep.specs)))) > 0
            ) or (dep.vcs == "git" and dep.revision is not None)
            if not found:
                raise UnpinnedDependenciesError(
                    f"Dependency '{dep.name}' at {deps_file}:{i} is not{extras} pinned using "
                    f"the operator(s): {', '.join(specs)} ."
                )

    @staticmethod
    def _resolve_deps(wanted: List[str], pinned: List[str]) -> List[str]:
        resolved: List[Raw] = []
        wanted: List[Union[Comment, Requirement]] = [
            (w if DTCommand._is_comment(w) else Requirement.parse(w)) for w in wanted
        ]
        pinned: Dict[Raw, Union[Comment, Requirement]] = {
            p: (p if DTCommand._is_comment(p) else Requirement.parse(p)) for p in pinned
        }
        for dep in wanted:
            # keep comments
            if isinstance(dep, Comment):
                resolved.append(dep)
                continue
            rdep: Requirement = dep
            # match with pinned
            found: bool = False
            for dep1, rdep1 in pinned.items():
                if rdep.name.lower().strip() == rdep1.name.lower().strip():
                    resolved.append(dep1)
                    found = True
                    break
            # make sure we always have a match
            if not found:
                msg: str = f"Dependency '{dep}' not found in pip freeze."
                dtslogger.error(msg)
                dtslogger.debug(f"pip-freeze: {pinned}")
                raise UserError(msg)
        # ---
        return resolved

    @staticmethod
    def _is_comment(s: str) -> bool:
        return len(s) <= 0 or s.lstrip().startswith("#")

    @staticmethod
    def _count_deps(deps: List[str]) -> int:
        return len(deps) - len(list(filter(DTCommand._is_comment, deps)))

    @staticmethod
    def _write_deps_file(project: DTProject, deps_file: str, deps: List[str]):
        # no deps no file change
        ndeps: int = DTCommand._count_deps(deps)
        if ndeps <= 0:
            return
        # combine lines into single string
        content: str = "\n".join(deps) + "\n"
        # file location
        fpath: str = os.path.join(project.path, deps_file)
        if not os.path.exists(fpath) or not os.path.isfile(fpath):
            raise UserError(
                f"The file '{deps_file}' was not found in '{project.path}' though the project "
                f"is set to receive {ndeps} dependencies from that file. This should not have "
                f"appened."
            )
        # write to disk
        with open(fpath, "wt") as fout:
            fout.write(content)
