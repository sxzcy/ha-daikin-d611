"""Pure-asyncio Daikin New Life Multi cloud client using aiohttp."""

from __future__ import annotations

import asyncio
import base64
from contextlib import AsyncExitStack
import copy
import hashlib
import hmac
import json
import logging
import os
import ssl
import tempfile
from typing import Any
from urllib import parse

import aiohttp

from .codec import (
    DaikinApiError,
    DaikinAuthError,
    DaikinError,
    compact_json,
    first_value,
    format_error,
    make_push_id,
    to_int,
    to_list,
)
from .const import AIR_CON_TYPES, AIR_SENSOR_TYPES, DEVICE_TYPE_AIR_CON, DEVICE_TYPE_AIR_SENSOR, DEVICE_TYPE_GEOTHERMIC, DEVICE_TYPE_HD, DEVICE_TYPE_MINI_VAM, DEVICE_TYPE_VAM, GEOTHERMIC_TYPES, HD_TYPES, VAM_TYPES
from .models import DaikinDevice, DaikinGateway

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://newlifemulti.daikin-china.com.cn:4443/v2/"
CERT_INFO_URL = "https://newlifemulti.daikin-china.com.cn:443/v2/home/getCertificateInfo"
POWER_DATA_WEB_URL = "https://newlifemulti.daikin-china.com.cn/v2/web/getHomePowerData"
POWER_DATA_REFERER = "https://newlifemulti.daikin-china.com.cn/daikinStaticWeb/powerconsumptionV2/index_home.html"
USER_AGENT = "DaikinINLS/4.9.0 HomeAssistant"
POWER_WEB_USER_AGENT = "Mozilla/5.0 (Linux; Android 12; Mobile) Daikin/4.9.0 INLS"
MAX_PAGINATION_PAGES = 50
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAm6hQn1LlnQ0DzG0ZiKUP
hNHUUJeFCgw5m/sUPkbOpgwui5Br6OQkrW/+yKeHn6gRLWNqW0+ULha/9lhWWUJm
1O9aYCYPnYrZh6IplBZL72Ad8mHxcXALc9y0wxr9QoF5X2kidZLxiOuoiPq5Pjwx
T/uH/8uYWbAVwlD+e1fjB7hJt8zubxFEbuhvLjMZ8bshCSn55yNVwwOasOORZwjD
UyLdGyl8TA149d7HCUXV0iUqnmfOkniio9nrBc2T1xb4aePP45wJEUFV6I1A3haG
hXBlHNjfR1/vdMViac3DRa+Q2PCDdjcJVE2EzvWapkOxewIYpWlHvqyKkUbhICO/
LQIDAQAB
-----END PUBLIC KEY-----"""

_HEX_CHARS = frozenset("0123456789abcdef")


def calculate_cert_password(push_id: str) -> str:
    """Compute the Daikin certificate-bootstrap CRC-16 password."""
    checksum = 0
    for byte in push_id.encode("utf-8"):
        checksum ^= byte
        for _ in range(8):
            if checksum & 1:
                checksum ^= 67601
            checksum = int(checksum) // 2
    return f"{checksum & 0xFFFF:04X}"


def rsa_public_decrypt_pkcs1_v15_base64(value: str) -> str:
    """Decrypt the PKCS#1 v1.5 RSA-signed client certificate password."""
    from cryptography.hazmat.primitives import serialization

    numbers = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode("ascii")).public_numbers()
    key_size = (numbers.n.bit_length() + 7) // 8
    block = pow(int.from_bytes(base64.b64decode(value), "big"), numbers.e, numbers.n).to_bytes(key_size, "big")
    if len(block) < 11 or block[0] != 0x00 or block[1] not in (0x01, 0x02):
        raise DaikinApiError("Invalid certificate password RSA block")
    try:
        separator = block.index(b"\x00", 2)
    except ValueError as exc:
        raise DaikinApiError("Invalid certificate password RSA separator") from exc
    return block[separator + 1 :].decode("utf-8")


