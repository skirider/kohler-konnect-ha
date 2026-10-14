"""Select entities for Kohler Konnect (preset/experience and outlet)."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.exceptions import HomeAssistantError

from kohler_anthem.models import Preset

from . import KohlerKonnectCoordinator, run_device_command
from .const import DOMAIN, HEADS
from .entity import KohlerEntity
from .helpers import (
    async_send_heads,
    async_start_preset_tracked,
    async_stop_shower_fully,
    extra,
    live_heads,
    preset_outlet_command_bits,
)

_LOGGER = logging.getLogger(__name__)

PRESET_NONE = "none"

OUTLET_OFF = "Off"
OUTLET_MULTIPLE = "Multiple heads"
HEAD_BY_LABEL = {label: key for key, label in HEADS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Kohler Konnect select entities."""
    coordinator: KohlerKonnectCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = []
    for device in coordinator.devices:
        entities += [
            KohlerPresetSelect(coordinator, device),
            KohlerOutletSelect(coordinator, device),
        ]
    async_add_entities(entities)


class KohlerPresetSelect(KohlerEntity, SelectEntity):
    """Start/stop the shower's presets and experiences.

    Options mirror the presets configured in the Kohler app. Selecting one
    starts it (controlpresetorexperience + valve activation); selecting
    "none" stops the running preset.
    """

    _attr_name = "Preset"
    _attr_icon = "mdi:playlist-play"

    @property
    def unique_id(self) -> str:
        return f"{self._device_id}_preset_select"

    def _label_for(self, preset: Preset) -> str:
        title = preset.title or preset.logical_name
        if title:
            return f"{title} ({preset.preset_id})"
        kind = "Experience" if preset.is_experience else "Preset"
        return f"{kind} {preset.preset_id}"

    def _labels_to_presets(self) -> dict[str, Preset]:
        response = self.coordinator.presets.get(self._device_id)
        if response is None:
            return {}
        return {self._label_for(p): p for p in response.presets}

    @property
    def options(self) -> list[str]:
        return [PRESET_NONE, *self._labels_to_presets()]

    @property
    def extra_state_attributes(self) -> dict:
        """expose each preset's per-valve data.

        Shows the stored hexString and its outlet-enable mask so heads can be
        mapped to outlet bits (bit0=outlet1, bit1=outlet2, bit2=outlet3).
        """
        out: dict = {}
        for label, preset in self._labels_to_presets().items():
            valves = {}
            for v in preset.valve_details:
                hx = (v.hex_string or "").strip()
                if not hx or hx == "000000":
                    continue
                valves[v.valve_index] = {
                    "hex": hx,
                    "outlet_mask": f"0x{hx[0:2].upper()}",
                    "outlets_on": [o.outlet_index for o in v.outlets if o.value],
                    "command_bits": f"0x{preset_outlet_command_bits(v):02X}",
                }
            out[label] = valves or "no valve data (experience)"
        return {"preset_valves": out}

    @property
    def current_option(self) -> str | None:
        state = self._state
        if state is None:
            return None
        active_id = state.state.active_preset_id
        if active_id is None:
            return PRESET_NONE
        for label, preset in self._labels_to_presets().items():
            if preset.id == active_id:
                return label
        # Active preset we don't have metadata for (e.g. cache still warming).
        return None

    async def async_select_option(self, option: str) -> None:
        if option == PRESET_NONE:
            # "none" now fully stops the shower (same escalating
            # stop as the water heater's Off), not just the preset selection.
            await run_device_command(
                async_stop_shower_fully(self.coordinator, self._device_id, 37.7),
                "stop shower",
            )
            await self.coordinator.async_request_refresh()
            return

        preset = self._labels_to_presets().get(option)
        if preset is None:
            _LOGGER.warning("Unknown Kohler preset option selected: %s", option)
            return
        # async_start_preset does the correct two-step (select + mode-0x01 valve
        # write) and raises a clear error for experiences, which can't be
        # started from HA. It requests a refresh itself.
        await async_start_preset_tracked(self.coordinator, self._device_id, preset)


class KohlerOutletSelect(KohlerEntity, SelectEntity):
    """run one physical head.

    Options are the installed heads (see HEADS) plus "Off". Picking a head
    starts water on that head only (closing anything else that is running);
    "Off" stops the shower. The current value is read back from the
    controller: "Multiple heads" is shown (not selectable) when a preset or
    the wall controller has more than one head open.
    """

    _attr_name = "Outlet"
    _attr_icon = "mdi:shower"
    _attr_options = [OUTLET_OFF, *HEADS.values(), OUTLET_MULTIPLE]

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device)
        self._optimistic: str | None = None

    @property
    def unique_id(self) -> str:
        return f"{self._device_id}_outlet_select"

    def _handle_coordinator_update(self) -> None:
        self._optimistic = None
        super()._handle_coordinator_update()

    @property
    def current_option(self) -> str:
        if self._optimistic is not None:
            return self._optimistic
        open_heads = [
            (valve_index, n)
            for valve_index, bits in live_heads(self._state).items()
            for n in (1, 2, 3)
            if bits & (1 << (n - 1))
        ]
        if not open_heads:
            return OUTLET_OFF
        if len(open_heads) == 1 and open_heads[0] in HEADS:
            return HEADS[open_heads[0]]
        return OUTLET_MULTIPLE

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "open_heads": [
                HEADS.get((valve_index, n), f"{valve_index} outlet{n}")
                for valve_index, bits in live_heads(self._state).items()
                for n in (1, 2, 3)
                if bits & (1 << (n - 1))
            ]
        }

    async def async_select_option(self, option: str) -> None:
        import asyncio

        coordinator = self.coordinator
        runtime = coordinator.runtime[self._device_id]
        target = extra(self._device_id)["target_celsius"]
        temp_c = (
            target
            if target is not None
            else coordinator.current_setpoint_celsius(self._device_id)
        )
        if option == OUTLET_MULTIPLE:
            raise HomeAssistantError(
                "'Multiple heads' is a status, not a choice. Pick a single "
                "head, or start a preset to run several heads."
            )
        if option == OUTLET_OFF:
            self._optimistic = OUTLET_OFF
            self.async_write_ha_state()
            try:
                await run_device_command(
                    async_stop_shower_fully(coordinator, self._device_id, temp_c),
                    "stop shower",
                )
            finally:
                await coordinator.async_request_refresh()
            return

        valve_index, outlet = HEAD_BY_LABEL[option]
        self._optimistic = option
        self.async_write_ha_state()
        try:
            await async_send_heads(
                coordinator,
                self._device_id,
                {valve_index: 1 << (outlet - 1)},
                temp_c,
                runtime.flow_percent,
                f"run {option}",
            )
        except Exception:
            self._optimistic = None
            self.async_write_ha_state()
            raise
        # The controller takes a few seconds to report the new head; hold the
        # optimistic value, then re-read.
        self._optimistic = option
        self.async_write_ha_state()
        await asyncio.sleep(5)
        await coordinator.async_request_refresh()
