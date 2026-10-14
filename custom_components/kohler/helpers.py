"""Shared helpers for building Kohler Anthem valve commands.

The valve protocol notes live with :func:`build_off_control`; the constants
here are shared by the water_heater, select, and number platforms so they all
speak the same 4-byte-per-valve dialect.
"""

from __future__ import annotations

import asyncio
import logging

from kohler_anthem import encode_valve_command
from kohler_anthem.models import (
    DeviceState,
    Preset,
    ValveControlModel,
    ValveMode,
    ValvePrefix,
)

_LOGGER = logging.getLogger(__name__)

# Maps the API's valveIndex names to the solowritesystem payload field and the
# valve-prefix byte the firmware expects in each 4-byte command.
VALVE_FIELD_AND_PREFIX = {
    "Valve1": ("primary_valve1", ValvePrefix.PRIMARY),
    "Valve2": ("secondary_valve1", ValvePrefix.SECONDARY_1),
    "Valve3": ("secondary_valve2", ValvePrefix.SECONDARY_2),
    "Valve4": ("secondary_valve3", ValvePrefix.SECONDARY_3),
    "Valve5": ("secondary_valve4", ValvePrefix.SECONDARY_4),
    "Valve6": ("secondary_valve5", ValvePrefix.SECONDARY_5),
    "Valve7": ("secondary_valve6", ValvePrefix.SECONDARY_6),
    "Valve8": ("secondary_valve7", ValvePrefix.SECONDARY_7),
}

# encode_valve_command's accepted Celsius range.
ENCODE_TEMP_MIN_C, ENCODE_TEMP_MAX_C = 15.0, 49.0


def to_celsius(value: float, unit: str) -> float:
    """Convert an account-unit temperature to Celsius for library writes."""
    if unit == "Fahrenheit":
        return (value - 32.0) * 5.0 / 9.0
    return value


def from_celsius(value_c: float, unit: str) -> float:
    """Convert a Celsius API value to the account's display unit.

    Kohler's REST API reports temperatures in Celsius regardless of the
    account's display preference (the mobile app converts locally). Entities
    present temperatures in the account's unit, so read paths convert from
    Celsius with this helper; writes convert back with :func:`to_celsius`.
    """
    if unit == "Fahrenheit":
        return value_c * 9.0 / 5.0 + 32.0
    return value_c


def clamp_encode_temp(temp_c: float) -> float:
    """Clamp a Celsius value into encode_valve_command's accepted range."""
    return min(max(temp_c, ENCODE_TEMP_MIN_C), ENCODE_TEMP_MAX_C)


def build_off_control(state: DeviceState | None, temp_c: float) -> ValveControlModel:
    """Build a solowritesystem payload that actually turns the water off.

    The library's ``turn_off()`` sends an all-zero ``primaryValve1``
    (``"00000000"``). The firmware ignores that command because its prefix
    byte (0x00) doesn't address any valve — which is why users could turn
    the shower on but never off. The mobile app instead sends
    ``[prefix][temp][flow]`` with mode ``0x00`` per valve (e.g.
    ``"0179c800"``); reproduce that here for every valve the device reports.
    """
    temp_c = clamp_encode_temp(temp_c)
    kwargs: dict[str, str] = {}
    valves = state.state.valve_state if state is not None else []
    for valve in valves:
        mapping = VALVE_FIELD_AND_PREFIX.get(valve.valve_index)
        if mapping is None:
            continue
        field, prefix = mapping
        # Temp/flow bytes are ignored for OFF; they just need to be valid.
        flow = min(max(valve.flow_setpoint, 0), 100) or 100
        kwargs[field] = encode_valve_command(
            temperature_celsius=temp_c,
            flow_percent=flow,
            mode=ValveMode.OFF,
            prefix=prefix,
        )
    if "primary_valve1" not in kwargs:
        kwargs["primary_valve1"] = encode_valve_command(
            temperature_celsius=temp_c,
            flow_percent=100,
            mode=ValveMode.OFF,
            prefix=ValvePrefix.PRIMARY,
        )
    return ValveControlModel(**kwargs)


# The preset's stored hexString is 3 bytes: [outlet-enable mask][temp][flow].
# The solowritesystem command needs 4 bytes: [valve-prefix][temp][flow][mode].
# A preset "hexString" of "000000" (or None) means that valve is unused.
PRESET_HEX_UNUSED = {None, "", "000000"}


