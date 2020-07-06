#!/usr/bin/env python3

import re
import sys
import argparse
import subprocess
from termcolor import colored

LAYER_SIZE_THR_YELLOW = 20 * 1024**2  # 20 MB
LAYER_SIZE_THR_RED = 75 * 1024**2    # 75 MB
SEPARATORS_LENGTH = 84
SEPARATORS_LENGTH_HALF = 25

EXTRA_INFO_SEPARATOR = '-' * SEPARATORS_LENGTH_HALF


class ImageAnalyzer(object):

    @staticmethod
    def about():
        print()
        print('='*30)
        print(colored('Docker Build Analyzer', 'white', 'on_blue'))
        print('Maintainer: Andrea F. Daniele (afdaniele@ttic.edu)')
        print('='*30)
        print()

    @staticmethod
    def sizeof_fmt(num, suffix='B', precision=2):
        for unit in ['', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']:
            if abs(num) < 1024.0:
                return f"%3.{precision}f %s%s" % (num, unit, suffix)
            num /= 1024.0
        return f"%.{precision}f%s%s".format(num, 'Yi', suffix)

    @staticmethod
    def process(buildlog, historylog, codens=0, extra_info=None):
        lines = buildlog
        image_history = historylog
        sizeof_fmt = ImageAnalyzer.sizeof_fmt

        # return if the log is empty
        if not lines:
            raise ValueError('The build log is empty')

        # return if the image history is empty
        if not image_history:
            raise ValueError('The image history is empty')

        # define RegEx patterns
        step_pattern = re.compile("Step ([0-9]+)/([0-9]+) : (.*)")
        layer_pattern = re.compile(" ---> ([0-9a-z]{12})")
        cache_string = ' ---> Using cache'
        final_layer_pattern = re.compile("Successfully tagged (.*)")

        # check if the build process succeded
        if not final_layer_pattern.match(lines[-1]):
            exit(codens+2)
        image = final_layer_pattern.match(lines[-1]).group(1)

        print()
        ImageAnalyzer.about()

        # find "Step XY/TOT" lines
        steps_idx = [i for i in range(len(lines)) if step_pattern.match(lines[i])] + [len(lines)]

        # create map {layerid: size_bytes}
        layer_to_size_bytes = dict()
        for layerid, layersize in image_history:
            if layerid == 'missing':
                continue
            layer_to_size_bytes[layerid] = int(layersize)

        # for each Step, find the layer ID
        first_layer = None
        cached_layers = 0
        for i, j in zip(steps_idx, steps_idx[1:]):
            indent_str = '|'
            layerid_str = 'Layer ID:'
            size_str = 'Size:'
            cur_step_lines = lines[i:j]
            open_layers = [
                layer_pattern.match(line) for line in cur_step_lines if layer_pattern.match(line)
            ]
            # check for cached layers
            step_cache = colored('No', 'red')
            if len(cur_step_lines) <= 2 or \
               len(list(filter(lambda s: s == cache_string, cur_step_lines))) == 1:
                cached_layers += 1
                step_cache = colored('Yes', 'green')
            # get Step info
            print('-' * SEPARATORS_LENGTH)
            stepline = lines[i]
            stepno = step_pattern.match(stepline).group(1)
            steptot = step_pattern.match(stepline).group(2)
            stepcmd = re.sub(' +', ' ', step_pattern.match(stepline).group(3))
            # get info about layer ID and size
            layerid = None
            layersize = 'ND'
            bg_color = 'white'
            fg_color = 'grey'
            if len(open_layers) > 0:
                layerid = open_layers[0].group(1)
                if stepcmd.startswith('FROM'):
                    first_layer = layerid
                    cached_layers += 1
            # ---
            if layerid in layer_to_size_bytes:
                layersize = sizeof_fmt(layer_to_size_bytes[layerid])
                fg_color = 'white'
                bg_color = 'yellow' if layer_to_size_bytes[layerid] > LAYER_SIZE_THR_YELLOW \
                    else 'green'
                bg_color = 'red' if layer_to_size_bytes[layerid] > LAYER_SIZE_THR_RED else bg_color
                bg_color = 'blue' if stepcmd.startswith('FROM') else bg_color

            indent_str = colored(indent_str, fg_color, 'on_'+bg_color)
            size_str = colored(size_str, fg_color, 'on_'+bg_color)
            layerid_str = colored(layerid_str, fg_color, 'on_'+bg_color)
            # print info about the current layer
            print(
                '%s %s\n%sStep: %s/%s\n%sCached: %s\n%sCommand: \n%s\t%s\n%s%s %s' % (
                    layerid_str, layerid,
                    indent_str, stepno, steptot,
                    indent_str, step_cache,
                    indent_str, indent_str, stepcmd,
                    indent_str, size_str, layersize
                )
            )
            print()

        # get info about layers
        tot_layers = len(steps_idx) - 1
        cached_layers = min(tot_layers, cached_layers)

        # compute size of the base image
        first_layer_idx = [
            i for i in range(len(image_history)) if image_history[i][0] == first_layer
        ][0]
        base_image_size = sum([int(line[1]) for line in image_history[first_layer_idx:]])

        # compute size of the final image
        final_image_size = sum([int(line[1]) for line in image_history])

        # print info about the whole image
        print()
        print(
            'Legend: %s %s\t%s %s\t%s < %s\t%s < %s\t%s > %s\t' % (
                colored(' '*2, 'white', 'on_white'), 'EMPTY LAYER',
                colored(' '*2, 'white', 'on_blue'), 'BASE LAYER',
                colored(' '*2, 'white', 'on_green'), sizeof_fmt(LAYER_SIZE_THR_YELLOW, precision=1),
                colored(' '*2, 'white', 'on_yellow'), sizeof_fmt(LAYER_SIZE_THR_RED, precision=1),
                colored(' '*2, 'white', 'on_red'), sizeof_fmt(LAYER_SIZE_THR_RED, precision=1)
            )
        )
        print()
        print('=' * SEPARATORS_LENGTH)
        print('Final image name: %s' % image)
        print('Base image size: %s' % sizeof_fmt(base_image_size))
        print('Final image size: %s' % sizeof_fmt(final_image_size))
        print('Your image added %s to the base image.' % sizeof_fmt(final_image_size-base_image_size))
        print(EXTRA_INFO_SEPARATOR)
        print('Layers total: {:d}'.format(tot_layers))
        print(' - Built: {:d}'.format(tot_layers - cached_layers))
        print(' - Cached: {:d}'.format(cached_layers))
        if extra_info is not None and len(extra_info) > 0:
            print(EXTRA_INFO_SEPARATOR)
            print(extra_info)
        print('=' * SEPARATORS_LENGTH)
        print()
        print(colored('IMPORTANT', 'white', 'on_blue') + ': Always ask yourself, can I do better than that? ;)')
        print()
        # ---
        return image, base_image_size, final_image_size


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--machine', default="", help="Hostname of the machine running the build")
    parsed = parser.parse_args()

    # put lines from the pipe in a list
    final_layer_pattern = re.compile("Successfully tagged (.*)")
    lines = [line for line in sys.stdin if len(line.strip()) > 0]

    # return if the log is empty
    if not lines:
        exit(1)

    # handle remote build
    docker_H = []
    if len(parsed.machine) > 0:
        docker_H = ['-H', parsed.machine]

    # check if the build process succeded
    if not final_layer_pattern.match(lines[-1]):
        exit(2)
    image = re.match(final_layer_pattern, lines[-1]).group(1)

    # get layers size from docker
    image_history = subprocess.check_output(
        ['docker'] + docker_H + ['history', '-H=false', '--format', '{{.ID}}:{{.Size}}', image],
    ).decode('utf-8')
    image_history = [l.split(':') for l in image_history.split('\n') if len(l.strip()) > 0]

    # run image analysis
    ImageAnalyzer.process(lines, image_history)
