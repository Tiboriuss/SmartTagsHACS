"""Constants for the Samsung SmartTags integration."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "samsung_smarttags"

# Samsung Account client IDs (matching uTag constants)
CLIENT_ID_LOGIN = "yfrtglt53o"
CLIENT_ID_ONECONNECT = "6iado3s6jc"  # SmartThings
CLIENT_ID_FIND = "27zmg0v1oo"  # Samsung Find

# Samsung Account entry point
ENTRY_POINT_URL = "https://account.samsung.com/accounts/ANDROIDSDK/getEntryPoint"

# SmartThings API
SMARTTHINGS_API = "https://api.smartthings.com"
FME_PLUGIN_ID = "com.samsung.android.plugin.fme"

# Auth endpoints
PATH_AUTHENTICATE = "/auth/oauth2/authenticate"
PATH_AUTHORISE = "/auth/oauth2/v2/authorize"
PATH_TOKEN = "/auth/oauth2/token"

# Spoofed versions
SMARTTHINGS_AUTH_VERSION = "1.8.17.25"
SMARTTHINGS_CLIENT_VERSION = "1.8.21.28"

# Headers matching uTag OspInterceptor
OSP_HEADERS = {
    "X-Osp-Clientosversion": "34",
    "X-Osp-Clientmodel": "SM-S928B",
    "X-Osp-Appid": CLIENT_ID_LOGIN,
    "X-Osp-Packagename": "com.samsung.android.oneconnect",
    "X-Osp-Packageversion": SMARTTHINGS_AUTH_VERSION,
    "User-Agent": (
        f"Android/Oneapp/{SMARTTHINGS_AUTH_VERSION} "
        "(SM-S928B; Android 34/14) 4.11.0 QcApplication"
    ),
}

# Headers matching uTag SmartThingsAuthInterceptor
ST_HEADERS = {
    "User-Agent": (
        f"Android/OneApp/{SMARTTHINGS_CLIENT_VERSION}/Main "
        "(SM-S928B; Android 14/14) SmartKit/4.423.1"
    ),
    "X-St-Client-Appversion": SMARTTHINGS_CLIENT_VERSION,
    "X-St-Client-Devicemodel": "samsung SM-S928B beyond1",
    "X-St-Client-Os": "Android 14",
    "Accept": "application/vnd.smartthings+json;v=1",
    "Accept-Language": "en",
}

# Config entry data keys
CONF_COUNTRY_CODE = "country_code"
CONF_LANGUAGE = "language"
CONF_E2E_PIN = "e2e_pin"
CONF_TOKENS = "tokens"

# Default polling interval in minutes
DEFAULT_SCAN_INTERVAL = 15
