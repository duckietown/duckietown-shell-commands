#!/bin/bash

# This script will flash an SD card with the necessary dependencies to run DuckieOS.
#
# Usage: [duckiebot_compose_file=<ABSOLUTE PATH>] [duckietoken=<TOKEN>] DuckieOS1-RPI3Bp.sh
#
# Environment variables:
#           duckietoken:		User's Duckietown token. Will be flashed to root partition at ~/.dt-shell/duckietoken.
#           duckiebot_compose_file: 	Path to the Duckiebot's primary docker-compose.yml config. Will use default if empty.

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

DEPS_LIST=(wget tar udisksctl docker base64 ssh-keygen iwgetid gzip udevadm date)

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


echo ---- Configuration passed: ---
echo IDENTITY_FILE=$IDENTITY_FILE
echo HOST_NAME=$HOST_NAME
echo USERNAME=$USERNAME
echo PASSWORD=$PASSWORD
echo WIFISSID=$WIFISSID
echo WIFIPASS=$WIFIPASS
echo ------------------------------

if [ ! -f $IDENTITY_FILE ]; then
    echo "Please set the environment variable IDENTITY_FILE to the path of a public key. "
    exit 1
fi


if [ -z "$HOST_NAME" ]; then
    echo "Please set variable HOST_NAME"
    exit 1
fi

if [ -z "$USERNAME" ]; then
    echo "Please set variable $USERNAME"
    exit 1
fi

if [ -z "$PASSWORD" ]; then
    echo "Please set variable $PASSWORD"
    exit 1
fi

if [ -z "WIFISSID" ]; then
    echo "Please set variable WIFISSID"
    exit 1
fi

if [ -z "WIFIPASS" ]; then
    echo "Please set variable WIFIPASS"
    exit 1
fi


declare -A PRELOADED_DOCKER_IMAGES=( \
    ["portainer"]="portainer/portainer:linux-arm" \
    ["watchtower"]="v2tec/watchtower:armhf-latest" \
    ["raspberrypi3-alpine-python"]="resin/raspberrypi3-alpine-python:slim"
# unfortunately we don't have space on the 1GB partition
#    ["rpi-health"]="duckietown/rpi-health:master18" \
#    ["simple-server"]="duckietown/rpi-simple-server:master18"
)

read_password() {
    # thanks: https://stackoverflow.com/questions/1923435/how-do-i-echo-stars-when-reading-password-with-read
    # unset password
    password=""
    prompt=$1
    while IFS= read -p "$prompt" -r -s -n 1 char
    do
        if [[ $char == $'\0' ]]; then
            break
        fi
        # thanks: https://askubuntu.com/questions/299437/how-can-i-use-the-backspace-character-as-a-backspace-when-entering-a-password
        if [[ $char == $'\177' ]]; then
            prompt=$'\b \b'
            password="${password%?}"
        else
            prompt='*'
            password+="$char"
        fi
    done
    echo
    # thanks: https://stackoverflow.com/questions/3236871/how-to-return-a-string-value-from-a-bash-function
    eval "$2='$password'"
}

prompt_for_configs() {
    echo "Configuring DuckiebotOS (press ^C to cancel)..."
    
#    DEFAULT_HOSTNAME="duckiebot"
#    DEFAULT_USERNAME="duckie"
#    DEFAULT_PASSWORD="quackquack"
#    DEFAULT_WIFISSID="duckietown"
#    DEFAULT_WIFIPASS="quackquack"
#
    #read -p "Please enter a username (default is $DEFAULT_USERNAME) > " USERNAME
    #USERNAME=${USERNAME:-$DEFAULT_USERNAME}
#    USERNAME=${DEFAULT_USERNAME}
    #read_password "Please enter a password (default is $DEFAULT_PASSWORD) > " PASSWORD
    #PASSWORD=${PASSWORD:-$DEFAULT_PASSWORD}
#    PASSWORD=${DEFAULT_PASSWORD}

#    read -p "Please enter a hostname (default is $DEFAULT_HOSTNAME) > " HOST_NAME
#    HOST_NAME=${HOST_NAME:-$DEFAULT_HOSTNAME}


#    read -p "Please enter a WiFi SSID (default is $DEFAULT_WIFISSID) > " WIFISSID
#    WIFISSID=${WIFISSID:-$DEFAULT_WIFISSID}
#    read_password "Please enter a WiFi PSK (default is $DEFAULT_WIFIPASS) > " WIFIPASS
#    WIFIPASS=${WIFIPASS:-$DEFAULT_WIFIPASS}

    #Removed until we can get a stable wifi
    #DEFAULT_DUCKPASS="$DEFAULT_PASSWORD"
    #DEFAULT_DUCKSSID="$HOST_NAME"
    #read -p "Please enter a Duckiebot SSID (default is $DEFAULT_DUCKSSID) > " DUCKSSID
    #DUCKSSID=${DUCKSSID:-$DEFAULT_DUCKSSID}
    #read_password "Please enter Duckiebot PSK (default is $DEFAULT_DUCKPASS) > " DUCKPASS
    #DUCKPASS=${DUCKPASS:-$DEFAULT_DUCKPASS}
}

