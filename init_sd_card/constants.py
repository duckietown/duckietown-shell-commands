TIPS_AND_TRICKS = """

## Tips and tricks

### Multiple networks

    dts init_sd_card --wifi network1:password1,network2:password2 --country US



### Steps

Without arguments the script performs the steps:

    download
    flash
    setup

You can use --steps to run only some of those:

    dts init_sd_card --steps flash,setup


"""

LIST_DEVICES_CMD = "lsblk -p --output NAME,TYPE,SIZE,VENDOR | grep --color=never 'disk\|TYPE'"

INPUT_DEVICE_MSG = (
    "Please type the device with your SD card. "
    "Please be careful to pick the right device and to include '/dev/'. "
    "Here's a list of the devices on your system:"
)


WPA_OPEN_NETWORK_CONFIG = """
network={{
  id_str="{cname}"
  ssid="{ssid}"
  key_mgmt=NONE
}}
"""

WPA_PSK_NETWORK_CONFIG = """
network={{
  id_str="{cname}"
  ssid="{ssid}"
  psk="{psk}"
  key_mgmt=WPA-PSK
}}
"""

WPA_EAP_NETWORK_CONFIG = """
network={{
    id_str="{cname}"
    ssid="{ssid}"
    key_mgmt=WPA-EAP
    group=CCMP TKIP
    pairwise=CCMP TKIP
    eap=PEAP
    proto=RSN
    identity="{username}"
    password="{password}"
    phase1="peaplabel=0"
    phase2="auth=MSCHAPV2"
    priority=1
}}
"""
