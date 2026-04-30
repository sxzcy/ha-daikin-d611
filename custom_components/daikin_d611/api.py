"""Compatibility exports for the Daikin DTA117D611 client modules."""

from __future__ import annotations

from .cloud import (
    CERT_INFO_URL,
    DEFAULT_BASE_URL,
    PUBLIC_KEY_PEM,
    DaikinCloudClient,
    build_client_ssl_context,
    calculate_cert_password,
    fetch_client_certificate,
    rsa_public_decrypt_pkcs1_v15_base64,
)
from .codec import (
    DaikinApiError,
    DaikinAuthError,
    DaikinError,
    DaikinSocketError,
    compact_json,
    decode_gateway_text,
    first_value,
    make_push_id,
    to_int,
    to_list,
)
from .socket import DaikinSocketClient

__all__ = [
    "CERT_INFO_URL",
    "DEFAULT_BASE_URL",
    "PUBLIC_KEY_PEM",
    "DaikinApiError",
    "DaikinAuthError",
    "DaikinCloudClient",
    "DaikinError",
    "DaikinSocketClient",
    "DaikinSocketError",
    "build_client_ssl_context",
    "calculate_cert_password",
    "compact_json",
    "decode_gateway_text",
    "fetch_client_certificate",
    "first_value",
    "make_push_id",
    "rsa_public_decrypt_pkcs1_v15_base64",
    "to_int",
    "to_list",
]