validate_userdata() {
###############################################################################
####### WARNING: Be very careful when modifying the cloud-init payload. #######
####### Each and every character has been choosen with the utmost care. #######
####### We attempt to validate the userdata, but this is not foolproof. #######
###############################################################################
USER_DATA=$(cat <<EOF
#cloud-config
# vim: syntax=yaml

# The currently used version of cloud-init is 0.7.9
# http://cloudinit.readthedocs.io/en/0.7.9/index.html

hostname: $HOST_NAME
manage_etc_hosts: true

users:
  - name: $USERNAME
    gecos: "Duckietown"
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    groups: users,docker,video
    plain_text_passwd: $PASSWORD
    lock_passwd: false
    ssh_pwauth: true
    chpasswd: { expire: false }

package_upgrade: false

write_files:
  - content: |
      allow-hotplug wlan0
      iface wlan0 inet dhcp
    path: /etc/network/interfaces.d/wlan0
  - encoding: b64 
    content: $DUCKIE_ART
    path: /etc/update-motd.d/duckie.art
  - content: |
      #!/bin/sh
      printf "\n\$(cat /etc/update-motd.d/duckie.art)\n"
    path: /etc/update-motd.d/20-duckie
    permissions: '0755'
  - content: $PUB_KEY
    path: /home/$USERNAME/.ssh/authorized_keys
  - content: | 
$duckiebot_compose_yaml
    path: /var/local/docker-compose.yml
#  - content: |
#      {
#          "dnsmasq_cfg": {
#             "address": "/#/192.168.27.1",
#             "dhcp_range": "192.168.27.100,192.168.27.150,1h",
#             "vendor_class": "set:device,IoT"
#          },
#          "host_apd_cfg": {
#             "ip": "192.168.27.1",
#             "ssid": "$DUCKSSID",
#             "wpa_passphrase": "$DUCKPASS",
#             "channel": "6"
#          },
#          "wpa_supplicant_cfg": {
#             "cfg_file": "/etc/wpa_supplicant/wpa_supplicant.conf"
#          }
#      }
#    path: /var/local/wificfg.json
  - content: |
      country=CA
      ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
      update_config=1
      network={
          ssid="$WIFISSID"
          psk="$WIFIPASS"
          key_mgmt=WPA-PSK
      }
    path: /etc/wpa_supplicant/wpa_supplicant.conf
  - content: |
      i2c-bcm2708
      i2c-dev
    path: /etc/modules
  - content: |
      [Unit]
      Description=Docker Socket for the API

      [Socket]
      ListenStream=2375
      BindIPv6Only=both
      Service=docker.service

      [Install]
      WantedBy=sockets.target
    path: /etc/systemd/system/docker-tcp.socket
#  - content: |
#    docker exec -it rpi-duckiebot-base bash || docker start -i rpi-duckiebot-base || docker run -it --name rpi-duckiebot-base -v /var/run/docker.sock:/var/run/docker.sock -v /data:/data --privileged --net host duckietown/rpi-duckiebot-base bash
#    path: /home/$USERNAME/.bash_profile
${duckietoken+"  - content: $duckietoken
    path: /home/$USERNAME/.dt_shell/duckie_token"
}

# These commands will be run once on first boot only
runcmd:
  - 'systemctl restart avahi-daemon'
# Create /data directory for storing Duckiebot-local configuration files
  - 'mkdir /data && chown 1000:1000 /data'
# Change the date to use the date of the flashing machine
  - 'date -s "$(date "+%Y-%m-%d %H:%M:%S")"'
# Copy all the hardware information (e.g. serial number) to /data/proc
  - 'mkdir /data/proc && cp /proc/*info /data/proc'

#   - [ modprobe, i2c-bcm2708 ]
#   - [ modprobe, i2c-dev ]
  - [ systemctl, stop, docker ]
  - [ systemctl, daemon-reload ]
  - [ systemctl, enable, docker-tcp.socket ]
  - [ systemctl, start, --no-block, docker-tcp.socket ]
  - [ systemctl, start, --no-block, docker ]
#  - 'LAST4_MAC=\$(sed -rn "s/^.*([0-9A-F:]{5})$/\\1/gi;s/://p" /sys/class/net/eth0/address); SUFFIX=\${LAST4_MAC:-0000}; echo "{ \"dnsmasq_cfg\": { \"address\": \"/#/192.168.27.1\", \"dhcp_range\": \"192.168.27.100,192.168.27.150,1h\", \"vendor_class\": \"set:device,IoT\" }, \"host_apd_cfg\": { \"ip\": \"192.168.27.1\", \"ssid\": \"$DUCKSSID-\$SUFFIX\", \"wpa_passphrase\": \"$DUCKPASS\", \"channel\":\"6\" }, \"wpa_supplicant_cfg\": { \"cfg_file\": \"/etc/wpa_supplicant/wpa_supplicant.conf\" } }" > /var/local/wificfg.json'
# Disabled pre-loading duckietown/software due to insuffient space on /var/local
# https://github.com/hypriot/image-builder-rpi/issues/244#issuecomment-390512469
#  - [ docker, load, "--input", "/var/local/software.tar.gz"]

# Portainer Web UI
  - [ docker, load, --input, "/var/local/portainer.tar.gz" ]
# Watchtower live updates
  - [ docker, load, --input, "/var/local/watchtower.tar.gz" ]
# Lightweight Python image / Simple HTTP Server
  - [ docker, load, --input, "/var/local/raspberrypi3-alpine-python.tar.gz" ]

# Launch the previous containers
  - [ docker-compose, --file, "/var/local/docker-compose.yml", up ]

# These commands will be run on every boot
bootcmd:
# Generate the unique duckiebot SSID on first boot, based on the MAC address, broadcast to random channel
  - 'iwconfig wlan0 power off'
EOF
)
###############################################################################
################################ END WARNING ##################################
###############################################################################

    echo "Validating user-data file..."
    VALIDATION_RESULT=$(wget -qO- "https://validate.core-os.net/validate" --method=PUT --body-data="$USER_DATA" || true)
    echo "Validation result: $(echo "$VALIDATION_RESULT" | python -m json.tool)"
    if echo "$VALIDATION_RESULT" | grep -q '"kind":"error"'; then
        >&2 echo "Critical error! Invalid cloud-init user-data: $USER_DATA"
        exit 1 
    fi
}

