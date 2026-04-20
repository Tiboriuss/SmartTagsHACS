"""Config flow for Samsung SmartTags integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import (
    CONF_COUNTRY_CODE,
    CONF_E2E_PIN,
    CONF_LANGUAGE,
    CONF_SCAN_INTERVAL,
    CONF_TOKENS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .samsung_auth import (
    SamsungAuth,
    SamsungAuthConnectionError,
    SamsungAuthError,
    SamsungAuthInvalidCredentials,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_COUNTRY_CODE, default="de"): str,
        vol.Required(CONF_LANGUAGE, default="en"): str,
        vol.Optional(CONF_E2E_PIN, default=""): str,
    }
)


class SamsungSmartTagsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Samsung SmartTags."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._samsung_auth: SamsungAuth | None = None
        self._login_url: str | None = None
        self._country_code: str = "de"
        self._language: str = "en"
        self._e2e_pin: str = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow handler."""
        return SamsungSmartTagsOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step — collect settings and generate login URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._country_code = user_input[CONF_COUNTRY_CODE]
            self._language = user_input[CONF_LANGUAGE]
            self._e2e_pin = user_input.get(CONF_E2E_PIN, "")

            try:
                session = async_create_clientsession(self.hass)
                self._samsung_auth = SamsungAuth(
                    session=session,
                    country_code=self._country_code,
                    language=self._language,
                )
                self._login_url = await self._samsung_auth.start_login()
                return await self.async_step_auth()

            except SamsungAuthConnectionError:
                errors["base"] = "connection"
            except SamsungAuthError:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the auth step — user pastes redirect URL after Samsung login."""
        errors: dict[str, str] = {}

        if user_input is not None:
            redirect_url = user_input.get("redirect_url", "").strip()
            if not redirect_url:
                errors["base"] = "no_redirect_url"
            else:
                try:
                    token_data = await self._samsung_auth.complete_login(redirect_url)

                    user_id = token_data["user_id"]
                    email = token_data["email"]

                    await self.async_set_unique_id(user_id)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"Samsung SmartTags ({email})",
                        data={
                            CONF_COUNTRY_CODE: self._country_code,
                            CONF_LANGUAGE: self._language,
                            CONF_E2E_PIN: self._e2e_pin,
                            CONF_TOKENS: token_data,
                        },
                    )

                except SamsungAuthInvalidCredentials:
                    errors["base"] = "invalid_redirect"
                except SamsungAuthConnectionError:
                    errors["base"] = "connection"
                except SamsungAuthError:
                    errors["base"] = "auth"
                except Exception:
                    _LOGGER.exception("Unexpected error during Samsung login")
                    errors["base"] = "unknown"

        return self.async_show_form(
            step_id="auth",
            data_schema=vol.Schema(
                {vol.Required("redirect_url"): str}
            ),
            errors=errors,
            description_placeholders={"login_url": self._login_url or ""},
        )


class SamsungSmartTagsOptionsFlow(OptionsFlow):
    """Handle options for Samsung SmartTags."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=current_interval,
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                }
            ),
        )