def build_ssl_context_from_p12(p12_bytes: bytes, password: str) -> ssl.SSLContext:
    """Build an mTLS SSLContext from PKCS#12 bytes (run in executor thread)."""
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, pkcs12

    private_key, certificate, extras = pkcs12.load_key_and_certificates(p12_bytes, password.encode("utf-8"))
    if private_key is None or certificate is None:
        raise DaikinApiError("Client certificate has no key or certificate")

    key_fd = cert_fd = None
    key_path = cert_path = None
    try:
        key_fd, key_path = tempfile.mkstemp(prefix="ha-daikin-d611-key-", suffix=".pem")
        cert_fd, cert_path = tempfile.mkstemp(prefix="ha-daikin-d611-cert-", suffix=".pem")
        if os.name == "posix":
            os.chmod(key_path, 0o600)
            os.chmod(cert_path, 0o600)
        with os.fdopen(key_fd, "wb") as f:
            key_fd = None
            f.write(private_key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()))
        with os.fdopen(cert_fd, "wb") as f:
            cert_fd = None
            f.write(certificate.public_bytes(Encoding.PEM))
            for item in extras or ():
                f.write(item.public_bytes(Encoding.PEM))

        context = ssl.create_default_context()
        try:
            context.set_ciphers("DEFAULT@SECLEVEL=1")
        except ssl.SSLError:
            pass
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        return context
    finally:
        for fd in (key_fd, cert_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        for path in (key_path, cert_path):
            if path is not None:
                try:
                    os.unlink(path)
                except OSError:
                    pass


async def async_fetch_client_certificate(
    session: aiohttp.ClientSession, push_id: str, timeout: float,
) -> tuple[bytes, str]:
    """Fetch and verify the client PKCS#12 certificate asynchronously."""
    body = {"clientId": push_id, "password": calculate_cert_password(push_id), "fileType": "p12", "clientType": "APP"}
    req_timeout = aiohttp.ClientTimeout(total=timeout)
    try:
        async with session.post(
            CERT_INFO_URL,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json; charset=utf-8", "User-Agent": USER_AGENT},
            timeout=req_timeout,
        ) as resp:
            raw = (await resp.read()).decode("utf-8", errors="replace")
            if resp.status >= 400:
                raise DaikinApiError(f"Certificate info HTTP {resp.status}: {raw[:500]}")
            payload = json.loads(raw or "{}")
    except DaikinApiError:
        raise
    except (aiohttp.ClientError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise DaikinApiError(f"Failed to get client certificate info: {format_error(exc)}") from exc

    if not isinstance(payload, dict) or payload.get("code") not in (0, "0", None):
        raise DaikinApiError(f"Certificate info failed: {compact_json(payload)}")

    info = (payload.get("data") or {}).get("downloadInfo") or {}
    resources_path, encrypted_password, expected_md5 = info.get("resourcesPath"), info.get("certPassword"), info.get("md5")
    if not resources_path or not encrypted_password:
        raise DaikinApiError(f"Incomplete certificate info: {compact_json(info)}")

    resources_url = str(resources_path).strip()
    parsed = parse.urlparse(resources_url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise DaikinApiError("Invalid client certificate download URL")

    try:
        async with session.get(resources_url, timeout=req_timeout) as resp:
            p12_bytes = await resp.read()
            if resp.status >= 400:
                raise DaikinApiError(f"Certificate download HTTP {resp.status}")
    except DaikinApiError:
        raise
    except (aiohttp.ClientError, TimeoutError, OSError) as exc:
        raise DaikinApiError(f"Failed to download client certificate: {format_error(exc)}") from exc

    if expected_md5 not in (None, ""):
        normalized_md5 = str(expected_md5).strip().lower()
        if len(normalized_md5) != 32 or any(ch not in _HEX_CHARS for ch in normalized_md5):
            raise DaikinApiError("Malformed client certificate MD5 digest")
        if not hmac.compare_digest(hashlib.md5(p12_bytes).hexdigest(), normalized_md5):
            raise DaikinApiError("Client certificate MD5 mismatch")
    else:
        _LOGGER.warning("Client certificate metadata did not include an MD5 digest")

    return p12_bytes, rsa_public_decrypt_pkcs1_v15_base64(str(encrypted_password))


class DaikinCloudClient:
    """Pure-asyncio Daikin New Life Multi cloud client."""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        timeout: float,
        base_url: str = DEFAULT_BASE_URL,
        push_id: str | None = None,
        bootstrap_session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.username = username
        self.password = password
        self.timeout = timeout
        self.base_url = base_url.rstrip("/") + "/"
        self.push_id = push_id or make_push_id()
        self.token: str | None = None
        self._bootstrap_session = bootstrap_session
        self._ssl_context: ssl.SSLContext | None = None
        self._mtls_session: aiohttp.ClientSession | None = None
        self._auth_lock = asyncio.Lock()

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if content_type:
            headers["Content-Type"] = content_type
        if self.token:
            headers["token"] = self.token
        return headers

    async def _async_ensure_session_locked(self) -> aiohttp.ClientSession:
        if self._mtls_session is not None and not self._mtls_session.closed:
            return self._mtls_session
        if self._ssl_context is None:
            async with AsyncExitStack() as stack:
                session = self._bootstrap_session or await stack.enter_async_context(
                    aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
                )
                p12_bytes, cert_pw = await async_fetch_client_certificate(session, self.push_id, self.timeout)
            self._ssl_context = await asyncio.to_thread(build_ssl_context_from_p12, p12_bytes, cert_pw)
        self._mtls_session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=self._ssl_context),
            timeout=aiohttp.ClientTimeout(total=self.timeout),
        )
        return self._mtls_session

    async def _async_ensure_session(self) -> aiohttp.ClientSession:
        if self._mtls_session is not None and not self._mtls_session.closed:
            return self._mtls_session
        async with self._auth_lock:
            return await self._async_ensure_session_locked()

    async def async_close(self) -> None:
        """Close the cached mTLS aiohttp session if owned by this client."""
        session, self._mtls_session = self._mtls_session, None
        if session is not None and not session.closed:
            await session.close()

    async def _async_request(
        self,
        endpoint: str,
        *,
        form: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> Any:
        if form is not None and body is not None:
            raise ValueError("form and body cannot be used together")
        active = session or await self._async_ensure_session()
        if form is not None:
            form_data = {**form, "version": form.get("version", "1")}
            data, headers = parse.urlencode(form_data).encode("utf-8"), self._headers("application/x-www-form-urlencoded")
        elif body is not None:
            data, headers = json.dumps(body, ensure_ascii=False).encode("utf-8"), self._headers("application/json; charset=utf-8")
        else:
            data, headers = b"", self._headers()

        try:
            async with active.post(
                parse.urljoin(self.base_url, endpoint.lstrip("/")),
                data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                raw = (await resp.read()).decode("utf-8", errors="replace")
                if resp.status >= 400:
                    raise DaikinApiError(f"HTTP {resp.status}: {raw[:500]}")
        except DaikinApiError:
            raise
        except (aiohttp.ClientError, TimeoutError, OSError) as exc:
            raise DaikinApiError(f"Request failed: {format_error(exc)}") from exc

        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise DaikinApiError(f"Invalid JSON response: {raw[:500]}") from exc

        if isinstance(payload, dict) and "code" in payload:
            code = payload.get("code")
            if code not in (0, "0", None):
                msg = str(first_value(payload.get("description"), payload.get("message"), payload.get("msg"), code))
                if any(word in msg for word in ("密码", "手机号", "登录")):
                    raise DaikinAuthError(msg)
                raise DaikinApiError(msg)
            return payload.get("data")
        return payload

    async def _async_login_locked(self) -> None:
        self.token = None
        session = await self._async_ensure_session_locked()
        data = await self._async_request(
            "app/nlcLoginV2",
            form={"authId": self.username, "password": self.password, "pushId": self.push_id},
            session=session,
        )
        if not isinstance(data, dict):
            raise DaikinApiError(f"Unexpected login response: {compact_json(data)}")
        token = first_value(data.get("accessToken"), data.get("token"), data.get("access_token"))
        if not token:
            raise DaikinApiError(f"Login response has no token: {compact_json(data)}")
        self.token = str(token)

    async def async_login(self) -> None:
        async with self._auth_lock:
            await self._async_login_locked()

    async def async_ensure_login(self) -> None:
        if not self.token:
            async with self._auth_lock:
                if not self.token:
                    await self._async_login_locked()

    async def _async_request_authenticated(
        self, endpoint: str, *, form: dict[str, Any] | None = None, body: dict[str, Any] | None = None,
    ) -> Any:
        await self.async_ensure_login()
        used_token = self.token
        try:
            return await self._async_request(endpoint, form=form, body=body)
        except (DaikinApiError, DaikinAuthError):
            if not used_token:
                raise
            _LOGGER.debug("Authenticated Daikin request failed; refreshing login and retrying", exc_info=True)
            async with self._auth_lock:
                if self.token == used_token:
                    self.token = None
                    await self._async_login_locked()
            return await self._async_request(endpoint, form=form, body=body)

    @staticmethod
    def _extract_list_and_total(data: Any) -> tuple[list[dict[str, Any]], int | None, bool]:
        if isinstance(data, list):
            return [i for i in data if isinstance(i, dict)], None, False
        if not isinstance(data, dict):
            return [], None, False
        for key in ("list", "records", "rows", "items", "data"):
            if isinstance(data.get(key), list):
                items = [i for i in data[key] if isinstance(i, dict)]
                total = to_int(first_value(data.get("total"), data.get("totalCount")))
                pages = to_int(first_value(data.get("pages"), data.get("totalPages")))
                page_num = to_int(first_value(data.get("pageNum"), data.get("pageNo"), data.get("page"), data.get("current")))
                has_more = bool(data.get("hasMore") or data.get("hasNextPage")) or (
                    pages is not None and page_num is not None and page_num < pages
                )
                return items, total, has_more
        return [], None, False

    async def _async_request_paginated_list(
        self, endpoint: str, *, base_body: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        first = await self._async_request_authenticated(endpoint, body=base_body)
        items, total, has_more = self._extract_list_and_total(first)
        if not items or (not has_more and (total is None or len(items) >= total)):
            return items
        collected = list(items)
        page = 2
        while page <= MAX_PAGINATION_PAGES:
            if total is not None and len(collected) >= total:
                break
            req_body = {**(base_body or {}), "pageNum": page, "pageNo": page, "pageSize": len(items)}
            nxt = await self._async_request_authenticated(endpoint, body=req_body)
            page_items, _nxt_total, nxt_more = self._extract_list_and_total(nxt)
            if not page_items:
                break
            collected.extend(page_items)
            if not nxt_more and (total is None or len(collected) >= total) and len(page_items) < len(items):
                break
            page += 1
        return collected

    async def async_list_homes(self) -> list[dict[str, Any]]:
        return await self._async_request_paginated_list("home/listHomeByLoginUser")

    async def async_get_home(self, home_id: str) -> dict[str, Any]:
        data = await self._async_request_authenticated("home/getHome", body={"homeId": home_id})
        return data if isinstance(data, dict) else {}

    async def async_list_gateways(self, home_id: str) -> list[dict[str, Any]]:
        return await self._async_request_paginated_list("home/listGatewayAuth", base_body={"homeId": home_id})

    async def async_get_user_info(self) -> dict[str, Any]:
        data = await self._async_request_authenticated("home/getUserInfo")
        return data if isinstance(data, dict) else {}

    async def async_get_power_consumption_url(self, home_id: int | str, user_type: str = "1") -> str:
        """Fetch the H5 power consumption URL containing encryptNlcId."""
        normalized_home_id: int | str = int(home_id) if str(home_id).isdigit() else str(home_id)
        data = await self._async_request_authenticated(
            "home/getHomePowerDataUrl",
            body={"homeId": normalized_home_id, "userType": str(user_type)},
        )
        if not isinstance(data, dict) or not data.get("url"):
            raise DaikinApiError(f"Power consumption URL missing: {compact_json(data)}")
        return str(data["url"])

    @staticmethod
    def extract_nlc_id_from_url(power_url: str) -> str | None:
        """Extract nlcId / encryptNlcId from the Daikin power consumption H5 URL."""
        query_params = parse.parse_qs(parse.urlparse(power_url).query)
        for key in ("nlcId", "encryptNlcId"):
            if query_params.get(key):
                return str(query_params[key][0])
        return None

    async def async_get_home_power_data(
        self,
        *,
        home_id: int | str,
        year: int,
        month: int,
        encrypt_nlc_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch monthly and daily power consumption data purely asynchronously."""
        if not encrypt_nlc_id:
            power_url = await self.async_get_power_consumption_url(home_id)
            encrypt_nlc_id = self.extract_nlc_id_from_url(power_url)
            if not encrypt_nlc_id:
                raise DaikinApiError("Could not extract nlcId from power consumption URL")

        normalized_home_id: int | str = int(home_id) if str(home_id).isdigit() else str(home_id)
        form_bytes = parse.urlencode({
            "encryptNlcId": str(encrypt_nlc_id),
            "homeId": normalized_home_id,
            "year": int(year),
            "month": int(month),
        }).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": POWER_WEB_USER_AGENT,
            "Referer": POWER_DATA_REFERER,
        }
        async with AsyncExitStack() as stack:
            session = self._bootstrap_session or await stack.enter_async_context(
                aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
            )
            try:
                async with session.post(
                    POWER_DATA_WEB_URL,
                    data=form_bytes,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    raw = (await resp.read()).decode("utf-8", errors="replace")
                    if resp.status >= 400:
                        raise DaikinApiError(f"Power data HTTP {resp.status}: {raw[:500]}")
            except DaikinApiError:
                raise
            except (aiohttp.ClientError, TimeoutError, OSError) as exc:
                raise DaikinApiError(f"Power data request failed: {format_error(exc)}") from exc

        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise DaikinApiError(f"Invalid power data JSON: {raw[:500]}") from exc
        if not isinstance(payload, dict) or payload.get("code") not in (0, "0", None):
            msg = str(first_value((payload or {}).get("description"), (payload or {}).get("message"), (payload or {}).get("code")))
            raise DaikinApiError(f"Power data API failed: {msg}")
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _merge_snapshot_pages(base: dict[str, Any], extra: dict[str, Any]) -> bool:
        added = False
        for key in ("ipbox", "indoor", "vam", "mini_vam", "sensor", "hd", "geothermic", "floor_heating"):
            extra_items = [i for i in to_list(extra.get(key)) if isinstance(i, dict)]
            if not extra_items:
                continue
            cur = [i for i in to_list(base.get(key)) if isinstance(i, dict)]
            seen = {str(i.get("key")) for i in cur if i.get("key")}
            for item in extra_items:
                item_key = str(item.get("key") or "")
                if item_key and item_key in seen:
                    continue
                if item_key:
                    seen.add(item_key)
                cur.append(item)
                added = True
            base[key] = cur
        return added

    @staticmethod
    def _snapshot_has_more(data: dict[str, Any]) -> bool:
        if bool(data.get("hasMore") or data.get("hasNextPage")):
            return True
        total = to_int(first_value(data.get("total"), data.get("totalCount")))
        pages = to_int(first_value(data.get("pages"), data.get("totalPages")))
        page_num = to_int(first_value(data.get("pageNum"), data.get("pageNo"), data.get("page"), data.get("current")))
        if pages is not None and page_num is not None and page_num < pages:
            return True
        if total is not None:
            count = sum(
                len(to_list(data.get(k)))
                for k in ("indoor", "vam", "mini_vam", "sensor", "hd", "geothermic", "floor_heating")
            )
            return count < total
        return False

    async def async_get_ipbox_snapshot(self, terminal_mac_or_key: str) -> dict[str, Any]:
        data = await self._async_request_authenticated("snapshot/ipbox/getFullSub", body={"terminalMac": terminal_mac_or_key})
        if not isinstance(data, dict):
            return {}
        merged = copy.deepcopy(data)
        page = 2
        while page <= MAX_PAGINATION_PAGES and self._snapshot_has_more(merged):
            nxt = await self._async_request_authenticated(
                "snapshot/ipbox/getFullSub",
                body={"terminalMac": terminal_mac_or_key, "pageNum": page, "pageNo": page},
            )
            if not isinstance(nxt, dict) or not self._merge_snapshot_pages(merged, nxt):
                break
            if not self._snapshot_has_more(nxt):
                break
            page += 1
        return merged

    async def async_discover_gateway(
        self, query: str, *, host_override: str | None = None, port_override: int | None = None,
    ) -> DaikinGateway:
        homes = {str(h["homeId"]): h for h in await self.async_list_homes() if h.get("homeId") is not None}
        candidates: list[DaikinGateway] = []
        for home_id, home in homes.items():
            try:
                home_detail = await self.async_get_home(home_id)
            except DaikinError:
                home_detail = {}
            home_name = str(first_value(home_detail.get("homeName"), home.get("homeName"), ""))
            for raw_gw in await self.async_list_gateways(home_id):
                key = str(first_value(raw_gw.get("gatewayKey"), raw_gw.get("key"), ""))
                mac = str(first_value(raw_gw.get("gatewayMac"), raw_gw.get("mac"), ""))
                gw_type = to_int(raw_gw.get("gatewayType"))
                candidates.append(
                    DaikinGateway(
                        home_id=home_id, home_name=home_name, key=key, mac=mac,
                        name=str(first_value(raw_gw.get("gatewayName"), mac, key, "")),
                        gateway_type=gw_type, terminal_type=to_int(raw_gw.get("ipboxType")),
                        host=str(first_value(host_override, raw_gw.get("socketIp"), "")),
                        port=port_override or to_int(raw_gw.get("socketPort")) or (8009 if gw_type == 2 else 8008),
                        raw=raw_gw,
                    )
                )

        needle = (query or "").casefold()
        matches = [
            gw for gw in candidates
            if not needle or needle in " ".join((gw.name, gw.key, gw.mac, gw.host, compact_json(gw.raw))).casefold()
        ]
        if not matches and len(candidates) == 1:
            gateway = candidates[0]
        elif not matches:
            avail = ", ".join(gw.name or gw.key or gw.mac or gw.host for gw in candidates)
            raise DaikinApiError(f"Gateway not found: {query}; available gateways: {avail or 'none'}")
        else:
            if len(matches) > 1:
                _LOGGER.warning("Multiple gateways matched %s; using first: %s", query, matches[0].name or matches[0].id)
            gateway = matches[0]
        if not gateway.host:
            raise DaikinApiError("Gateway has no socket host; set host override")
        return gateway


_CLOUD_INT_KEYS = (
    "switch", "switches", "mode", "air_flow", "volume", "outdoor_status",
    "filter_used_time", "filter_used_percent", "pm25", "co2", "voc", "tvoc_status", "hcho_status",
)
_CLOUD_FLOAT_KEYS = ("temp", "target_temperature", "sensor_temperature", "humidity", "hcho", "tvoc")


def _norm_key(value: Any) -> str:
    text = str(value or "").strip().replace(":", "").replace("-", "").casefold()
    return text.removeprefix("0x")


def _cloud_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    text = str(value).strip().casefold()
    if text in {"1", "true", "on", "online", "yes"}:
        return True
    return False if text in {"0", "false", "off", "offline", "no"} else None


def _cloud_float(value: Any) -> float | Any:
    if value in (None, ""):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _item_unique_token(item: dict[str, Any]) -> str | None:
    physics = item.get("physics") if isinstance(item.get("physics"), dict) else {}
    raw = first_value(item.get("key"), physics.get("serial_no"), physics.get("device_no"), physics.get("mac"))
    return str(raw) if raw not in (None, "") else None


def _match_cloud_item(
    device: DaikinDevice,
    indoor: list[dict[str, Any]],
    vam: list[dict[str, Any]],
    sensors: list[dict[str, Any]],
    *,
    hd: list[dict[str, Any]] = (),
    geothermic: list[dict[str, Any]] = (),
    used_tokens: set[str] | None = None,
) -> dict[str, Any] | None:
    candidates = (
        indoor if device.device_type in AIR_CON_TYPES
        else vam if device.device_type in VAM_TYPES
        else sensors if device.device_type in AIR_SENSOR_TYPES
        else hd if device.device_type in HD_TYPES
        else geothermic if device.device_type in GEOTHERMIC_TYPES
        else ()
    )
    used = used_tokens if used_tokens is not None else set()
    available = [item for item in candidates if (_item_unique_token(item) not in used)]
    dev_key, dev_alias = _norm_key(device.name), _norm_key(device.alias)

    # Pass 1: exact hardware identity / name / alias match
    for item in available:
        physics = item.get("physics") if isinstance(item.get("physics"), dict) else {}
        hay = " ".join(_norm_key(p) for p in (item.get("key"), physics.get("serial_no"), physics.get("mac"), physics.get("device_no")))
        if (dev_key and dev_key in hay) or (dev_alias and dev_alias in hay):
            return item

    # Pass 2: room_id match (pick unit-th match if multiple items share the same room)
    room_matches = []
    for item in available:
        physics = item.get("physics") if isinstance(item.get("physics"), dict) else {}
        if to_int(physics.get("socket_room_id")) == device.room_id or to_int(physics.get("center_address")) == device.room_id - 1:
            room_matches.append(item)
    if room_matches:
        return room_matches[device.unit] if device.unit < len(room_matches) else room_matches[0]
    return None


def parse_cloud_snapshot(
    snapshot: dict[str, Any],
    devices: list[DaikinDevice],
    refreshed_at: str,
) -> dict[str, dict[str, Any]]:
    """Extract normalized per-device cloud status dicts from a Daikin ipbox snapshot."""
    online_by_key = {
        str(sub["device_key"]): sub.get("online")
        for ipbox in snapshot.get("ipbox", []) if isinstance(ipbox, dict)
        for sub in ipbox.get("sub", []) if isinstance(sub, dict) and sub.get("device_key")
    }
    indoor = [i for i in to_list(snapshot.get("indoor")) if isinstance(i, dict)]
    vam = [i for i in to_list(snapshot.get("mini_vam")) + to_list(snapshot.get("vam")) if isinstance(i, dict)]
    sensors = [i for i in to_list(snapshot.get("sensor")) if isinstance(i, dict)]
    hd = [i for i in to_list(snapshot.get("hd")) if isinstance(i, dict)]
    geothermic = [i for i in to_list(snapshot.get("geothermic")) + to_list(snapshot.get("floor_heating")) if isinstance(i, dict)]

    extracted: dict[str, dict[str, Any]] = {}
    used_tokens: set[str] = set()
    for device in devices:
        item = _match_cloud_item(
            device, indoor, vam, sensors, hd=hd, geothermic=geothermic, used_tokens=used_tokens,
        )
        if item is None:
            continue
        if (tok := _item_unique_token(item)) is not None:
            used_tokens.add(tok)
        online = item.get("online")
        if online is None and item.get("key") in online_by_key:
            online = online_by_key[str(item["key"])]
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        physics = item.get("physics") if isinstance(item.get("physics"), dict) else {}
        filters = item.get("filter") if isinstance(item.get("filter"), dict) else {}
        capability = item.get("capability") if isinstance(item.get("capability"), dict) else {}
        cloud: dict[str, Any] = {
            **status,
            "cloud_key": item.get("key"),
            "cloud_online": _cloud_bool(online),
            "cloud_physics": copy.deepcopy(physics),
            "last_cloud_refresh": refreshed_at,
            "cloud_source": "snapshot",
        }
        if capability:
            cloud["cloud_capability"] = copy.deepcopy(capability)
        if item.get("key") and str(item["key"]).startswith("SENSOR:"):
            cloud["sensor_temperature"] = cloud.get("temp")
        elif "temp" in cloud:
            cloud["target_temperature"] = cloud["temp"]
        if "switches" in cloud:
            cloud["switch"] = cloud["switches"]
        if "volume" in cloud:
            cloud["air_flow"] = cloud["volume"]
        if "direction1" in cloud and "fan_direction1" not in cloud:
            cloud["fan_direction1"] = cloud["direction1"]
        if "direction2" in cloud and "fan_direction2" not in cloud:
            cloud["fan_direction2"] = cloud["direction2"]
        for key, value in filters.items():
            cloud[f"filter_{key.removeprefix('filter_')}"] = value
        for key in _CLOUD_INT_KEYS:
            if key in cloud:
                cloud[key] = first_value(to_int(cloud[key]), cloud[key])
        for key in _CLOUD_FLOAT_KEYS:
            if key in cloud:
                cloud[key] = _cloud_float(cloud[key])
        for key in ("online", "cloud_online"):
            if key in cloud:
                cloud[key] = first_value(_cloud_bool(cloud[key]), cloud[key])
        extracted[device.unique_id] = cloud
    return extracted


def synthesize_missing_cloud_devices(
    snapshot: dict[str, Any],
    existing_devices: list[DaikinDevice],
    gateway: DaikinGateway,
) -> list[DaikinDevice]:
    """Build fallback DaikinDevice objects for cloud snapshot items absent from local room info."""
    indoor = [i for i in to_list(snapshot.get("indoor")) if isinstance(i, dict)]
    vam = [i for i in to_list(snapshot.get("mini_vam")) + to_list(snapshot.get("vam")) if isinstance(i, dict)]
    sensors = [i for i in to_list(snapshot.get("sensor")) if isinstance(i, dict)]
    hd = [i for i in to_list(snapshot.get("hd")) if isinstance(i, dict)]
    geothermic = [i for i in to_list(snapshot.get("geothermic")) + to_list(snapshot.get("floor_heating")) if isinstance(i, dict)]

    used_tokens: set[str] = set()
    for dev in existing_devices:
        matched = _match_cloud_item(dev, indoor, vam, sensors, hd=hd, geothermic=geothermic, used_tokens=used_tokens)
        if matched is not None and (tok := _item_unique_token(matched)) is not None:
            used_tokens.add(tok)

    existing_keys = {(d.device_type, d.room_id, d.unit) for d in existing_devices}
    extras: list[DaikinDevice] = []
    buckets: list[tuple[list[dict[str, Any]], int, str]] = [
        (indoor, DEVICE_TYPE_AIR_CON, "AIR_CON"),
        ([i for i in to_list(snapshot.get("mini_vam")) if isinstance(i, dict)], DEVICE_TYPE_MINI_VAM, "MINI_VAM"),
        ([i for i in to_list(snapshot.get("vam")) if isinstance(i, dict)], DEVICE_TYPE_VAM, "VAM"),
        (sensors, DEVICE_TYPE_AIR_SENSOR, "AIR_SENSOR"),
        (hd, DEVICE_TYPE_HD, "HD"),
        (geothermic, DEVICE_TYPE_GEOTHERMIC, "GEOTHERMIC"),
    ]
    next_room_counters: dict[tuple[int, int], int] = {}
    for items, default_type, default_type_name in buckets:
        for idx, item in enumerate(items):
            tok = _item_unique_token(item)
            if tok and tok in used_tokens:
                continue
            physics = item.get("physics") if isinstance(item.get("physics"), dict) else {}
            room_id = to_int(physics.get("socket_room_id"))
            if room_id is None and (ca := to_int(physics.get("center_address"))) is not None:
                room_id = ca + 1
            if room_id is None:
                if default_type != DEVICE_TYPE_AIR_SENSOR:
                    continue
                room_id = 100 + idx
            unit = next_room_counters.get((default_type, room_id), 0)
            while (default_type, room_id, unit) in existing_keys:
                unit += 1
            next_room_counters[(default_type, room_id)] = unit + 1
            existing_keys.add((default_type, room_id, unit))
            if tok:
                used_tokens.add(tok)
            name = str(first_value(physics.get("name"), physics.get("mac"), item.get("key"), ""))
            extras.append(
                DaikinDevice(
                    gateway_id=gateway.id,
                    gateway_name=gateway.name,
                    room_id=room_id,
                    room_name=name,
                    room_alias=name,
                    device_type=default_type,
                    device_type_name=default_type_name,
                    unit=unit,
                    name=str(first_value(physics.get("mac"), physics.get("serial_no"), item.get("key"), name)),
                    alias=name,
                    raw={"cloud_synthesized": True, "cloud_key": item.get("key")},
                )
            )
    return extras
