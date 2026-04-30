"""Config flow for Daikin DTA117D611."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.data_entry_flow import FlowResult

from .api import DaikinApiError, DaikinAuthError, DaikinCloudClient, DaikinSocketClient
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

_LOGGER = logging.getLogger(__name__)


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    port_default = defaults.get(CONF_PORT, "")
    if port_default is None:
        port_default = ""
    schema: dict[Any, Any] = {
        vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
        vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
        vol.Required(CONF_GATEWAY, default=defaults.get(CONF_GATEWAY, DEFAULT_GATEWAY)): str,
        vol.Optional(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
        vol.Optional(CONF_PORT, default=str(port_default)): str,
        vol.Required(CONF_SCAN_INTERVAL, default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): int,
        vol.Required(CONF_TIMEOUT, default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)): int,
    }
    return vol.Schema(schema)


def _options_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): int,
            vol.Required(
                CONF_TIMEOUT,
                default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            ): int,
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
            vol.Required(
                CONF_USE_STABLE_IDS,
                default=defaults.get(CONF_USE_STABLE_IDS, DEFAULT_USE_STABLE_IDS),
            ): bool,
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Daikin DTA117D611 config flow."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""

        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(user_input)
            if not data.get(CONF_HOST):
                data.pop(CONF_HOST, None)
            if data.get(CONF_PORT) in (None, ""):
                data.pop(CONF_PORT, None)
            else:
                try:
                    data[CONF_PORT] = int(data[CONF_PORT])
                except (TypeError, ValueError):
                    errors[CONF_PORT] = "invalid_port"
                    return self.async_show_form(step_id="user", data_schema=_schema(user_input), errors=errors)

            try:
                gateway = await self.hass.async_add_executor_job(self._validate_input, data)
            except DaikinAuthError:
                errors["base"] = "auth"
            except DaikinApiError as exc:
                _LOGGER.debug("Daikin D611 validation failed", exc_info=True)
                errors["base"] = "gateway_not_found" if "Gateway not found" in str(exc) else "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected Daikin D611 validation error")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(gateway.id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=gateway.name or "Daikin DTA117D611", data=data)

        return self.async_show_form(step_id="user", data_schema=_schema(user_input), errors=errors)

    @staticmethod
    def _validate_input(data: dict[str, Any]):
        cloud = DaikinCloudClient(
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            timeout=float(data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
        )
        gateway = cloud.discover_gateway(
            str(data.get(CONF_GATEWAY, DEFAULT_GATEWAY)),
            host_override=data.get(CONF_HOST),
            port_override=data.get(CONF_PORT),
        )
        user_info = cloud.get_user_info()
        nlc_id = user_info.get("nlcId") or (user_info.get("userInfo") or {}).get("nlcId")
        if not nlc_id:
            raise DaikinApiError("Could not get nlcId")
        socket_client = DaikinSocketClient(gateway, nlc_id=str(nlc_id or ""), timeout=float(data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)))
        socket_client.query_devices()
        return gateway


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Daikin D611 options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            options = dict(user_input)
            options[CONF_SCAN_INTERVAL] = max(10, int(options[CONF_SCAN_INTERVAL]))
            options[CONF_TIMEOUT] = max(3, int(options[CONF_TIMEOUT]))
            options[CONF_CONTROL_ACK_TIMEOUT] = max(0, int(options[CONF_CONTROL_ACK_TIMEOUT]))
            return self.async_create_entry(title="", data=options)

        defaults = {
            **self.config_entry.data,
            **self.config_entry.options,
        }
        return self.async_show_form(step_id="init", data_schema=_options_schema(defaults))