def preset_has_valve_data(preset: Preset) -> bool:
    """True if the preset carries at least one usable valve hexString.

    "Experiences" (Kohler's app-authored programs, e.g. Wake Up) come back with
    every ``hexString`` null/empty and cannot be started through the device
    API — only real presets carry the per-valve temp/flow bytes we need to open
    a valve. Verified live: sending ``controlpresetorexperience`` for an
    experience returns HTTP 201 but the device ignores it (no valve data, no
    water). Callers use this to fail loudly instead of silently no-opping.
    """
    return any(
        (v.hex_string or "").strip() not in PRESET_HEX_UNUSED
        for v in preset.valve_details
    )


def preset_outlet_command_bits(valve) -> int:
    """outlet bitmask (outlet N -> bit N-1) for a preset valve.

    Primary source is the preset's ``outlets`` list (``value`` = enabled).
    Fallback is the stored hexString's first byte, which encodes outlet N at
    bit N+1 (bit0 = valve flag), i.e. command bits = stored >> 2. Verified on
    a 2-valve GCS: 0x19 -> outlets 2,3; 0x05 -> outlet 1; 0x0D -> outlets 1,2;
    0x01 -> none.
    """
    bits = 0
    for outlet in getattr(valve, "outlets", None) or []:
        idx = str(outlet.outlet_index).lower().replace("outlet", "")
        if outlet.value and idx.isdigit() and 1 <= int(idx) <= 8:
            bits |= 1 << (int(idx) - 1)
    if bits:
        return bits
    hex_string = (valve.hex_string or "").strip()
    if len(hex_string) >= 2:
        return (int(hex_string[0:2], 16) >> 2) & 0xFF
    return 0


def build_preset_valve_control(preset: Preset) -> ValveControlModel:
    """Build a solowritesystem payload that STARTS a preset's valves.

    Each preset valve stores a 3-byte ``[outletMask][temp][flow]`` hexString.
    We re-emit it as the firmware's 4-byte ``[prefix][temp][flow][mode]`` form
    with mode ``0x01`` (SHOWER / on).

    This is the crux of the preset-start fix. The upstream ``kohler-anthem``
    library builds this same command with mode ``0x40`` — which its own enum
    names ``STOP`` — so activating a preset sent the valves a *stop* command and
    nothing happened. Verified live on the hardware: the identical bytes with
    mode ``0x01`` open the valve and run water; mode ``0x40`` does not.
    """
    kwargs: dict[str, str] = {}
    for valve in preset.valve_details:
        mapping = VALVE_FIELD_AND_PREFIX.get(valve.valve_index)
        hex_string = (valve.hex_string or "").strip()
        if mapping is None or hex_string in PRESET_HEX_UNUSED or len(hex_string) < 6:
            continue
        field, prefix = mapping
        # Carry the preset's own temp+flow bytes through unchanged; only the
        # prefix byte is ours to set.
        temp_flow = hex_string[2:6]
        # open the outlets the preset enables.
        # Upstream hard-coded the 4th byte to 0x01 (outlet 1 only). The
        # command's 4th byte is an outlet bitmask, outlet N -> bit N-1
        # (library: 0x02 = tub filler/outlet2, 0x03 = outlets 1+2).
        bits = preset_outlet_command_bits(valve)
        if bits == 0:
            continue
        kwargs[field] = f"{int(prefix):02X}{temp_flow}{bits:02X}"
    return ValveControlModel(**kwargs)


# ---------------------------------------------------------------------------
# Reliable "turn the shower off".
#
# Findings on a 2-valve GCS (the controller reports 8 valve slots, Valve1-8,
# even though only 2 are installed):
#   * The original off wrote [prefix][temp][flow][0x00] to EVERY reported valve
#     slot. The cloud accepts it but the controller ignores the whole write.
#   * A write of STOP 0x40 / OFF 0x00 to all 8 slots is ignored the same way.
#   * The library's pause (0x40 on primaryValve1 only, other slots
#     "00000000") DOES stop the water.
# => only address valves that are actually in the session (open or paused).
#
# Sequence, re-reading state between steps and stopping as soon as the
# controller reports no open outlets and no pause:
#   1. OFF  0x00 on session valves
#   2. STOP 0x40 on session valves      (known to stop flow)
#   3. OFF  0x00 on session valves      (end the paused session)
#   4. controlpresetorexperience "0"    (clear preset / warmup)
# Each step is logged at DEBUG (enable debug logging for custom_components.kohler).
# ---------------------------------------------------------------------------

