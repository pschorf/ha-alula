"""Config flow for the Alula integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .const import CONF_PANEL_ID, DOMAIN

try:
    from pyalula import AlulaClient
    from pyalula.client import AlulaAuthError, AlulaApiError
except ImportError:
    pass

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_PANEL_ID, default=""): str,
    }
)


class AlulaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup UI for Alula."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            panel_id = user_input.get(CONF_PANEL_ID) or None

            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            client = AlulaClient()
            try:
                await client.login(username, password)
            except AlulaAuthError:
                errors["base"] = "invalid_auth"
            except AlulaApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Alula login")
                errors["base"] = "unknown"
            else:
                await client.close()
                data = {
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                }
                if panel_id:
                    data[CONF_PANEL_ID] = panel_id
                return self.async_create_entry(title=f"Alula ({username})", data=data)
            finally:
                if errors:
                    await client.close()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
