"""Kohler Konnect Home Assistant Integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import KohlerKonnectAPI, ReauthRequired
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.WATER_HEATER]


def _build_api(entry: ConfigEntry) -> KohlerKonnectAPI:
    """Construct an API client from a config entry's stored auth data."""
    if entry.data.get("auth_method") == "oauth" or "refresh_token" in entry.data:
        return KohlerKonnectAPI(refresh_token=entry.data["refresh_token"])
    return KohlerKonnectAPI(
        username=entry.data["username"],
        password=entry.data["password"],
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kohler Konnect from a config entry."""
    api = _build_api(entry)

    try:
        await hass.async_add_executor_job(api.authenticate)
    except ReauthRequired as err:
        raise ConfigEntryAuthFailed(str(err)) from err

    coordinator = KohlerKonnectCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


class KohlerKonnectCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch Kohler Konnect state periodically."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: KohlerKonnectAPI,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.api = api
        self._entry = entry

    async def _async_update_data(self):
        """Fetch data from API."""
        try:
            data = await self.hass.async_add_executor_job(self.api.get_all_state)
        except ReauthRequired as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Kohler API: {err}") from err

        new_rt = self.api.refresh_token
        if new_rt and new_rt != self._entry.data.get("refresh_token"):
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={**self._entry.data, "refresh_token": new_rt},
            )
        return data
