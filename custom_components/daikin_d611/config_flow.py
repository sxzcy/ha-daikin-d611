"""Config and options flows for Daikin DTA117D611."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .cloud import DaikinCloudClient
from .codec import DaikinApiError, DaikinAuthError, DaikinError, first_value
from .const import (
    CONF_CONTROL_ACK_TIMEOUT,
    CONF_ENABLE_CLOUD_SNAPSHOT,
    CONF_ENABLE_DIAGNOSTIC_ENTITIES,
    CONF_GATEWAY,
    CONF_STATE_PRIORITY,
    CONF_TIMEOUT,
    CONF_USE_STABLE_IDS,
    DEFAULT_CONTROL_ACK_TIMEOUT,
    DEFAULT_ENABLE_CLOUD_SNAPSHOT,
    DEFAULT_ENABLE_DIAGNOSTIC_ENTITIES,
    DEFAULT_GATEWAY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STATE_PRIORITY,
    DEFAULT_TIMEOUT,
    DEFAULT_USE_STABLE_IDS,
    DOMAIN,
    STATE_PRIORITY_CLOUD_FIRST,
    STATE_PRIORITY_LOCAL_FIRST,
)
from .models import DaikinGateway
from .transport import DaikinLocalTransport

_LOGGER = logging.getLogger(__name__)
MIN_PORT = 1
MAX_PORT = 65535
PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    port_default = defaults.get(CONF_PORT, "")
    if port_default is None:
        port_default = ""
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
            vol.Required(CONF_GATEWAY, default=defaults.get(CONF_GATEWAY, DEFAULT_GATEWAY)): str,
            vol.Optional(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Optional(CONF_PORT, default=str(port_default)): str,
            vol.Required(CONF_SCAN_INTERVAL, default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): int,
            vol.Required(CONF_TIMEOUT, default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)): int,
        }
    )


def _reauth_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
        }
    )


def _options_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_SCAN_INTERVAL, default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): int,
            vol.Required(CONF_TIMEOUT, default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)): int,
            vol.Required(
                CONF_CONTROL_ACK_TIMEOUT,
                default=defaults.get(CONF_CONTROL_ACK_TIMEOUT, DEFAULT_CONTROL_ACK_TIMEOUT),
            ): int,
            vol.Required(
                CONF_ENABLE_CLOUD_SNAPSHOT,
                default=defaults.get(CONF_ENABLE_CLOUD_SNAPSHOT, DEFAULT_ENABLE_CLOUD_SNAPSHOT),
            ): bool,
            vol.Required(
                CONF_STATE_PRIORITY,
                default=defaults.get(CONF_STATE_PRIORITY, DEFAULT_STATE_PRIORITY),
            ): vol.In([STATE_PRIORITY_LOCAL_FIRST, STATE_PRIORITY_CLOUD_FIRST]),
            vol.Required(
                CONF_ENABLE_DIAGNOSTIC_ENTITIES,
                default=defaults.get(CONF_ENABLE_DIAGNOSTIC_ENTITIES, DEFAULT_ENABLE_DIAGNOSTIC_ENTITIES),
            ): bool,
            vol.Required(CONF_USE_STABLE_IDS, default=defaults.get(CONF_USE_STABLE_IDS, DEFAULT_USE_STABLE_IDS)): bool,
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Daikin DTA117D611 config flow."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsFlowHandler:
        return OptionsFlowHandler()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial configuration step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(user_input)
            if isinstance(data.get(CONF_HOST), str):
                data[CONF_HOST] = data[CONF_HOST].strip()
            if not data.get(CONF_HOST):
                data.pop(CONF_HOST, None)
            if data.get(CONF_PORT) in (None, ""):
                data.pop(CONF_PORT, None)
            else:
                try:
                    port = int(str(data[CONF_PORT]).strip())
                except (TypeError, ValueError):
                    errors[CONF_PORT] = "invalid_port"
                    return self.async_show_form(step_id="user", data_schema=_schema(user_input), errors=errors)
                if not MIN_PORT <= port <= MAX_PORT:
                    errors[CONF_PORT] = "invalid_port"
                    return self.async_show_form(step_id="user", data_schema=_schema(user_input), errors=errors)
                data[CONF_PORT] = port

            try:
                gateway = await self._async_validate_input(data)
            except DaikinAuthError:
                errors["base"] = "auth"
            except (DaikinError, TimeoutError, OSError) as exc:
                _LOGGER.debug("Daikin D611 validation failed", exc_info=True)
                errors["base"] = "gateway_not_found" if "Gateway not found" in str(exc) else "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected Daikin D611 validation error")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(gateway.id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=gateway.name or "Daikin D611 Bridge", data=data)

        return self.async_show_form(step_id="user", data_schema=_schema(user_input), errors=errors)

    def _get_current_reauth_entry(self) -> config_entries.ConfigEntry:
        if hasattr(self, "_get_reauth_entry"):
            return self._get_reauth_entry()
        entry_id = self.context.get("entry_id")
        entry = self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        if entry is None:
            raise RuntimeError("Config entry is not available for Daikin D611 reauthentication")
        return entry

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Handle reauthentication initiated by Home Assistant."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Confirm updated credentials for an existing config entry."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_current_reauth_entry()

        if user_input is not None:
            updated_data = {
                **reauth_entry.data,
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            try:
                await self._async_validate_input(updated_data)
            except DaikinAuthError:
                errors["base"] = "auth"
            except (DaikinError, TimeoutError, OSError) as exc:
                _LOGGER.debug("Daikin D611 reauth validation failed", exc_info=True)
                errors["base"] = "gateway_not_found" if "Gateway not found" in str(exc) else "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected Daikin D611 reauth error")
                errors["base"] = "unknown"
            else:
                if hasattr(self, "async_update_reload_and_abort"):
                    return self.async_update_reload_and_abort(
                        reauth_entry,
                        data_updates={
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )
                self.hass.config_entries.async_update_entry(reauth_entry, data=updated_data)
                await self.hass.config_entries.async_reload(reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        defaults = {
            CONF_USERNAME: (
                user_input.get(CONF_USERNAME, "")
                if user_input is not None
                else reauth_entry.data.get(CONF_USERNAME, "")
            ),
        }
        return self.async_show_form(step_id="reauth_confirm", data_schema=_reauth_schema(defaults), errors=errors)

    async def _async_validate_input(self, data: dict[str, Any]) -> DaikinGateway:
        timeout = float(data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT))
        cloud = DaikinCloudClient(
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            timeout=timeout,
            bootstrap_session=async_get_clientsession(self.hass),
        )
        try:
            gateway = await cloud.async_discover_gateway(
                str(data.get(CONF_GATEWAY, DEFAULT_GATEWAY)),
                host_override=data.get(CONF_HOST),
                port_override=data.get(CONF_PORT),
            )
            user_info = await cloud.async_get_user_info()
            nlc_id = first_value(
                user_info.get("nlcId"),
                (user_info.get("userInfo") or {}).get("nlcId"),
            )
            if not nlc_id:
                raise DaikinApiError("Could not get nlcId")
            transport = DaikinLocalTransport(gateway, nlc_id=str(nlc_id), timeout=timeout)
            await transport.async_query_devices()
            return gateway
        finally:
            await cloud.async_close()


class OptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle Daikin D611 options with automatic entry reload."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            options = dict(user_input)
            options[CONF_SCAN_INTERVAL] = max(10, int(options[CONF_SCAN_INTERVAL]))
            options[CONF_TIMEOUT] = max(3, int(options[CONF_TIMEOUT]))
            options[CONF_CONTROL_ACK_TIMEOUT] = max(0, int(options[CONF_CONTROL_ACK_TIMEOUT]))
            return self.async_create_entry(title="", data=options)

        defaults = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_options_schema(defaults))