validate_duckiebot_compose() {
    if [ -z "$duckiebot_compose_file" ]; then
        duckiebot_compose_file="$TMP_DIR/duckiebot-compose.yml"
        echo "Using default Docker compose config, $duckiebot_compose_file"
        echo "$(cat <<EOF
version: '3'
services:
  portainer:
    image: portainer/portainer:linux-arm
    command: ["--host=unix:///var/run/docker.sock", "--no-auth"]
    restart: unless-stopped
    network_mode: "host"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
  watchtower:
    image: v2tec/watchtower:armhf-latest
    command: ["--cleanup"]
    restart: unless-stopped
    network_mode: "host"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
  http-server:
    image: duckietown/rpi-simple-server:master18
    restart: unless-stopped
    network_mode: "host"
    volumes:
      - data-volume:/data
    working_dir: /data
  rpi-health:
    image: duckietown/rpi-health:master18
    restart: unless-stopped
    network_mode: "host"
    devices:
    - "/dev/vchiq:/dev/vchiq"

volumes:
  data-volume:
    driver: local
    driver_opts:
      type: none
      device: /data
      o: bind
EOF
)" > $duckiebot_compose_file
    fi

# TODO: create separate docker-compose.yml file for duckietown containers
#     lanefollowing-demo:
#         image: duckietown/rpi-duckiebot-lanefollowing-demo
#         command: ["sleep infinity"]
#         volumes:
#         - data:/duckietown-data
#         depends_on:
#         - "wifi"
#     joystick-demo:
#         image: duckietown/rpi-duckiebot-joystick-demo
#         command: ["sleep infinity"]
#         volumes:
#         - data:/duckietown-data
#         depends_on:
#         - "wifi"
#     calibration:
#         image: duckietown/rpi-duckiebot-calibration
#         command: ["sleep infinity"]
#         volumes:
#         - data:/duckietown-data
#         depends_on:
#         - "wifi"
#     gym-duckietown-agent:
#         image: duckietown/gym-duckietown-agent:arm
#         command: ["sleep infinity"]
#         volumes:
#         - data:/duckietown-data
#         depends_on:
#         - "wifi"
#     slimremote:
#         image: duckietown/duckietown-slimremote
#         command: ["sleep infinity"]
#         depends_on:
#         - "wifi"
# volumes:
#     data:

    # If docker-compose is available on the host, attempt to validate
    if [ $(command -v docker-compose) ]; then
        docker-compose -f $duckiebot_compose_file config --quiet
        if [ $? -ne 0 ]; then
            >&2 echo "Critical error! Invalid Duckiebot compose: $duckiebot_compose_file"
            exit 1
        fi
    fi
    # Fixes indentation for nesting YAML into cloud-init userdata properly
    duckiebot_compose_yaml=$(cat $duckiebot_compose_file | sed -e 's/^/      /')
}

