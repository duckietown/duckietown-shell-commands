# syntax=docker/dockerfile:1.4

# ==================================================>
# ==> Do not change the code below this line
ARG ARCH
ARG DISTRO
ARG DOCKER_REGISTRY
ARG BASE_REPOSITORY
ARG BASE_ORGANIZATION=duckietown
ARG BASE_TAG=${DISTRO}-${ARCH}
ARG LAUNCHER=default

# define base image
FROM ${DOCKER_REGISTRY}/${BASE_ORGANIZATION}/${BASE_REPOSITORY}:${BASE_TAG} as base

# recall all arguments
ARG ARCH
ARG DISTRO
ARG DOCKER_REGISTRY
ARG BASE_TAG
ARG BASE_REPOSITORY
ARG BASE_ORGANIZATION
ARG LAUNCHER
# - buildkit
ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT

# setup environment
ENV INITSYSTEM="off" \
    TERM="xterm" \
    LANG="C.UTF-8" \
    LC_ALL="C.UTF-8" \
    PYTHONIOENCODING="UTF-8" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED="1" \
    DEBIAN_FRONTEND="noninteractive" \
    QEMU_EXECVE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

# keep some arguments as environment variables
ENV DT_LAUNCHER="${LAUNCHER}"

# copy assets
COPY --from=assets ./assets/bin/. /usr/local/bin/

# install apt dependencies (some of these are needed to build python wheels in dt-pip3-install)
COPY --from=project ./dependencies-apt.txt "/tmp/"
RUN dt-apt-install /tmp/dependencies-apt.txt

# install python3 dependencies
ARG PIP_INDEX_URL="https://pypi.org/simple"
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
COPY --from=project ./dependencies-py3.* "/tmp/"
RUN dt-pip3-install "/tmp/dependencies-py3.*"

# install launcher scripts
COPY --from=assets ./launchers/. "/tmp/launch/"
RUN dt-install-launchers "/tmp/launch"

# define default command
CMD ["bash", "-c", "dt-launcher-${DT_LAUNCHER}"]
# <== Do not change the code above this line
# <==================================================
