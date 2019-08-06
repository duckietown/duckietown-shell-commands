#!/bin/bash

# This script will flash an SD card with Hypriot

#for debugging, enable command printout
if [[ -n "$DEBUG" ]]; then
    set -xu
fi

set -e

VERSION=1 # Increment version to bust the cache
TMP_DIR="/tmp/duckietown"

# check required arguments
if [ -z "$INIT_SD_CARD_DEV" ]; then
  echo "The variable INIT_SD_CARD_DEV is required. Exiting..."
  exit 1
fi

if [ -z "$HYPRIOTOS_VERSION" ]; then
  echo "The variable HYPRIOTOS_VERSION is required. Exiting..."
  exit 1
fi

if [[ ! -f $TMP_DIR/version ]] || [[ "$(cat $TMP_DIR/version)" != "$VERSION" ]]; then
   rm -rf $TMP_DIR
fi

mkdir -p ${TMP_DIR}
echo "$VERSION" > $TMP_DIR/version

DEPS_LIST=(wget tar udisksctl docker base64  gzip udevadm)

if [[ $(uname -a) = *"x86_64"* ]]; then
    echo "64-bit OS detected..."
    ETCHER_URL="https://github.com/balena-io/etcher/releases/download/v1.4.4/etcher-cli-1.4.4-linux-x64.tar.gz"
else
    echo "Non 64-bit OS detected..."
    ETCHER_URL="https://github.com/balena-io/etcher/releases/download/v1.4.4/etcher-cli-1.4.4-linux-x86.tar.gz"
fi

ETCHER_DIR="${TMP_DIR}/etcher-cli"
TMP_ETCHER_LOCAL=$(mktemp -p ${TMP_DIR})

HYPRIOT_URL="https://github.com/hypriot/image-builder-rpi/releases/download/v${HYPRIOTOS_VERSION}/hypriotos-rpi-v${HYPRIOTOS_VERSION}.img.zip"
HYPRIOT_LOCAL="${TMP_DIR}/${HYPRIOT_URL##*/}"

IMAGE_DOWNLOADER_CACHEDIR="${TMP_DIR}/docker_images"
mkdir -p ${IMAGE_DOWNLOADER_CACHEDIR}

#MOD_FILE="${TMP_DIR}/mod"
#DUCKIE_ART_URL="https://raw.githubusercontent.com/duckietown/Software/master18/misc/duckie.art"
#WIFI_CONNECT_URL="https://github.com/balena-io/resin-wifi-connect/releases/download/v4.2.2/wifi-connect-v4.2.2-linux-rpi.tar.gz"

download_etcher() {
    if [[ -f "$ETCHER_DIR/etcher" ]]; then
        echo "Prior etcher-cli install detected at $ETCHER_DIR, skipping..."
    else
        # Download tool to burn image
        echo "Downloading etcher-cli..."
        wget -cO "${TMP_ETCHER_LOCAL}" "${ETCHER_URL}"

        # Unpack archive
        echo "Installing etcher-cli to $ETCHER_DIR..."
        mkdir -p $ETCHER_DIR && tar fvx ${TMP_ETCHER_LOCAL} -C ${ETCHER_DIR} --strip-components=1
    fi

    rm -rf ${TMP_ETCHER_LOCAL}
}

download_hypriot() {
    if [[ -f $HYPRIOT_LOCAL ]]; then
        echo "HypriotOS image was previously downloaded to $HYPRIOT_LOCAL, skipping..."
    else
        # Download the Hypriot Image echo "Downloading Hypriot image to ${HYPRIOT_LOCAL}"
        wget -cO ${HYPRIOT_LOCAL} ${HYPRIOT_URL}
        echo "Downloading Hypriot image complete."
    fi
}

flash_hypriot() {
    echo "Flashing Hypriot image $HYPRIOT_LOCAL to disk ${INIT_SD_CARD_DEV}"
    sudo -p "[sudo] Enter password for '%p' which is required to run Etcher: " \
        ${ETCHER_DIR}/etcher -d ${INIT_SD_CARD_DEV} -u false ${HYPRIOT_LOCAL}
    echo "Flashing Hypriot image succeeded."

}

download_etcher
download_hypriot
flash_hypriot
