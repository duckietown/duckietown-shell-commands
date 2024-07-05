If you add wifi networks manually, follow the example below relative to the network authentication you have:


 - Unprotected (Open) WiFi network:

   ...
      access-points:
        "<ssid>": {{}}



 - WPA/WPA2 WiFi network with PSK authentication:

   ...
      access-points:
        "<ssid>":
          key-management: psk
          password: "<wifi_password>"



 - WPA/WPA2 WiFi network with username/password authentication:

   ...
      access-points:
        "<ssid>":
          auth:
            key-management: eap
            identity: "<username>"
            password: "<password>"
            method: peap
            phase2-auth: MSCHAPV2
