"""Daikin DTA117D611 Home Assistant integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ENABLE_DIAGNOSTIC_ENTITIES,
    CONF_USE_STABLE_IDS,
    DEFAULT_ENABLE_DIAGNOSTIC_ENTITIES,
    DEFAULT_USE_STABLE_IDS,
    DIAGNOSTIC_UNIQUE_ID_SUFFIXES,
    DOMAIN,
    PLATFORMS,
    UNIQUE_ID_SUFFIXES,
)
from .coordinator import DaikinD611Coordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Daikin DTA117D611 from a config entry."""

    coordinator = DaikinD611Coordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    if coordinator.gateway is not None:
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, coordinator.gateway.id)},
            manufacturer="Daikin",
            name=coordinator.gateway.name or "Daikin DTA117D611",
            model="DTA117D611 Gateway",
        )
    if entry.options.get(CONF_USE_STABLE_IDS, DEFAULT_USE_STABLE_IDS):
        await _async_migrate_stable_ids(hass, entry, coordinator)
    if entry.options.get(CONF_ENABLE_DIAGNOSTIC_ENTITIES, DEFAULT_ENABLE_DIAGNOSTIC_ENTITIES):
        _async_enable_diagnostic_entities(hass, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_migrate_stable_ids(
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

        legacy_device = device_registry.async_get_device({(DOMAIN, legacy_base)})
        stable_device = device_registry.async_get_device({(DOMAIN, stable_base)})
        if legacy_device and not stable_device:
            device_registry.async_update_device(
                legacy_device.id,
                merge_identifiers={(DOMAIN, stable_base)},
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


def _async_enable_diagnostic_entities(
    hass: HomeAssistant,
    coordinator: DaikinD611Coordinator,
) -> None:
    entity_registry = er.async_get(hass)
    for device in coordinator.data.values():
        for base_id in (device.unique_id, device.stable_physical_id):
            for platform, suffixes in DIAGNOSTIC_UNIQUE_ID_SUFFIXES.items():
                for suffix in suffixes:
                    entity_id = entity_registry.async_get_entity_id(platform, DOMAIN, f"{base_id}{suffix}")
                    if entity_id is not None:
                        entity_registry.async_update_entity(entity_id, disabled_by=None)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
