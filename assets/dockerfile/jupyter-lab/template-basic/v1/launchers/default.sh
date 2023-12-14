#!/bin/bash

# YOUR CODE BELOW THIS LINE
# ----------------------------------------------------------------------------

set -e

# add project directory to PYTHONPATH with highest priority
export PYTHONPATH=${DT_PROJECT_PATH}/packages/:${PYTHONPATH}

# run Jupyter Lab
exec jupyter lab --ip=${JUPYTER_LAB_HOST} --port=${JUPYTER_LAB_PORT}


# ----------------------------------------------------------------------------
# YOUR CODE ABOVE THIS LINE
