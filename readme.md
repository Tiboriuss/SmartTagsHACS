# Samsung SmartTags for Home Assistant (TESTING!!!)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Track your Samsung Galaxy SmartTag / SmartTag2 devices in Home Assistant, just like your smartphone. Each tag appears as a `device_tracker` entity with GPS coordinates and battery level on the HA map.

## Features

- **Device Tracker entities** — each SmartTag shows as a tracker on the Home Assistant map
- **GPS coordinates** — latitude, longitude, and accuracy
- **Battery level** — reported as a device tracker attribute
- **E2E decryption** — supports end-to-end encrypted tag locations (optional PIN)
- **Automatic polling** — locations update every 5 minutes via the Samsung SmartThings API

## Requirements

- A Samsung account with Samsung Find (SmartThings Find) set up
- At least one Galaxy SmartTag or SmartTag2 registered to your account
- Home Assistant 2024.1.0 or newer
- [HACS](https://hacs.xyz/) installed

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Click the three dots menu (⋮) in the top right → **Custom repositories**
3. Add `https://github.com/Tiboriuss/SmartTagsHACS` as an **Integration**
4. Search for "Samsung SmartTags" in HACS and install it
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/samsung_smarttags` folder into your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Samsung SmartTags**
3. Enter your country code (e.g., `de`, `us`) and language (e.g., `en`)
4. Optionally enter your E2E PIN if your tags use end-to-end encryption
5. Click **Submit** — a Samsung login URL will be generated
6. Open the login URL in your browser and sign in with your Samsung account
7. After login, your browser will try to open a `ms-app://` URL — **copy the entire URL** from the address bar
8. Paste the redirect URL back into Home Assistant and click **Submit**
9. Your SmartTags will appear as device tracker entities on the map

## How It Works

This integration authenticates with the Samsung Account OAuth2 flow (the same method used by the Samsung SmartThings mobile app) and polls tag locations through the SmartThings Installed Apps Proxy API. It supports end-to-end encrypted locations using ECIES decryption when an E2E PIN is configured.

## E2E Encryption

If you have end-to-end encryption enabled for your SmartTags in Samsung Find, you need to provide the E2E PIN during setup. This is the PIN you set when enabling encryption in the Samsung Find app. Without it, encrypted tag locations will show as `0.0, 0.0`.

## Troubleshooting

- **"FME plugin not found"** — Make sure Samsung Find is set up and your tags are registered in the Samsung Find app
- **Tags not appearing** — Ensure your tags have reported at least one location in Samsung Find
- **Authentication expired** — The integration will attempt to refresh tokens automatically. If this fails, delete and re-add the integration

## Credits

Based on the reverse-engineering work of [KieronQuinn/uTag](https://github.com/KieronQuinn/uTag).

## License

MIT