verify_duckietoken() {
    if [ -n "$duckietoken" ]; then
        if [ !$(dt tok verify $duckietoken) ]; then
            >&2 echo "Critical error! Unable to verify Duckie Token."
            exit 1 
        fi
    fi
}

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

fetch_motd() {
    # todo: check if the file on the server changed
    #if [ ! -f $MOD_FILE ]; then
    echo "Downloading Message of the Day"
    wget --no-check-certificate -O $MOD_FILE $DUCKIE_ART_URL
    #fi
    DUCKIE_ART=$(cat $MOD_FILE | base64 -w 0)
}

copy_ssh_credentials() {
    PUB_KEY=$(cat $IDENTITY_FILE)
}

mount_disks() {
    # wait 1 second for the /dev/disk/by-label to be refreshed
    echo "Refreshing disks"
    sudo udevadm trigger
    sleep 5

    if [ ! -e "/dev/disk/by-label/root" ] || [ ! -e "/dev/disk/by-label/HypriotOS" ]; then
        echo "Downloading Message of the Day"
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

write_userdata() {
    echo "Writing custom cloud-init user-data..."
    echo "$USER_DATA" > $TMP_HYPRIOT_MOUNTPOINT/user-data
}

unset_env_vars() {
    unset duckiebot_compose_file
    unset duckietoken
}

# main()

# configs
check_deps
prompt_for_configs
fetch_motd
copy_ssh_credentials
validate_duckiebot_compose
verify_duckietoken
validate_userdata
unset_env_vars

# downloads
download_etcher
download_hypriot
download_docker_images

# flash
flash_hypriot

#write_custom_files
mount_disks
    preload_docker_images
    write_configurations
    write_userdata
    sync  # flush all buffers
unmount_disks


echo "Finished preparing SD card. Please remove it and insert into $HOST_NAME."

# echo "Wait for a minute, then visit the following URL: http://$HOST_NAME.local:9000/"
# echo "SSH access is also provided by: ssh $HOST_NAME.local [-i $IDENTITY_FILE]"

# XXX: this fails if the current computer does not have wifi enabled
# for example if it connects to the wifi using an ethernet connection to the switch
if iwgetid -r; then
    CURRENT_WIFI=$(iwgetid -r)
else
    exit 0
fi

if [ "$CURRENT_WIFI" != "$WIFISSID" ]; then
    echo "Notice: the current WiFi network is '$CURRENT_WIFI', not '$WIFISSID'"
    echo "If you do not join '$WIFISSID', then $HOST_NAME might be unreachable"
fi
#echo "Alternately, join the WiFi '$DUCKSSID' to connect to $HOST_NAME directly"
echo "Press any key to continue"
read -n 1 -s -r 

# echo "Wait for a minute, then visit the following URL: http://$HOST_NAME:9000/"
# echo "SSH access is also provided by: ssh $HOST_NAME.local [-i $IDENTITY_FILE]"

#end main()
