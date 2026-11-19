"""Daikin DTA117D611 Home Assistant integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    CONF_USE_STABLE_IDS,
    DEFAULT_USE_STABLE_IDS,
    DOMAIN,
    PLATFORMS,
    UNIQUE_ID_SUFFIXES,
)
from .coordinator import DaikinD611Coordinator

type DaikinD611ConfigEntry = ConfigEntry[DaikinD611Coordinator]


def _get_device_by_identifier(
    device_registry: dr.DeviceRegistry,
    identifier: tuple[str, str],
    config_entry_id: str,
) -> dr.DeviceEntry | None:
    if hasattr(device_registry, "async_get_device_by_identifier"):
        return device_registry.async_get_device_by_identifier(identifier, config_entry_id)
    return device_registry.async_get_device(identifiers={identifier})


async def async_setup_entry(hass: HomeAssistant, entry: DaikinD611ConfigEntry) -> bool:
    """Set up Daikin DTA117D611 from a config entry."""
    coordinator = DaikinD611Coordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await coordinator.async_shutdown()
        raise

    entry.runtime_data = coordinator

    if coordinator.gateway is not None:
        device_registry = dr.async_get(hass)
        gateway_device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, coordinator.gateway.id)},
            manufacturer="Daikin",
            name=coordinator.gateway.name or "Daikin D611 Gateway",
            model="DTA117D611 Gateway",
        )
        coordinator.gateway_device_id = gateway_device.id

    if entry.options.get(CONF_USE_STABLE_IDS, DEFAULT_USE_STABLE_IDS):
        _migrate_stable_ids(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _migrate_stable_ids(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: DaikinD611Coordinator,
) -> None:
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    for device in coordinator.data.values():
        legacy_base = device.unique_id
        stable_base = device.stable_physical_id
        if legacy_base == stable_base:
            continue

        legacy_device = _get_device_by_identifier(device_registry, (DOMAIN, legacy_base), entry.entry_id)
        stable_device = _get_device_by_identifier(device_registry, (DOMAIN, stable_base), entry.entry_id)
        if legacy_device and not stable_device:
            device_registry.async_update_device(
                legacy_device.id,
                new_identifiers=set(legacy_device.identifiers) | {(DOMAIN, stable_base)},
            )

        for platform, suffixes in UNIQUE_ID_SUFFIXES.items():
            for suffix in suffixes:
                old_unique_id = f"{legacy_base}{suffix}"
                new_unique_id = f"{stable_base}{suffix}"
                old_entity_id = entity_registry.async_get_entity_id(platform, DOMAIN, old_unique_id)
                if old_entity_id is None:
                    continue
                if entity_registry.async_get_entity_id(platform, DOMAIN, new_unique_id):
                    continue
                entity_registry.async_update_entity(old_entity_id, new_unique_id=new_unique_id)


async def async_unload_entry(hass: HomeAssistant, entry: DaikinD611ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
