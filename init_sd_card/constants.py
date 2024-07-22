TIPS_AND_TRICKS = """

## Tips and tricks

### Multiple networks

    dts init_sd_card --wifi network1:password1,network2:password2 --country US



### Steps

Without arguments the script performs the steps:

    license
    download
    flash
    setup

You can use --steps to run only some of those:

    dts init_sd_card --steps flash,setup

You can use --no-steps to exclude some steps:

    dts init_sd_card --no-steps download


"""

LIST_DEVICES_CMD = "lsblk -p --output NAME,TYPE,SIZE,VENDOR | grep --color=never 'disk\|TYPE'"


# NOTE: This is a chunk of a netplan configuration file, the padding is important
NETPLAN_OPEN_NETWORK_CONFIG = """
        "{ssid}": {{}}
"""

# NOTE: This is a chunk of a netplan configuration file, the padding is important
NETPLAN_WPA_PSK_NETWORK_CONFIG = """
        "{ssid}":
          password: "{psk}"
"""

# NOTE: This is a chunk of a netplan configuration file, the padding is important
NETPLAN_WPA_EAP_NETWORK_CONFIG = """
        "{ssid}":
          auth:
            key-management: eap
            identity: "{username}"
            password: "{password}"
            method: peap
            phase2-auth: MSCHAPV2
"""
