import argparse
import os
from typing import Optional, List, Set

from dt_shell.commands import DTCommandConfigurationAbs

SUPPORTED_ARCHS: Set[str] = {"arm32v7", "amd64", "arm64v8"}


class DTCommandConfiguration(DTCommandConfigurationAbs):

    @classmethod
    def parser(cls, *args, **kwargs) -> Optional[argparse.ArgumentParser]:
        """
        The parser this command will use.
        """
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory containing the project to build",
        )
        parser.add_argument(
            "-a",
            "--arch",
            default=None,
            help="Target architecture(s) for the image to build",
        )
        parser.add_argument(
            "-H",
            "--machine",
            default=None,
            help="Docker socket or hostname where to build the image",
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
            "--no-cache",
            default=False,
            action="store_true",
            help="Skip the Docker cache",
        )
        parser.add_argument(
            "--force-cache",
            default=False,
            action="store_true",
            help="Whether to force Docker to use an old version of the same "
            "image as cache",
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
            "--push",
            default=False,
            action="store_true",
            help="Whether to push the resulting image",
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
            help="Path to use if specifying a custom local recipe path",
        )
        parser.add_argument(
            "--recipe-version",
            default=None,
            help="Branch to use if specifying a test branch of the recipes repository",
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
            choices=SUPPORTED_ARCHS,
            help="Forces CI to build on a specific architecture node",
        )
        parser.add_argument(
            "--cloud",
            default=False,
            action="store_true",
            help="Build the image on the cloud",
        )
        parser.add_argument(
            "--stamp",
            default=False,
            action="store_true",
            help="Stamp image with the build time",
        )
        parser.add_argument(
            "-D",
            "--destination",
            default=None,
            help="Docker socket or hostname where to deliver the image",
        )
        parser.add_argument(
            "--docs",
            default=False,
            action="store_true",
            help="Build the code documentation as well",
        )
        parser.add_argument(
            "--quiet", default=False, action="store_true", help="Be less verbose"
        )
        parser.add_argument(
            "--ncpus",
            default=None,
            type=int,
            help="Value to pass as build-arg `NCPUS` to docker build.",
        )
        parser.add_argument(
            "-v", "--verbose", default=False, action="store_true", help="Be verbose"
        )
        parser.add_argument(
            "--tag",
            default=None,
            help="Overrides 'version' (usually taken to be branch name)",
        )
        parser.add_argument(
            "--login",
            default=False,
            action="store_true",
            help="Login against the registry first",
        )
        # ---
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return ["buildx"]
