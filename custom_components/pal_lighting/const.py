"""Constants for the PAL Lighting integration."""

DOMAIN = "pal_lighting"

CONF_HOST = "host"
CONF_ACCESS_KEY = "access_key"
CONF_PASSWORD = "password"  # decimal 0-255, applied to both frame pwd bytes
CONF_POLL_INTERVAL = "poll_interval"  # seconds; 0 disables the reachability probe

DEFAULT_POLL_INTERVAL = 20

DEFAULT_NAME = "PAL Lighting"
DEFAULT_ACCESS_KEY = 123456789  # factory accessKey
DEFAULT_PASSWORD = 117  # 0x75 — this device's password bytes (75 75)

# 4-switch remote layout, as the app's "4 button remote" screen.
SWITCH_COUNT = 4

# 0xA1 control frame layout (verified against the live device):
#   [0xA1][pwd0][pwd1][zone=0x04][cmd=0x03][data][0x00 *5][checksum]
# data for switch N (1-based): per the app's all_on_off (Timer2Activity,
# zone-4 8-channel remote) ON = 2*(N-1), OFF = 2*(N-1)+1. NOTE: the live
# device TOGGLES the relay on every command regardless of the data value
# (verified 2026-09-13 A-B-A: repeated OFF flips the load back on), so these
# values are cosmetic — switch.py must skip redundant commands to stay safe.
ZONE_BYTE = 0x04
CMD_SCENE = 0x03
DATA_ON = [0x00, 0x02, 0x04, 0x06]
DATA_OFF = [0x01, 0x03, 0x05, 0x07]

# XLink UDP
DEVICE_UDP_PORT = 5987
HANDSHAKE_TIMEOUT_FIELD = 100  # app-observed value in the handshake body