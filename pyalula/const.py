"""Constants for the Alula API — filled in from Phase 1 traffic capture."""

# -------------------------------------------------------------------
# Base URLs
# -------------------------------------------------------------------
BASE_URL = "https://api.alula.net"
WS_URL = "wss://api.alulaprod.com/ws/v1"

# -------------------------------------------------------------------
# OAuth2 — static client credentials embedded in the app
# -------------------------------------------------------------------
OAUTH_CLIENT_ID = "4ce837c4-08e2-11e7-aa3b-605718912297"
OAUTH_CLIENT_SECRET = "Uzka3sgLNDTaH3cQ"

# -------------------------------------------------------------------
# REST endpoint paths
# -------------------------------------------------------------------
PATH_TOKEN = "/oauth/token"
PATH_DEVICES_PANELS = "/rest/v1/devices?customOptions[omitRelationships]=true&filter[isPanel]=true&sort=friendlyName"
PATH_HELIX_USERS = "/rest/v1/helix/users"  # ?filter[deviceId]=<id>

# -------------------------------------------------------------------
# Arming level byte codes (from ArmingLevel enum + Firebase config)
# level1=disarm, level2=stay, level3=night, level4=away
# -------------------------------------------------------------------
ARM_LEVEL_DISARM = 1
ARM_LEVEL_STAY = 2
ARM_LEVEL_NIGHT = 3
ARM_LEVEL_AWAY = 4

# String values returned by the REST API in the armingLevel field
ARM_STATE_STRINGS = {
    "disarm": ARM_LEVEL_DISARM,
    "stay": ARM_LEVEL_STAY,
    "night": ARM_LEVEL_NIGHT,
    "away": ARM_LEVEL_AWAY,
}

# -------------------------------------------------------------------
# WebSocket — device.helix channel
# -------------------------------------------------------------------
WS_CHANNEL = "device.helix"
WS_ACTION_SEND = "send"

# Zones per batch request (matches web app behaviour; firmware drops large ranges)
ZONE_BATCH_SIZE = 3

# -------------------------------------------------------------------
# Timeouts / retry
# -------------------------------------------------------------------
REQUEST_TIMEOUT = 15       # seconds, REST calls
WS_CONNECT_TIMEOUT = 10    # seconds, WebSocket handshake
WS_RESPONSE_TIMEOUT = 5    # seconds, wait for panel push after zone request
TOKEN_REFRESH_BUFFER = 300  # refresh token this many seconds before expiry