STOP_STEP_SETTLE_S = 4


def _session_valves(state: DeviceState | None) -> list:
    """Valves that are part of the current session (open, flowing or paused)."""
    if state is None:
        return []
    return [
        v
        for v in state.state.valve_state
        if (v.is_active or v.at_flow or v.pause_flag)
        and v.valve_index in VALVE_FIELD_AND_PREFIX
    ]


def build_mode_control(valves: list, temp_c: float, mode: ValveMode) -> ValveControlModel:
    """[prefix][temp][flow][mode] for the given valves only; primary if none."""
    temp_c = clamp_encode_temp(temp_c)
    kwargs: dict[str, str] = {}
    for valve in valves:
        field, prefix = VALVE_FIELD_AND_PREFIX[valve.valve_index]
        flow = min(max(valve.flow_setpoint, 0), 100) or 100
        kwargs[field] = encode_valve_command(
            temperature_celsius=temp_c, flow_percent=flow, mode=mode, prefix=prefix
        )
    if not kwargs:
        kwargs["primary_valve1"] = encode_valve_command(
            temperature_celsius=temp_c, flow_percent=100, mode=mode,
            prefix=ValvePrefix.PRIMARY,
        )
    return ValveControlModel(**kwargs)


def _session_summary(state: DeviceState | None) -> tuple[bool, bool, str]:
    """(open, paused, short description) for a device state."""
    if state is None:
        return False, False, "no state"
    flowing = paused = False
    parts = []
    for v in state.state.valve_state:
        f = bool(v.is_active or v.at_flow)
        flowing |= f
        paused |= bool(v.pause_flag)
        if f or v.pause_flag:
            parts.append(
                f"{v.valve_index}:out={int(v.out1)}{int(v.out2)}{int(v.out3)}"
                f" flow={int(v.at_flow)} pause={int(v.pause_flag)}"
            )
    parts.append(f"valves={len(state.state.valve_state)}")
    parts.append(f"warmup={state.is_warming_up}")
    parts.append(f"preset={state.state.active_preset_id}")
    return flowing, paused, " ".join(parts)


async def async_stop_shower_fully(coordinator, device_id: str, temp_c: float) -> None:
    """Escalating stop addressed only to session valves (see above)."""
    client = coordinator.client
    tenant_id = coordinator.tenant_id

    async def _read() -> DeviceState | None:
        try:
            return await client.get_device_state(device_id)
        except Exception as err:  # noqa: BLE001 - best-effort read
            _LOGGER.debug("Kohler stop: state read failed: %s", err)
            return None

    def _valve_step(mode: ValveMode):
        def _send(s):
            vc = build_mode_control(_session_valves(s), temp_c, mode)
            sent = {k: v for k, v in vc.model_dump().items() if v and v != "00000000"}
            _LOGGER.debug("Kohler stop: sending %s", sent)
            return client.control_valve(tenant_id, device_id, vc)
        return _send

    state = await _read()
    _, _, desc = _session_summary(state)
    _LOGGER.debug("Kohler stop: start  [%s]", desc)

    steps = (
        ("1 valve OFF 0x00", _valve_step(ValveMode.OFF)),
        ("2 valve STOP 0x40", _valve_step(ValveMode.STOP)),
        ("3 valve OFF 0x00", _valve_step(ValveMode.OFF)),
        ("4 preset/warmup clear", lambda s: client.stop_preset(tenant_id, device_id)),
    )
    for name, make in steps:
        await make(state)
        await asyncio.sleep(STOP_STEP_SETTLE_S)
        state = await _read()
        flowing, paused, desc = _session_summary(state)
        _LOGGER.debug("Kohler stop: after step %s [%s]", name, desc)
        if state is not None and not flowing and not paused and not state.is_warming_up:
            _LOGGER.debug("Kohler stop: shower OFF after step %s", name)
            return
    _LOGGER.warning("Kohler stop: shower still not fully off after all steps")


# ---------------------------------------------------------------------------
# Head-level control.
#
# A "heads" dict maps valveIndex -> outlet bitmask (outlet N -> bit N-1), the
# same bits the command's 4th byte and the state's out1/out2/out3 flags use.
# ---------------------------------------------------------------------------


def live_heads(state: DeviceState | None) -> dict[str, int]:
    """Heads currently open, read from the controller's out1..out3 flags."""
    heads: dict[str, int] = {}
    if state is None:
        return heads
    for v in state.state.valve_state:
        bits = (1 if v.out1 else 0) | (2 if v.out2 else 0) | (4 if v.out3 else 0)
        if bits and v.valve_index in VALVE_FIELD_AND_PREFIX:
            heads[v.valve_index] = bits
    return heads


