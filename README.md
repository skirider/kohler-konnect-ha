# Kohler Konnect for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

> **Fork of [kenyonj/kohler-konnect-ha](https://github.com/kenyonj/kohler-konnect-ha)** (v0.5.5) with fixes for multi-valve / multi-head Anthem systems. See [Changes in this fork](#changes-in-this-fork).

An unofficial Home Assistant integration for **Kohler Konnect** devices, with full support for the **Anthem showers**.

---

## Features

| Feature | Status |
|---|---|
| 🚿 Shower warmup (pre-heat) | ✅ Working |
| ▶️ Start preset (select entity + service; experiences must be started in the Kohler app) | ✅ Working |
| ⏹️ Stop shower | ✅ Working |
| ⏸️ Pause shower (keeps session active) | ✅ Working |
| 🌡️ Target temperature (get/set, live while running) | ✅ Working |
| 💦 Flow percentage (set, live while running) | ✅ Working |
| 🚰 Run a single head, per zone (configurable names) | ✅ Working |
| 📶 Connection state sensor | ✅ Working |
| 🔄 Warmup state sensor | ✅ Working |
| 🎛️ Active preset sensor (by name) | ✅ Working |
| 💧 Current outlet temperature | ✅ Working |
| 🌊 Water running binary sensor | ✅ Working |
| ⚠️ Valve problem binary sensor (error codes) | ✅ Working |
| 📊 Total water used / system state sensors | ✅ Working |

---

## Supported Devices

- **Kohler Anthem Shower** — full read/write support
- Other Kohler Konnect devices (EVO, DTV+, SFC) — partial state read

---

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → ⋮ → **Custom repositories**
3. Add `https://github.com/skirider/kohler-konnect-ha` as an **Integration**
4. Install **Kohler Konnect**
5. Restart Home Assistant

### Manual

1. Copy `custom_components/kohler/` into your HA `custom_components/` directory
2. Restart Home Assistant

---

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Kohler Konnect**
3. Enter your Kohler Konnect email and password (same credentials as the official app)

---

## Entities

Each Anthem shower gets:

| Entity | Type | What it does |
|---|---|---|
| `water_heater.anthem_shower` | Water heater | Modes Off / Warmup / Running / Pause. **Running** starts the Default preset (preset 1), or resumes the same heads from Pause. Target temperature applies live without changing heads |
| `select.*_preset` | Select | Start a preset by name; `none` stops the shower. Attributes show each preset's per-valve heads |
| `select.*_outlet` | Select | `Off` or one physical head (e.g. `Zone 1 - Handshower`). Picking a head runs only that head; shows `Multiple heads` when a preset runs several. Head names are set in `const.py` (`HEADS`) |
| `number.*_flow` | Number | Water flow percentage; applies live (same heads) if water is running |
| `switch.*_shower_warmup` | Switch | Start/stop warmup |
| `binary_sensor.*_water_running` | Binary sensor | On while any valve is flowing |
| `binary_sensor.*_valve_problem` | Binary sensor | On when a valve reports an error (codes in attributes) |
| `sensor.*` | Sensors | Connection state, target temperature, warmup state, active preset, system state, total water used, last connected |

Flow and target temperature are held locally (the Kohler API has no "set
without running water" command) and are applied when a head is started — or
immediately, to the heads already running.

### Configuring head names

Edit `HEADS` in `custom_components/kohler/const.py`. Keys are
`(valveIndex, outlet number)`: `Valve1` is Zone 1, `Valve2` is Zone 2, and the
outlet number is the order the heads appear for that zone in the Kohler
Konnect app. Only the heads listed appear in the Outlet select.

---

## Services

### `kohler.start_warmup`
Pre-heats the shower to your target temperature — no water flows until you get in.

### `kohler.start_preset`
Starts a saved preset or experience by ID (1–5 are presets, 17+ are experiences).

```yaml
service: kohler.start_preset
target:
  entity_id: water_heater.anthem_shower
data:
  preset_id: 1
```

### `kohler.stop_shower`
Stops all water flow (and clears any running preset or warmup). Can take a few
seconds: it confirms the shower reports no open heads before finishing.

### `kohler.pause_shower`
Pauses the water while keeping the shower session active, so it can be resumed.

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

## Changes in this fork

Verified live on a 2-valve Anthem GCS (3 heads per valve).

**Presets opened the wrong heads.** Starting a preset sent outlet bitmask `0x01`
(outlet 1 only) for every valve. The preset's stored mask uses a different
layout (bit0 = valve flag, outlet N at bit N+1) from the command's (outlet N at
bit N-1), so it is now converted — preferring the preset's `outlets[]` list.
Example: stored `0x19` → command `0x06` (outlets 2 + 3).

**Off / Stop didn't stop the water.** The controller reports 8 valve slots
(`Valve1`..`Valve8`) even when 2 are installed. Off wrote to all 8; the cloud
accepts that write but the controller ignores it. Off now addresses only valves
in the session (open or paused), escalating OFF → STOP → OFF → preset clear and
re-reading state between steps. In testing, the first OFF succeeds. Preset
`none` uses the same stop. Presets started from HA never report as active, so
the preset clear no longer depends on `active_preset_id`.

**Pause only paused Valve 1.** Pause now sends STOP to every valve in the
session.

**Changing temperature/flow switched heads.** It re-sent "Valve 1, outlet 1".
It now re-sends the heads that are open (read from `out1..out3`) with the new
temperature/flow.

**Running opened Valve 1 outlet 1.** Running now starts the Default preset, or
resumes the previous heads from Pause.

**Outlet select was tub/shower-only.** Replaced with real heads per zone.

**Mode names** are translated (Off / Warmup / Running / Pause); state values
stay lowercase, so automations are unaffected.

**Preset select attributes** expose each preset's per-valve hex, mask and
enabled outlets (`preset_valves`) for debugging.

---

## How It Works

This integration uses the undocumented Kohler Konnect REST API:

1. **Service token** — mTLS request to Kohler's Azure APIM to get a runtime API key
2. **User token** — Azure B2C ROPC flow with your email/password → JWT bearer token
3. **API calls** — all device state and commands sent to `api-kohler-us.kohler.io` with both headers

State is polled every 10 seconds (presets every ~5 minutes). Commands are sent immediately.

---

## Contributing

PRs welcome! Especially interested in:
- Support for EVO / DTV+ / SFC devices
- Azure IoT Hub real-time state updates (instead of polling)
- Multiple shower / valve support

---

## Support

If this integration saved you some time (or a cold shower), consider buying me a coffee ☕

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/kenyonj)

---

## License

MIT
