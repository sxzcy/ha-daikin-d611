"""Daikin New Life Multi cloud client."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import ssl
import tempfile
from typing import Any
from urllib import error, parse, request

from .codec import (
    DaikinApiError,
    DaikinAuthError,
    DaikinError,
    compact_json,
    first_value,
    make_push_id,
    to_int,
    to_list,
)
from .models import DaikinGateway

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://newlifemulti.daikin-china.com.cn:4443/v2/"
CERT_INFO_URL = "https://newlifemulti.daikin-china.com.cn:443/v2/home/getCertificateInfo"
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAm6hQn1LlnQ0DzG0ZiKUP
hNHUUJeFCgw5m/sUPkbOpgwui5Br6OQkrW/+yKeHn6gRLWNqW0+ULha/9lhWWUJm
1O9aYCYPnYrZh6IplBZL72Ad8mHxcXALc9y0wxr9QoF5X2kidZLxiOuoiPq5Pjwx
T/uH/8uYWbAVwlD+e1fjB7hJt8zubxFEbuhvLjMZ8bshCSn55yNVwwOasOORZwjD
UyLdGyl8TA149d7HCUXV0iUqnmfOkniio9nrBc2T1xb4aePP45wJEUFV6I1A3haG
hXBlHNjfR1/vdMViac3DRa+Q2PCDdjcJVE2EzvWapkOxewIYpWlHvqyKkUbhICO/
LQIDAQAB
-----END PUBLIC KEY-----"""


def calculate_cert_password(push_id: str) -> str:
    checksum = 0
    for byte in push_id.encode("utf-8"):
        checksum ^= byte
        for _ in range(8):
            if checksum & 1:
                checksum ^= 67601
            checksum = int(checksum) // 2
    return f"{checksum & 0xffff:04X}"


def rsa_public_decrypt_pkcs1_v15_base64(value: str) -> str:
    from cryptography.hazmat.primitives import serialization

    public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode("ascii"))
    numbers = public_key.public_numbers()
    encrypted = base64.b64decode(value)
    key_size = (numbers.n.bit_length() + 7) // 8
    block = pow(int.from_bytes(encrypted, "big"), numbers.e, numbers.n).to_bytes(key_size, "big")
    if len(block) < 11 or block[0] != 0x00 or block[1] not in (0x01, 0x02):
        raise DaikinApiError("Invalid certificate password RSA block")
    try:
        separator = block.index(b"\x00", 2)
    except ValueError as exc:
        raise DaikinApiError("Invalid certificate password RSA separator") from exc
    return block[separator + 1 :].decode("utf-8")


def fetch_client_certificate(push_id: str, timeout: float) -> tuple[bytes, str]:
    body = {
        "clientId": push_id,
        "password": calculate_cert_password(push_id),
        "fileType": "p12",
        "clientType": "APP",
    }
    req = request.Request(
        CERT_INFO_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "DaikinINLS/4.9.0 HomeAssistant",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
    except (error.URLError, json.JSONDecodeError) as exc:
        raise DaikinApiError(f"Failed to get client certificate info: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("code") not in (0, "0", None):
        raise DaikinApiError(f"Certificate info failed: {compact_json(payload)}")

    download_info = ((payload.get("data") or {}).get("downloadInfo") or {})
    resources_path = download_info.get("resourcesPath")
    encrypted_password = download_info.get("certPassword")
    expected_md5 = download_info.get("md5")
    if not resources_path or not encrypted_password:
        raise DaikinApiError(f"Incomplete certificate info: {compact_json(download_info)}")

    try:
        with request.urlopen(str(resources_path), timeout=timeout) as resp:
            p12_bytes = resp.read()
    except error.URLError as exc:
        raise DaikinApiError(f"Failed to download client certificate: {exc}") from exc

    if expected_md5:
        actual_md5 = hashlib.md5(p12_bytes).hexdigest()
        if actual_md5.lower() != str(expected_md5).lower():
            raise DaikinApiError("Client certificate MD5 mismatch")

    return p12_bytes, rsa_public_decrypt_pkcs1_v15_base64(str(encrypted_password))


def build_client_ssl_context(push_id: str, timeout: float) -> ssl.SSLContext:
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        pkcs12,
    )

    p12_bytes, password = fetch_client_certificate(push_id, timeout)
    private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
        p12_bytes,
        password.encode("utf-8"),
    )
    if private_key is None or certificate is None:
        raise DaikinApiError("Client certificate has no key or certificate")

    key_fd, key_path = tempfile.mkstemp(prefix="ha-daikin-d611-key-", suffix=".pem")
    cert_fd, cert_path = tempfile.mkstemp(prefix="ha-daikin-d611-cert-", suffix=".pem")
    try:
        with os.fdopen(key_fd, "wb") as key_file:
            key_file.write(
                private_key.private_bytes(
                    Encoding.PEM,
                    PrivateFormat.TraditionalOpenSSL,
                    NoEncryption(),
                )
            )
        with os.fdopen(cert_fd, "wb") as cert_file:
            cert_file.write(certificate.public_bytes(Encoding.PEM))
            for item in additional_certificates or []:
                cert_file.write(item.public_bytes(Encoding.PEM))

        context = ssl.create_default_context()
        try:
            context.set_ciphers("DEFAULT@SECLEVEL=0")
        except ssl.SSLError:
            pass
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        return context
    finally:
        for path in (key_path, cert_path):
            try:
                os.unlink(path)
            except OSError:
                pass


