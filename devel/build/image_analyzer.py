#!/usr/bin/env python3
import dataclasses
import re
from typing import Optional, Dict

import termcolor as tc

__version__ = "1.1.0"

LAYER_SIZE_YELLOW = 20 * 1024**2  # 20 MB
LAYER_SIZE_RED = 75 * 1024**2  # 75 MB
SEPARATORS_LENGTH = 84
SEPARATORS_LENGTH_HALF = 25

EXTRA_INFO_SEPARATOR = "-" * SEPARATORS_LENGTH_HALF


@dataclasses.dataclass
class BuildLayer:
    type: str
    command: str
    size: float
    id: Optional[str] = None
    index: Optional[int] = None


@dataclasses.dataclass
class BuildStep:
    type: str
    command: str
    cached: bool = False
    layer: Optional[BuildLayer] = None


class ImageAnalyzer(object):
    @staticmethod
    def about():
        print()
        print("=" * 30)
        print(tc.colored("Docker Build Analyzer", "white", "on_blue"))
        print(f"Version: {__version__}")
        print("=" * 30)
        print()

    @staticmethod
    def size_fmt(num, suffix="B", precision=2):
        for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
            if abs(num) < 1024.0:
                # noinspection PyStringFormat
                return f"%3.{precision}f %s%s" % (num, unit, suffix)
            num /= 1024.0
        # noinspection PyStringFormat
        return f"%.{precision}f%s%s".format(num, "Yi", suffix)

    @staticmethod
    def process(buildlog, historylog, codens=0, extra_info=None, nocolor=False):
        lines = buildlog
        size_fmt = ImageAnalyzer.size_fmt

        # return if the log is empty
        if not lines:
            raise ValueError("The build log is empty")

        # return if the image history is empty
        if not historylog:
            raise ValueError("The image history is empty")

        if nocolor:
            tc.colored = lambda s, *_: s

        # define RegEx patterns
        step_pattern = re.compile(r"\[\s*([0-9]+)/([0-9]+)] (.*)")
        cache_string = "CACHED"

        # sanitize log
        lines = list(map(lambda s: s.strip("\n"), lines))

        # check if the build process succeded
        if not lines[-1].startswith("DONE"):
            exit(codens + 2)

        # find image tags
        image_names = []
        for line in reversed(lines):
            if line.startswith("naming to"):
                image_name = line[10:].split(" ")[0]
                image_names.append(image_name)

        print()
        ImageAnalyzer.about()

        # find "Step XY/TOT" lines
        steptot = -1
        steps_idx = [i for i in range(len(lines)) if step_pattern.match(lines[i])]

        # add end of lines to complete the ranges
        steps_ranges = steps_idx + [len(lines)]

        # sanitize history log
        historylog = [
            (lid[7:19] if lid.startswith("sha256:") else lid, size, _) for (lid, size, _) in historylog
        ]

        # create map {step_id: Layer}
        buildsteps: Dict[int, BuildStep] = {}
        last_FROM = -1
        for i, j in zip(steps_ranges, steps_ranges[1:]):
            stepline = lines[i]
            steplines = lines[i:j]
            # get step info
            stepno = int(step_pattern.match(stepline).group(1))
            steptot = int(step_pattern.match(stepline).group(2))
            stepcmd = re.sub(r"\s+", " ", step_pattern.match(stepline).group(3))
            steptype, stepcmd = stepcmd.split(" ", maxsplit=1)
            # cached?
            stepcached = len(list(filter(lambda s: s == cache_string, steplines))) == 1
            # find FROM layers
            if steptype == "FROM":
                last_FROM = stepno
            # add layer object
            buildsteps[stepno] = BuildStep(
                type=steptype,
                command=stepcmd,
                cached=stepcached,
            )

        # map steps to layers
        j = len(historylog) - 1
        base_image_size = 0
        final_image_size = 0

        for stepno in sorted(buildsteps.keys()):
            buildstep = buildsteps[stepno]
            while j >= 0:
                layerid, layersize, layercmd = historylog[j]
                layertype, layercmd = layercmd.split(" ", maxsplit=1)
                j -= 1

                final_image_size += layersize
                if stepno == last_FROM or layertype == buildstep.type:
                    buildstep.layer = BuildLayer(
                        type=layertype,
                        command=layercmd,
                        size=layersize,
                        id=layerid if "missing" not in layerid else None,
                        index=j,
                    )
                    break
                else:
                    base_image_size += layersize

        # for each Step, find the layer ID
        cached_layers = 0
        for stepno in sorted(buildsteps.keys()):
            buildstep = buildsteps[stepno]
            indent_str = "|"
            stepno_str = "Step:"
            size_str = "Size:"
            # check for cached layers
            step_cache = tc.colored("No", "red")
            if buildstep.type == "FROM":
                cached_layers += 1
                step_cache = tc.colored("--", "white")
            elif buildstep.cached:
                cached_layers += 1
                step_cache = tc.colored("Yes", "green")
            # get Step info
            print("-" * SEPARATORS_LENGTH)
            # get info about layer ID and size
            layersize = "ND"
            bg_color = "white"
            fg_color = "grey"
            # ---
            if buildstep.layer is not None and buildstep.layer.size is not None:
                layersize = size_fmt(buildstep.layer.size)
                fg_color = "white"
                bg_color = "yellow" if buildstep.layer.size > LAYER_SIZE_YELLOW else "green"
                bg_color = "red" if buildstep.layer.size > LAYER_SIZE_RED else bg_color
                bg_color = "blue" if stepno == 1 else bg_color

            indent_str = tc.colored(indent_str, fg_color, "on_" + bg_color)
            size_str = tc.colored(size_str, fg_color, "on_" + bg_color)
            stepno_str = tc.colored(stepno_str, fg_color, "on_" + bg_color)
            # print info about the current layer
            print(
                "%s %s/%s\n%sCached: %s\n%sCommand: \n%s\t%s %s\n%s%s %s"
                % (
                    stepno_str,
                    stepno,
                    steptot,
                    indent_str,
                    step_cache,
                    indent_str,
                    indent_str,
                    buildstep.type,
                    buildstep.command,
                    indent_str,
                    size_str,
                    layersize,
                )
            )
            print()

        # get info about layers
        tot_layers = len(buildsteps)
        cached_layers = min(tot_layers, cached_layers)

        # print info about the whole image
        if tot_layers > 1:
            print()
            print(
                "Legend: %s %s\t%s %s\t%s < %s\t%s < %s\t%s > %s\t"
                % (
                    tc.colored(" " * 2, "white", "on_white"),
                    "EMPTY LAYER",
                    tc.colored(" " * 2, "white", "on_blue"),
                    "BASE LAYER",
                    tc.colored(" " * 2, "white", "on_green"),
                    size_fmt(LAYER_SIZE_YELLOW, precision=1),
                    tc.colored(" " * 2, "white", "on_yellow"),
                    size_fmt(LAYER_SIZE_RED, precision=1),
                    tc.colored(" " * 2, "white", "on_red"),
                    size_fmt(LAYER_SIZE_RED, precision=1),
                )
            )
            print()
            print("=" * SEPARATORS_LENGTH)

        print("Final image name: %s" % ("\n" + " " * 18).join(image_names))
        if tot_layers > 1:
            print("Base image size: %s" % size_fmt(base_image_size))
            print("Final image size: %s" % size_fmt(final_image_size))
            print("Your image added %s to the base image." % size_fmt(final_image_size - base_image_size))
            print(EXTRA_INFO_SEPARATOR)
            print("Layers total: {:d}".format(tot_layers))
            print(" - Built: {:d}".format(tot_layers - cached_layers))
            print(" - Cached: {:d}".format(cached_layers))
        if extra_info is not None and len(extra_info) > 0:
            print(EXTRA_INFO_SEPARATOR)
            print(extra_info)
        print("=" * SEPARATORS_LENGTH)
        print()
        print(
            tc.colored("IMPORTANT", "white", "on_blue") + ": Always ask yourself, can I do better than that?"
        )
        print()
