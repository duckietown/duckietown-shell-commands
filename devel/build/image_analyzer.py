#!/usr/bin/env python3

import re
import sys
import argparse
import subprocess
from termcolor import colored

LAYER_SIZE_THR_YELLOW = 50 * 1024**2  # 50 MB
LAYER_SIZE_THR_RED = 200 * 1024**2    # 200 MB


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
    def sizeof_fmt(num, suffix='B'):
        for unit in ['','K','M','G','T','P','E','Z']:
            if abs(num) < 1024.0:
                return "%3.2f %s%s" % (num, unit, suffix)
            num /= 1024.0
        return "%.2f%s%s" % (num, 'Yi', suffix)

    @staticmethod
    def process(buildlog, historylog, codens=0):
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
        for l in image_history:
            layerid, layersize = l
            if layerid == 'missing':
                continue
            layer_to_size_bytes[layerid] = int(layersize)

        # for each Step, find the layer ID
        first_layer = None
        last_layer = None
        for i,j in zip(steps_idx, steps_idx[1:]):
            indent_str = '|'
            layerid_str = 'Layer ID:'
            size_str = 'Size:'
            cur_step_lines = lines[i:j]
            open_layers = [layer_pattern.match(l) for l in cur_step_lines if layer_pattern.match(l)]
            # get Step info
            print('-' * 22)
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
                if first_layer is None:
                    first_layer = layerid
                last_layer = layerid
            # ---
            if layerid in layer_to_size_bytes:
                layersize = sizeof_fmt(layer_to_size_bytes[layerid])
                fg_color = 'white'
                bg_color = 'yellow' if layer_to_size_bytes[layerid] > LAYER_SIZE_THR_YELLOW else 'green'
                bg_color = 'red' if layer_to_size_bytes[layerid] > LAYER_SIZE_THR_RED else bg_color
                bg_color = 'blue' if stepcmd.startswith('FROM') else bg_color

            indent_str = colored(indent_str, fg_color, 'on_'+bg_color)
            size_str = colored(size_str, fg_color, 'on_'+bg_color)
            layerid_str = colored(layerid_str, fg_color, 'on_'+bg_color)
            # print info about the current layer
            print(
                '%s %s\n%sStep: %s/%s\n%sCommand: \n%s\t%s\n%s%s %s' % (
                layerid_str, layerid,
                indent_str, stepno, steptot,
                indent_str, indent_str, stepcmd,
                indent_str, size_str, layersize
            ))
            print()

        # compute size of the base image
        first_layer_idx = [i for i in range(len(image_history)) if image_history[i][0] == first_layer][0]
        base_image_size = sum([int(l[1]) for l in image_history[first_layer_idx:]])

        # compute size of the final image
        final_image_size = sum([int(l[1]) for l in image_history])

        # print info about the whole image
        print()
        print('Legend: %s %s\t%s %s\t%s < %s\t%s < %s\t%s > %s\t' % (
            colored(' '*2, 'white', 'on_white'), 'EMPTY LAYER',
            colored(' '*2, 'white', 'on_blue'), 'BASE SIZE',
            colored(' '*2, 'white', 'on_green'), sizeof_fmt(LAYER_SIZE_THR_YELLOW),
            colored(' '*2, 'white', 'on_yellow'), sizeof_fmt(LAYER_SIZE_THR_RED),
            colored(' '*2, 'white', 'on_red'), sizeof_fmt(LAYER_SIZE_THR_RED)
        ))
        print()
        print('=' * 22)
        print('Final image name: %s' % image)
        print('Base image size: %s' % sizeof_fmt(base_image_size))
        print('Final image size: %s' % sizeof_fmt(final_image_size))
        print('Your image added %s to the base image.' % sizeof_fmt(final_image_size-base_image_size))
        print('=' * 22)
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
    lines = [l for l in sys.stdin if len(l.strip()) > 0]

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

    # get layers size from docker
    image_history = subprocess.check_output(
        ['docker'] + docker_H + ['history', '-H=false', '--format', '{{.ID}}:{{.Size}}', image],
    ).decode('utf-8')
    image_history = [l.split(':') for l in image_history.split('\n') if len(l.strip()) > 0]

    # run image analysis
    ImageAnalyzer.process(lines, image_history)