class DaikinCloudClient:
    """Minimal Daikin New Life Multi cloud client."""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        timeout: float,
        base_url: str = DEFAULT_BASE_URL,
        push_id: str | None = None,
    ) -> None:
        self.username = username
        self.password = password
        self.timeout = timeout
        self.base_url = base_url.rstrip("/") + "/"
        self.push_id = push_id or make_push_id()
        self.token: str | None = None
        self.ssl_context: ssl.SSLContext | None = None

    def _url(self, endpoint: str) -> str:
        return parse.urljoin(self.base_url, endpoint.lstrip("/"))

    def _ensure_cert(self) -> None:
        if self.ssl_context is None:
            self.ssl_context = build_client_ssl_context(self.push_id, self.timeout)

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "DaikinINLS/4.9.0 HomeAssistant",
        }
        if content_type:
            headers["Content-Type"] = content_type
        if self.token:
            headers["token"] = self.token
        return headers

    def _request(
        self,
        endpoint: str,
        *,
        form: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        if form is not None and body is not None:
            raise ValueError("form and body cannot be used together")
        self._ensure_cert()
        if form is not None:
            form_data = dict(form)
            form_data.setdefault("version", "1")
            data = parse.urlencode(form_data).encode("utf-8")
            headers = self._headers("application/x-www-form-urlencoded")
        elif body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers = self._headers("application/json; charset=utf-8")
        else:
            data = b""
            headers = self._headers()

        req = request.Request(self._url(endpoint), data=data, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout, context=self.ssl_context) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise DaikinApiError(f"HTTP {exc.code}: {raw[:500]}") from exc
        except error.URLError as exc:
            raise DaikinApiError(f"Request failed: {exc}") from exc

        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise DaikinApiError(f"Invalid JSON response: {raw[:500]}") from exc

        if isinstance(payload, dict) and "code" in payload:
            code = payload.get("code")
            if code not in (0, "0", None):
                message = first_value(payload.get("description"), payload.get("message"), payload.get("msg"), code)
                if "密码" in str(message) or "手机号" in str(message) or "登录" in str(message):
                    raise DaikinAuthError(str(message))
                raise DaikinApiError(str(message))
            return payload.get("data")
        return payload

    def login(self) -> None:
        data = self._request(
            "app/nlcLoginV2",
            form={"authId": self.username, "password": self.password, "pushId": self.push_id},
        )
        if not isinstance(data, dict):
            raise DaikinApiError(f"Unexpected login response: {compact_json(data)}")
        token = first_value(data.get("accessToken"), data.get("token"), data.get("access_token"))
        if not token:
            raise DaikinApiError(f"Login response has no token: {compact_json(data)}")
        self.token = str(token)

    def ensure_login(self) -> None:
        if not self.token:
            self.login()

    def _request_authenticated(
        self,
        endpoint: str,
        *,
        form: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        self.ensure_login()
        try:
            return self._request(endpoint, form=form, body=body)
        except DaikinApiError:
            if not self.token:
                raise
            _LOGGER.debug("Authenticated Daikin request failed; refreshing login and retrying", exc_info=True)
            self.token = None
            self.login()
            return self._request(endpoint, form=form, body=body)

    def list_homes(self) -> list[dict[str, Any]]:
        return [item for item in to_list(self._request_authenticated("home/listHomeByLoginUser")) if isinstance(item, dict)]

    def get_home(self, home_id: str) -> dict[str, Any]:
        data = self._request_authenticated("home/getHome", body={"homeId": home_id})
        return data if isinstance(data, dict) else {}

    def list_gateways(self, home_id: str) -> list[dict[str, Any]]:
        return [item for item in to_list(self._request_authenticated("home/listGatewayAuth", body={"homeId": home_id})) if isinstance(item, dict)]

    def get_user_info(self) -> dict[str, Any]:
        data = self._request_authenticated("home/getUserInfo")
        return data if isinstance(data, dict) else {}

    def get_ipbox_snapshot(self, terminal_mac_or_key: str) -> dict[str, Any]:
        data = self._request_authenticated("snapshot/ipbox/getFullSub", body={"terminalMac": terminal_mac_or_key})
        return data if isinstance(data, dict) else {}

    def discover_gateway(self, query: str, *, host_override: str | None = None, port_override: int | None = None) -> DaikinGateway:
        homes = self.list_homes()
        homes_by_id = {str(home.get("homeId")): home for home in homes if home.get("homeId") is not None}
        candidates: list[DaikinGateway] = []
        for home_id, home in homes_by_id.items():
            home_detail = {}
            try:
                home_detail = self.get_home(home_id)
            except DaikinError:
                _LOGGER.debug("Failed to get home detail for %s", home_id, exc_info=True)
            home_name = str(first_value(home_detail.get("homeName"), home.get("homeName"), ""))
            for raw_gateway in self.list_gateways(home_id):
                key = str(first_value(raw_gateway.get("gatewayKey"), raw_gateway.get("key"), ""))
                mac = str(first_value(raw_gateway.get("gatewayMac"), raw_gateway.get("mac"), ""))
                name = str(first_value(raw_gateway.get("gatewayName"), mac, key, ""))
                gateway_type = to_int(raw_gateway.get("gatewayType"))
                terminal_type = to_int(raw_gateway.get("ipboxType"))
                host = str(first_value(host_override, raw_gateway.get("socketIp"), ""))
                port = port_override or to_int(raw_gateway.get("socketPort")) or (8009 if gateway_type == 2 else 8008)
                candidates.append(
                    DaikinGateway(
                        home_id=home_id,
                        home_name=home_name,
                        key=key,
                        mac=mac,
                        name=name,
                        gateway_type=gateway_type,
                        terminal_type=terminal_type,
                        host=host,
                        port=port,
                        raw=raw_gateway,
                    )
                )

        needle = (query or "").casefold()
        matches = [
            gateway
            for gateway in candidates
            if not needle
            or needle in " ".join([gateway.name, gateway.key, gateway.mac, gateway.host, compact_json(gateway.raw)]).casefold()
        ]
        if not matches and len(candidates) == 1:
            gateway = candidates[0]
            _LOGGER.info(
                "Gateway query %s did not match; using the only cloud gateway: %s",
                query,
                gateway.name or gateway.key or gateway.mac,
            )
        elif not matches:
            available = ", ".join(
                gateway.name or gateway.key or gateway.mac or gateway.host
                for gateway in candidates
            )
            raise DaikinApiError(
                f"Gateway not found: {query}; available gateways: {available or 'none'}"
            )
        else:
            if len(matches) > 1:
                _LOGGER.warning("Multiple gateways matched %s; using first: %s", query, matches[0])
            gateway = matches[0]
        if not gateway.host:
            raise DaikinApiError("Gateway has no socket host; set host override")
        return gateway
