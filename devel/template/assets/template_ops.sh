#!/bin/bash

# Input args:
#   CODE_DIR
#   TEMPLATE_TYPE
#   TEMPLATE_VERSION
#   APPLY_DIFF
#   MODE
#

declare -A MODES=(
    ["conservative"]=":!assets :!code :!html :!docs :!launchers :!packages :!dependencies* :!configurations.yaml :!.dtproject :!dtproject/self.yaml :!.github :!.bumpversion.cfg :!README.md :!LICENSE.pdf" \
    ["brute"]="" \
)

exclusions=${MODES[$MODE]}

template_url="https://github.com/${TEMPLATE_TYPE}"
template_remote="template"

if [ -z ${TERM+x} ] || [ "${TERM}" = "dumb" ]; then
  export TERM=ansi
fi

# add template as a remote if it does not exist
git -C "${CODE_DIR}" remote add ${template_remote} ${template_url} &> /dev/null

close() {
    # remove template as a remote
    git -C "${CODE_DIR}" remote remove ${template_remote} &> /dev/null
    # ---
    exit $1
}

# update remote
git -C "${CODE_DIR}" remote update ${template_remote}

# get pretty-diff
SCRIPT_PATH="$( cd "$(dirname "$0")" ; pwd -P )"
PRETTY_DIFF="${SCRIPT_PATH}/diff-so-fancy"

# run git diff (human-readable show)
if [ "${APPLY_DIFF}" != "1" ]; then
  git \
    -c core.pager="${PRETTY_DIFF} | less --tabs=4 -RFX" \
    -C "${CODE_DIR}" \
    diff template/${TEMPLATE_VERSION} HEAD -- . ${exclusions}
  # ---
  close 0
fi

# run git diff
if [ "${APPLY_DIFF}" = "1" ]; then
  if [ -z "$(git status --porcelain)" ]; then
    # Working directory clean\
    set -e
    # apply the diff
    git \
      -C "${CODE_DIR}" \
      diff HEAD template/${TEMPLATE_VERSION} --binary -- . ${exclusions} \
    | git \
      -C "${CODE_DIR}" \
      apply
    # ---
    close 0
  else
    # uncommitted changes
    echo "You have uncommitted changes. Please commit or stash them before continuing."
    close 1
  fi

fi
