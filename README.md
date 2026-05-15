# Kohler Konnect for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/kenyonj/kohler-konnect-ha.svg)](https://github.com/kenyonj/kohler-konnect-ha/releases)

An unofficial Home Assistant integration for **Kohler Konnect** devices, with full support for the **Anthem shower (GCS)**.

> ⚠️ This is an unofficial integration, reverse-engineered from the Kohler Konnect Android app. It is not affiliated with or endorsed by Kohler Co. The API may change at any time.

---

## Features

| Feature | Status |
|---|---|
| 🚿 Shower warmup (pre-heat) | ✅ Working |
| ▶️ Start preset / experience | ✅ Working |
| ⏹️ Stop shower | ✅ Working |
| 🌡️ Target temperature (get/set) | ✅ Working |
| 📶 Connection state sensor | ✅ Working |
| 🔄 Warmup state sensor | ✅ Working |
| 🎛️ Active preset sensor | ✅ Working |
| 💧 Current outlet temperature | ✅ Working |

---

## Supported Devices

- **Kohler Anthem Shower (GCS)** — full read/write support
- Other Kohler Konnect devices (EVO, DTV+, SFC) — partial state read (PRs welcome)

---

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → ⋮ → **Custom repositories**
3. Add `https://github.com/kenyonj/kohler-konnect-ha` as an **Integration**
4. Install **Kohler Konnect**
5. Restart Home Assistant

### Manual

1. Copy `custom_components/kohler/` into your HA `custom_components/` directory
2. Restart Home Assistant

---

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Kohler Konnect**
3. Pick a sign-in method:
   - **OAuth (recommended).** The integration shows a Kohler B2C sign-in URL. Open it in a browser, sign in, then copy the `code=` value from the URL that the browser fails to open (the page tries to launch `msauth://...`) and paste it back into Home Assistant. The integration stores only a refresh token and rotates it automatically.
   - **Legacy password.** Enter your Kohler Konnect email and password. Kept as a fallback; Kohler's backend has started rejecting password-grant tokens on some endpoints, so OAuth is preferred for new installs.

> ⚠️ **OAuth caveat:** the redirect URI registered with Kohler's B2C client is the Android app's `msauth://com.kohler.hermoth/<sig-hash>` scheme. The `<sig-hash>` placeholder in `const.py` (`B2C_OAUTH_REDIRECT_URI`) must be set to the real URL-encoded SHA1 of the Kohler APK signing cert before OAuth will succeed end-to-end. Extract it via `apksigner -v --print-certs Kohler.apk`.

---

## Services

### `kohler.start_warmup`
Pre-heats the shower to your target temperature — no water flows until you get in.

### `kohler.start_preset`
Starts a saved preset by ID.

```yaml
service: kohler.start_preset
target:
  entity_id: water_heater.anthem_shower
data:
  preset_id: "1"
```

### `kohler.stop_shower`
Immediately stops all water flow.

---

## Automations

### Pre-heat shower 10 minutes before your alarm
```yaml
automation:
  trigger:
    - platform: time
      at: "06:50:00"
  action:
    - service: kohler.start_warmup
      target:
        entity_id: water_heater.anthem_shower
```

### Start shower when you wake up
```yaml
automation:
  trigger:
    - platform: state
      entity_id: input_boolean.morning_routine
      to: "on"
  action:
    - service: kohler.start_preset
      target:
        entity_id: water_heater.anthem_shower
      data:
        preset_id: "1"
```

---

## How It Works

This integration uses the undocumented Kohler Konnect REST API:

1. **Service token** — mTLS request to Kohler's Azure APIM to get a runtime API key
2. **User token** — Azure B2C `B2C_1A_signin` policy via OAuth Authorization Code + PKCE (or legacy ROPC for fallback) → JWT bearer token, with automatic refresh-token rotation
3. **API calls** — all device state and commands sent to `api-kohler-us.kohler.io` with both headers

State is polled every 30 seconds. Commands are sent immediately.

---

## Contributing

PRs welcome! Especially interested in:
- Support for EVO / DTV+ / SFC devices
- Azure IoT Hub real-time state updates (instead of polling)
- Bath fill support
- Multiple shower / valve support

---

## Support

If this integration saved you some time (or a cold shower), consider buying me a coffee ☕

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/kenyonj)

---

## License

MIT
