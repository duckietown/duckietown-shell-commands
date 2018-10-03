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





declare -A PRELOADED_DOCKER_IMAGES=( \
    ["portainer"]="portainer/portainer:linux-arm" \
    ["watchtower"]="v2tec/watchtower:armhf-latest" \
    ["raspberrypi3-alpine-python"]="resin/raspberrypi3-alpine-python:slim"
# unfortunately we don't have space on the 1GB partition
#    ["rpi-health"]="duckietown/rpi-health:master18" \
#    ["simple-server"]="duckietown/rpi-simple-server:master18"
)



check_deps() {
    missing_deps=()
    for dep in ${DEPS_LIST[@]}; do
        if [ ! $(command -v ${dep}) ]; then
            missing_deps+=("${dep}")
        fi
    done
    if [ ${#missing_deps[@]} -ne 0 ]; then
        echo "The following dependencies are missing. Please install corresponding packages for:"
        echo "${missing_deps[@]}"
        [[ "$0" = "$BASH_SOURCE" ]] && exit 1 || return 1 # handle exits from shell or function but don't exit interactive shell
    fi
}

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


expand_partition() {
    echo PARTITION_TABLE=$PARTITION_TABLE

    if [ -f $PARTITION_TABLE ]; then
        echo "Expanding partition table"
        #sudo dd of=/dev/mmcblk0 if=$PARTITION_TABLE bs=512 count=1
        sudo parted -s /dev/mmcblk0 resizepart 2 "100%"
        sudo resize2fs /dev/mmcblk0p2
    else
        echo "Skipping expansion of partition table."
    fi
}


download_docker_image() {
    image_name="$1"
    docker_tag="$2"
    image_filename="${IMAGE_DOWNLOADER_CACHEDIR}/${image_name}.tar.gz"

    # download docker image if it doesn't exist
    if [ -f ${image_filename} ]; then
        echo "${docker_tag} was previously downloaded to ${image_filename}, skipping..."
    else
        echo "Downloading ${docker_tag} from Docker Hub..."
        docker pull ${docker_tag} && docker save ${docker_tag} | gzip --best > ${image_filename}
    fi
}

download_docker_images() {
    for image_name in "${!PRELOADED_DOCKER_IMAGES[@]}"; do
        docker_tag=${PRELOADED_DOCKER_IMAGES[$image_name]}
        download_docker_image ${image_name} ${docker_tag}
    done
}

preload_docker_images() {
    echo "Configuring DuckieOS installation..." 
    # Preload image(s) to speed up first boot
    echo "Writing preloaded Docker images to /var/local/"
    for image_name in "${!PRELOADED_DOCKER_IMAGES[@]}"; do
        docker_tag=${PRELOADED_DOCKER_IMAGES[$image_name]}
        image_filename="${IMAGE_DOWNLOADER_CACHEDIR}/${image_name}.tar.gz"
        # TODO: find a way to pre-load docker containers without needing SUDO access
        sudo cp ${image_filename} $TMP_ROOT_MOUNTPOINT/var/local/
        echo "Loaded $image_filename to $TMP_ROOT_MOUNTPOINT/var/local"
    done
}

write_configurations() {
    _cfg="$TMP_HYPRIOT_MOUNTPOINT/config.txt"
    # Add i2c to boot configuration
    sed $_cfg -i -e "s/^start_x=0/start_x=1/"
    # do not reserve a lot of memory of the GPU, as the line following demo needs about 750-800M!!!
    # sed $_cfg -i -e "s/^gpu_mem=16/gpu_mem=256/"
    echo "dtparam=i2c1=on" >> $_cfg
    echo "dtparam=i2c_arm=on" >> $_cfg
}

mount_disks() {
    # wait 1 second for the /dev/disk/by-label to be refreshed
    echo "Refreshing disks"
    sudo udevadm trigger
    sleep 5

    if [ ! -e "/dev/disk/by-label/root" ] || [ ! -e "/dev/disk/by-label/HypriotOS" ]; then
        echo "."
        sleep 1
        echo "."
        sleep 1
        echo "If you are using Ubuntu 16: Please remove and reinsert the SD card."
        sleep 5
        echo ""
        echo "Press any key to continue."
        read -n 1
    fi

    TMP_ROOT_MOUNTPOINT="/media/$USER/root"
    TMP_HYPRIOT_MOUNTPOINT="/media/$USER/HypriotOS"
    udisksctl mount -b /dev/disk/by-label/HypriotOS
    udisksctl mount -b /dev/disk/by-label/root
}

unmount_disks() {
    udisksctl unmount -b /dev/disk/by-label/HypriotOS
    udisksctl unmount -b /dev/disk/by-label/root
}

#write_userdata() {
#    echo "Writing custom cloud-init user-data..."
#    echo "$USER_DATA" > $TMP_HYPRIOT_MOUNTPOINT/user-data
#}


# main()

# configs
check_deps

# downloads
download_etcher
download_hypriot
download_docker_images

# flash
flash_hypriot

#write_custom_files
mount_disks
    expand_partition
    preload_docker_images
    write_configurations
#    write_userdata
    sync  # flush all buffers
#unmount_disks


echo "Finished preparing SD card. Please remove it and insert into the robot."

# echo "Wait for a minute, then visit the following URL: http://$HOST_NAME.local:9000/"
# echo "SSH access is also provided by: ssh $HOST_NAME.local [-i $IDENTITY_FILE]"

# XXX: this fails if the current computer does not have wifi enabled
## for example if it connects to the wifi using an ethernet connection to the switch
#if iwgetid -r; then
#    CURRENT_WIFI=$(iwgetid -r)
#else
#    exit 0
#fi

#if [ "$CURRENT_WIFI" != "$WIFISSID" ]; then
#    echo "Notice: the current WiFi network is '$CURRENT_WIFI', not '$WIFISSID'"
#    echo "If you do not join '$WIFISSID', then $HOST_NAME might be unreachable"
#fi
#echo "Alternately, join the WiFi '$DUCKSSID' to connect to $HOST_NAME directly"
echo "Press any key to continue"
read -n 1 -s -r 

# echo "Wait for a minute, then visit the following URL: http://$HOST_NAME:9000/"
# echo "SSH access is also provided by: ssh $HOST_NAME.local [-i $IDENTITY_FILE]"

#end main()

#  - 'LAST4_MAC=\$(sed -rn "s/^.*([0-9A-F:]{5})$/\\1/gi;s/://p" /sys/class/net/eth0/address); SUFFIX=\${LAST4_MAC:-0000}; echo "{ \"dnsmasq_cfg\": { \"address\": \"/#/192.168.27.1\", \"dhcp_range\": \"192.168.27.100,192.168.27.150,1h\", \"vendor_class\": \"set:device,IoT\" }, \"host_apd_cfg\": { \"ip\": \"192.168.27.1\", \"ssid\": \"$DUCKSSID-\$SUFFIX\", \"wpa_passphrase\": \"$DUCKPASS\", \"channel\":\"6\" }, \"wpa_supplicant_cfg\": { \"cfg_file\": \"/etc/wpa_supplicant/wpa_supplicant.conf\" } }" > /var/local/wificfg.json'