def preset_heads(preset: Preset) -> dict[str, int]:
    """Heads a preset opens, per valve."""
    heads: dict[str, int] = {}
    for v in preset.valve_details:
        hx = (v.hex_string or "").strip()
        if v.valve_index not in VALVE_FIELD_AND_PREFIX or hx in PRESET_HEX_UNUSED:
            continue
        bits = preset_outlet_command_bits(v)
        if bits:
            heads[v.valve_index] = bits
    return heads


def build_heads_control(
    state: DeviceState | None,
    heads: dict[str, int],
    temp_c: float,
    flow_percent: int,
) -> ValveControlModel:
    """Open exactly ``heads``; close any other valve that is in the session.

    Only valves being opened or currently in the session are addressed —
    writing to valve slots that aren't in use makes the controller ignore the
    whole command (see the stop notes above).
    """
    temp_c = clamp_encode_temp(temp_c)
    flow_percent = min(max(int(flow_percent), 10), 100)
    kwargs: dict[str, str] = {}
    for valve_index, bits in heads.items():
        if not bits or valve_index not in VALVE_FIELD_AND_PREFIX:
            continue
        field, prefix = VALVE_FIELD_AND_PREFIX[valve_index]
        base = encode_valve_command(
            temperature_celsius=temp_c,
            flow_percent=flow_percent,
            mode=ValveMode.OFF,
            prefix=prefix,
        )
        kwargs[field] = f"{base[:6]}{bits & 0x3F:02X}"
    for valve in _session_valves(state):
        field, prefix = VALVE_FIELD_AND_PREFIX[valve.valve_index]
        if field in kwargs:
            continue
        kwargs[field] = encode_valve_command(
            temperature_celsius=temp_c,
            flow_percent=flow_percent,
            mode=ValveMode.OFF,
            prefix=prefix,
        )
    return ValveControlModel(**kwargs)


# ---------------------------------------------------------------------------
# Coordinator-level actions, kept here so that
# __init__.py stays identical to upstream v0.5.5.
# ---------------------------------------------------------------------------

# Per-device session extras: {"target_celsius": float | None, "last_heads": {}}
_EXTRA: dict[str, dict] = {}


def extra(device_id: str) -> dict:
    """HA-side target temperature (Celsius) and the most recent session's heads."""
    return _EXTRA.setdefault(device_id, {"target_celsius": None, "last_heads": {}})


async def async_send_heads(
    coordinator,
    device_id: str,
    heads: dict[str, int],
    temp_c: float,
    flow_percent: int,
    action: str,
) -> None:
    """Run exactly these heads (valveIndex -> outlet bits).

    Other valves in the current session are closed in the same write, so this
    can switch heads/zones while water is running.
    """
    from . import run_device_command

    state = (coordinator.data or {}).get(device_id)
    await run_device_command(
        coordinator.client.control_valve(
            coordinator.tenant_id,
            device_id,
            build_heads_control(state, heads, temp_c, flow_percent),
        ),
        action,
    )
    extra(device_id)["last_heads"] = dict(heads)
    await coordinator.async_request_refresh()


async def async_apply_runtime(coordinator, device_id: str, action: str) -> None:
    """Re-send the running heads with the current temperature/flow.

    Replaces coordinator.async_apply_runtime, which re-sent ``turn_on_outlet``
    (Valve1 / outlet 1 only) and so switched heads mid-shower. No-op when the
    water is off.
    """
    if not coordinator.device_is_running(device_id):
        return
    heads = live_heads((coordinator.data or {}).get(device_id))
    if not heads:
        return
    target = extra(device_id)["target_celsius"]
    temp_c = target if target is not None else coordinator.current_setpoint_celsius(device_id)
    await async_send_heads(
        coordinator,
        device_id,
        heads,
        temp_c,
        coordinator.runtime[device_id].flow_percent,
        action,
    )


async def async_start_preset_tracked(coordinator, device_id: str, preset: Preset) -> None:
    """Start a preset, remember its heads (for resume) and drop any HA-side
    temperature override so the preset's own temperature is shown/used."""
    await coordinator.async_start_preset(device_id, preset)
    ex = extra(device_id)
    ex["last_heads"] = preset_heads(preset)
    ex["target_celsius"] = None
