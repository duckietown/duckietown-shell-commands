# syntax=docker/dockerfile:1.4

# ==================================================>
# ==> Do not change the code below this line
ARG ARCH
ARG DISTRO=ente
ARG DOCKER_REGISTRY
ARG BASE_REPOSITORY=dt-commons
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

# keep some arguments as environment variables
ENV DT_LAUNCHER="${LAUNCHER}"
ENV DT_PROJECT_PATH=/project

# move to the project location
WORKDIR ${DT_PROJECT_PATH}

# install jupyter lab (pinned just to be future-proof)
RUN pip3 install jupyterlab==4.0.9

# install project's library
COPY --from=project . ${DT_PROJECT_PATH}
RUN pip3 install ${DT_PROJECT_PATH}

# install launcher scripts
COPY --from=assets ./launchers/. "/tmp/launch/"
RUN dt-install-launchers "/tmp/launch"
# <== Do not change the code above this line
# <==================================================
