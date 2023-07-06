# syntax=docker/dockerfile:1.4

# ==================================================>
# ==> Do not change the code below this line
ARG ARCH
ARG DISTRO
ARG DOCKER_REGISTRY=docker.io
ARG BASE_IMAGE=dt-jupyter-book
ARG BASE_TAG=${DISTRO}-${ARCH}
ARG LAUNCHER=default

# define base image
FROM ${DOCKER_REGISTRY}/duckietown/${BASE_IMAGE}:${BASE_TAG} as base

# recall all arguments
ARG DISTRO
ARG ICON
ARG BASE_TAG
ARG BASE_IMAGE
ARG LAUNCHER
# - buildkit
ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT

# define/create repository path
ARG REPO_PATH="${SOURCE_DIR}/book"
ARG LAUNCH_PATH="${LAUNCH_DIR}/book"
RUN mkdir -p "${REPO_PATH}" "${LAUNCH_PATH}"
WORKDIR "${REPO_PATH}"

# keep some arguments as environment variables
ENV DT_MODULE_TYPE="book" \
    DT_MODULE_DESCRIPTION="book" \
    DT_MODULE_ICON="book" \
    DT_MAINTAINER="everybody" \
    DT_REPO_PATH="${REPO_PATH}" \
    DT_LAUNCH_PATH="${LAUNCH_PATH}" \
    DT_LAUNCHER="${LAUNCHER}"

# install library
# TODO: install library here

# store module metadata
LABEL org.duckietown.label.module.type="book" \
    org.duckietown.label.module.description="book" \
    org.duckietown.label.module.icon="book" \
    org.duckietown.label.platform.os="${TARGETOS}" \
    org.duckietown.label.platform.architecture="${TARGETARCH}" \
    org.duckietown.label.platform.variant="${TARGETVARIANT}" \
    org.duckietown.label.code.location="${REPO_PATH}" \
    org.duckietown.label.code.version.distro="${DISTRO}" \
    org.duckietown.label.base.image="${BASE_IMAGE}" \
    org.duckietown.label.base.tag="${BASE_TAG}" \
    org.duckietown.label.maintainer="everybody"
# <== Do not change the code above this line
# <==================================================

# copy source (if given)
COPY --from=source . ${JB_SOURCE_DIR}
