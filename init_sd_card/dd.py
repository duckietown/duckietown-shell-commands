#!/usr/bin/env python3

import argparse
import logging
import os
import pathlib
import sys
import time

from utils.misc_utils import human_time
from utils.progress_bar import ProgressBar

logging.basicConfig()
logger = logging.getLogger("dd")

utils_dir = os.path.join(pathlib.Path(__file__).parent.absolute(), "..", "utils")
sys.path.append(utils_dir)

# import progress_bar
# import misc_utils


# configure parser
parser = argparse.ArgumentParser()
parser.add_argument("-i", "--input", required=True, help="Input device or file")
parser.add_argument("-o", "--output", required=True, help="Output device or file")
parser.add_argument("-b", "--block-size", default=1024 ** 2, type=int, help="Block size")
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
pbar = ProgressBar(header="Flashing [ETA: ND]")

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
            pbar.update(current_progress)
            # compute ETA
            elapsed = time.time() - stime
            eta = (100 - current_progress) * (elapsed / current_progress)
            pbar.set_header("Flashing [ETA: {}]".format(human_time(eta, True)))
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
pbar.update(100)
logger.info("Flashed in {}".format(human_time(time.time() - stime)))
