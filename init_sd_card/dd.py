#!/usr/bin/env python3

import math
import os
import sys
import time
import logging
import argparse
import pathlib

logging.basicConfig()
logger = logging.getLogger("dd")

utils_dir = os.path.join(pathlib.Path(__file__).parent.absolute(), "..", "utils")
sys.path.append(utils_dir)


def human_time(time_secs, compact=False):
    label = lambda s: s[0] if compact else " " + s
    days = int(time_secs // 86400)
    hours = int(time_secs // 3600 % 24)
    minutes = int(time_secs // 60 % 60)
    seconds = int(time_secs % 60)
    parts = []
    if days > 0:
        parts.append("{}{}".format(days, label("days")))
    if days > 0 or hours > 0:
        parts.append("{}{}".format(hours, label("hours")))
    if days > 0 or hours > 0 or minutes > 0:
        parts.append("{}{}".format(minutes, label("minutes")))
    parts.append("{}{}".format(seconds, label("seconds")))
    return ", ".join(parts)


class ProgressBar:
    def __init__(self, scale=1.0, buf=sys.stdout, header="Progress"):
        self._finished = False
        self._buffer = buf
        self._header = header
        self._last_value = -1
        self._scale = max(0.0, min(1.0, scale))
        self._max = int(math.ceil(100 * self._scale))

    def set_header(self, header):
        self._header = header

    def update(self, percentage):
        percentage_int = int(max(0, min(100, percentage)))
        if percentage_int == self._last_value:
            return
        percentage = int(math.ceil(percentage * self._scale))
        if self._finished:
            return
        # compile progress bar
        pbar = f"{self._header}: [" if self._scale > 0.5 else "["
        # progress
        pbar += "=" * percentage
        if percentage < self._max:
            pbar += ">"
        pbar += " " * (self._max - percentage - 1)
        # this ends the progress bar
        pbar += "] {:d}%".format(percentage_int)
        # print
        self._buffer.write(pbar)
        self._buffer.flush()
        # return to start of line
        self._buffer.write("\b" * len(pbar) + "\x1b[2K")
        # end progress bar
        if percentage >= self._max:
            self._buffer.write("Done!\n")
            self._buffer.flush()
            self._finished = True
        self._last_value = percentage_int

    def done(self):
        self.update(100)


# configure parser
parser = argparse.ArgumentParser()
parser.add_argument("-i", "--input", required=True, help="Input device or file")
parser.add_argument("-o", "--output", required=True, help="Output device or file")
parser.add_argument("-b", "--block-size", default=1024**2, type=int, help="Block size")
# parse arguments
parsed = parser.parse_args()

# make sure source and destination exist
if not os.path.exists(parsed.input):
    print(f"Fatal: input `{parsed.input}` not found.")
if not os.path.exists(parsed.output):
    print(f"Fatal: output `{parsed.output}` not found.")

# open source and destination
src_size = os.stat(parsed.input).st_size
written = 0
current_progress = 0
stime = time.time()
bar = ProgressBar(header="Flashing [ETA: ND]")

# open resources
src = open(parsed.input, "rb")
tgt = open(parsed.output, "wb")

# transfer chunks from source to target
try:
    chunk = src.read(parsed.block_size)
    while chunk:
        tgt.write(chunk)
        written += len(chunk)
        new_progress = int(written / src_size * 100.0)
        if new_progress != current_progress:
            # flush buffers and sync before notifying the new progress
            tgt.flush()
            os.fsync(tgt.fileno())
            # update progress and progress bar
            current_progress = new_progress
            bar.update(current_progress)
            # compute ETA
            elapsed = time.time() - stime
            eta = (100 - current_progress) * (elapsed / current_progress)
            bar.set_header("Flashing [ETA: {}]".format(human_time(eta, True)))
        # read next chunk
        chunk = src.read(parsed.block_size)
    # flus`h I/O buffer
    logger.info("Flushing I/O buffer...")
    os.fsync(tgt.fileno())
    logger.info("`Done!")
except KeyboardInterrupt:
    pass
finally:
    # close resources
    src.close()
    tgt.close()

# jump to 100% if success
bar.update(100)
logger.info("Flashed in {}".format(human_time(time.time() - stime)))
