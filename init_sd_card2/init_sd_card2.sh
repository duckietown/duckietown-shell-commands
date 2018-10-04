#!/bin/bash

# This script will flash an SD card with the necessary dependencies to run DuckieOS.
#
# Environment variables:
#
#  USER_DATA: user data payload

#for debugging, enable command printout
if [ -n "$DEBUG" ]; then
    set -xu
fi

set -e

VERSION=1 # Increment version to bust the cache
TMP_DIR="/tmp/duckietown"

if [ ! -f $TMP_DIR/version ] || [ "$(cat $TMP_DIR/version)" != "$VERSION" ]; then
   rm -rf $TMP_DIR
fi

mkdir -p ${TMP_DIR}
echo "$VERSION" > $TMP_DIR/version

DEPS_LIST=(wget tar udisksctl docker base64  gzip udevadm)

if [[ $(uname -a) = *"x86_64"* ]]; then
    echo "64-bit OS detected..."
    ETCHER_URL="https://github.com/resin-io/etcher/releases/download/v1.4.4/etcher-cli-1.4.4-linux-x64.tar.gz"
else
    echo "Non 64-bit OS detected..."
    ETCHER_URL="https://github.com/resin-io/etcher/releases/download/v1.4.4/etcher-cli-1.4.4-linux-x86.tar.gz"
fi

ETCHER_DIR="${TMP_DIR}/etcher-cli"
TMP_ETCHER_LOCAL=$(mktemp -p ${TMP_DIR})

HYPRIOT_URL="https://github.com/hypriot/image-builder-rpi/releases/download/v1.9.0/hypriotos-rpi-v1.9.0.img.zip"
HYPRIOT_LOCAL="${TMP_DIR}/${HYPRIOT_URL##*/}"

IMAGE_DOWNLOADER_CACHEDIR="${TMP_DIR}/docker_images"
mkdir -p ${IMAGE_DOWNLOADER_CACHEDIR}

MOD_FILE="${TMP_DIR}/mod"
DUCKIE_ART_URL="https://raw.githubusercontent.com/duckietown/Software/master18/misc/duckie.art"

WIFI_CONNECT_URL="https://github.com/resin-io/resin-wifi-connect/releases/download/v4.2.1/wifi-connect-v4.2.1-linux-rpi.tar.gz"




#
#declare -A PRELOADED_DOCKER_IMAGES=( \
#    ["portainer"]="portainer/portainer:linux-arm" \
#    ["watchtower"]="v2tec/watchtower:armhf-latest" \
#    ["raspberrypi3-alpine-python"]="resin/raspberrypi3-alpine-python:slim"
## unfortunately we don't have space on the 1GB partition
##    ["rpi-health"]="duckietown/rpi-health:master18" \
##    ["simple-server"]="duckietown/rpi-simple-server:master18"
#)
#
#
#
#check_deps() {
#    missing_deps=()
#    for dep in ${DEPS_LIST[@]}; do
#        if [ ! $(command -v ${dep}) ]; then
#            missing_deps+=("${dep}")
#        fi
#    done
#    if [ ${#missing_deps[@]} -ne 0 ]; then
#        echo "The following dependencies are missing. Please install corresponding packages for:"
#        echo "${missing_deps[@]}"
#        [[ "$0" = "$BASH_SOURCE" ]] && exit 1 || return 1 # handle exits from shell or function but don't exit interactive shell
#    fi
#}

download_etcher() {
    if [ -f "$ETCHER_DIR/etcher" ]; then
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
    if [ -f $HYPRIOT_LOCAL ]; then
        echo "HypriotOS image was previously downloaded to $HYPRIOT_LOCAL, skipping..."
    else
        # Download the Hypriot Image echo "Downloading Hypriot image to ${HYPRIOT_LOCAL}"
        wget -cO ${HYPRIOT_LOCAL} ${HYPRIOT_URL}
        echo "Downloading Hypriot image complete."
    fi
}

flash_hypriot() {

    echo "Flashing Hypriot image $HYPRIOT_LOCAL to disk..."
    sudo -p "[sudo] Enter password for '%p' which is required to run Etcher: " \
        ${ETCHER_DIR}/etcher -u false ${HYPRIOT_LOCAL}
    echo "Flashing Hypriot image succeeded."

}

# main()

download_etcher
download_hypriot

# flash
flash_hypriot


echo "Finished preparing SD card. Please remove it and insert into the robot."

#  - 'LAST4_MAC=\$(sed -rn "s/^.*([0-9A-F:]{5})$/\\1/gi;s/://p" /sys/class/net/eth0/address); SUFFIX=\${LAST4_MAC:-0000}; echo "{ \"dnsmasq_cfg\": { \"address\": \"/#/192.168.27.1\", \"dhcp_range\": \"192.168.27.100,192.168.27.150,1h\", \"vendor_class\": \"set:device,IoT\" }, \"host_apd_cfg\": { \"ip\": \"192.168.27.1\", \"ssid\": \"$DUCKSSID-\$SUFFIX\", \"wpa_passphrase\": \"$DUCKPASS\", \"channel\":\"6\" }, \"wpa_supplicant_cfg\": { \"cfg_file\": \"/etc/wpa_supplicant/wpa_supplicant.conf\" } }" > /var/local/wificfg.json'
