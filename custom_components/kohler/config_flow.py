"""Config flow for Kohler Konnect."""
from __future__ import annotations

import logging
import secrets
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .api import (
    KohlerKonnectAPI,
    ReauthRequired,
    build_authorize_url,
    exchange_code_for_tokens,
    generate_pkce_pair,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

AUTH_METHODS = ["oauth", "ropc"]

STEP_USER_DATA_SCHEMA = vol.Schema(
    {vol.Required("method", default="oauth"): vol.In(AUTH_METHODS)}
)

STEP_ROPC_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)

STEP_OAUTH_DATA_SCHEMA = vol.Schema({vol.Required("code"): str})

STEP_REAUTH_ROPC_SCHEMA = vol.Schema({vol.Required("password"): str})


class KohlerKonnectConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kohler Konnect."""

    VERSION = 1

    def __init__(self) -> None:
        self._code_verifier: str | None = None
        self._oauth_state: str | None = None
        self._authorize_url: str | None = None
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pick an auth method."""
        if user_input is not None:
            if user_input["method"] == "oauth":
                return await self.async_step_oauth()
            return await self.async_step_ropc()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA
        )

    async def async_step_oauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the B2C authorize URL and capture the pasted code."""
        errors: dict[str, str] = {}

        if self._authorize_url is None:
            self._code_verifier, challenge = generate_pkce_pair()
            self._oauth_state = secrets.token_urlsafe(16)
            self._authorize_url = build_authorize_url(
                challenge, self._oauth_state
            )

        if user_input is not None:
            code = user_input["code"].strip()
            try:
                tokens = await self.hass.async_add_executor_job(
                    exchange_code_for_tokens, code, self._code_verifier
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Token exchange failed: %s", err)
                errors["base"] = "invalid_code"
            else:
                refresh_token = tokens.get("refresh_token")
                if not refresh_token:
                    errors["base"] = "no_refresh_token"
                else:
                    result = await self._finish_oauth(refresh_token)
                    if result is not None:
                        return result
                    errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="oauth",
            data_schema=STEP_OAUTH_DATA_SCHEMA,
            description_placeholders={"authorize_url": self._authorize_url},
            errors=errors,
        )

    async def _finish_oauth(self, refresh_token: str) -> FlowResult | None:
        """Validate an OAuth refresh token and create/update the entry."""
        api = KohlerKonnectAPI(refresh_token=refresh_token)
        try:
            await self.hass.async_add_executor_job(api.authenticate)
            devices = await self.hass.async_add_executor_job(api.get_devices)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("OAuth validation failed: %s", err)
            return None
        if not devices:
            return None

        data = {
            "auth_method": "oauth",
            "refresh_token": api.refresh_token or refresh_token,
        }

        if self._reauth_entry is not None:
            self.hass.config_entries.async_update_entry(
                self._reauth_entry,
                data={**self._reauth_entry.data, **data},
            )
            await self.hass.config_entries.async_reload(
                self._reauth_entry.entry_id
            )
            return self.async_abort(reason="reauth_successful")

        unique_id = api._tenant_id or "kohler-oauth"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Kohler Konnect", data=data
        )

    async def async_step_ropc(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Legacy ROPC username/password flow."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api = KohlerKonnectAPI(
                username=user_input["username"],
                password=user_input["password"],
            )
            try:
                await self.hass.async_add_executor_job(api.authenticate)
                devices = await self.hass.async_add_executor_job(api.get_devices)
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    await self.async_set_unique_id(user_input["username"])
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Kohler Konnect ({user_input['username']})",
                        data={**user_input, "auth_method": "ropc"},
                    )

        return self.async_show_form(
            step_id="ropc",
            data_schema=STEP_ROPC_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Start a reauth flow for an existing config entry."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Route reauth based on the original auth method."""
        assert self._reauth_entry is not None
        if self._reauth_entry.data.get("auth_method") == "ropc":
            return await self.async_step_reauth_ropc(user_input)
        return await self.async_step_oauth()

    async def async_step_reauth_ropc(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reauth for ROPC entries: re-prompt for password."""
        assert self._reauth_entry is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            api = KohlerKonnectAPI(
                username=self._reauth_entry.data["username"],
                password=user_input["password"],
            )
            try:
                await self.hass.async_add_executor_job(api.authenticate)
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={
                        **self._reauth_entry.data,
                        "password": user_input["password"],
                    },
                )
                await self.hass.config_entries.async_reload(
                    self._reauth_entry.entry_id
                )
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_ropc",
            data_schema=STEP_REAUTH_ROPC_SCHEMA,
            errors=errors,
        )
