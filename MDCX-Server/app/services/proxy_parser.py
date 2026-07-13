"""
代理节点 URL 解析器

支持解析以下格式的节点 URL 并输出统一的 NodeConfig：
- vmess://  (v2rayN 兼容, base64 JSON)
- vless://  (标准 URL query)
- trojan:// (标准 URL query)
- ss://     (SIP002)

所有输出用 Xray outbound JSON 结构，方便直接塞进 config.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger(__name__)


@dataclass
class NodeConfig:
    """统一节点配置"""
    id: str
    name: str  # 节点别名 / remark
    protocol: str  # vmess / vless / trojan / shadowsocks
    address: str
    port: int
    raw_url: str
    outbound: dict[str, Any]  # xray outbound json
    latency_ms: int | None = None  # 测速结果
    country: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _b64_decode_padded(data: str) -> bytes:
    """base64 解码，自动补齐 padding。"""
    data = data.strip().replace("-", "+").replace("_", "/")
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.b64decode(data)


def parse_vmess(url: str) -> NodeConfig:
    """
    解析 vmess://<base64 json>

    Payload 例:
      {"v":"2","ps":"节点1","add":"1.2.3.4","port":"443","id":"uuid","aid":"0",
       "net":"ws","type":"none","host":"","path":"/path","tls":"tls","sni":""}
    """
    if not url.startswith("vmess://"):
        raise ValueError("Not a vmess:// URL")
    payload_b64 = url[len("vmess://"):]
    try:
        payload = json.loads(_b64_decode_padded(payload_b64).decode("utf-8", errors="replace"))
    except Exception as e:
        raise ValueError(f"vmess base64/json decode failed: {e}") from e

    address = str(payload.get("add", "")).strip()
    port = int(payload.get("port", 0))
    uid = str(payload.get("id", "")).strip()
    aid = int(payload.get("aid", 0) or 0)
    net = str(payload.get("net", "tcp")).strip() or "tcp"
    security = str(payload.get("scy") or payload.get("security") or "auto")
    tls = str(payload.get("tls", "")).strip()
    host_hdr = str(payload.get("host", "")).strip()
    path = str(payload.get("path", "")).strip()
    sni = str(payload.get("sni", "")).strip() or host_hdr or address
    name = str(payload.get("ps", "")).strip() or f"{address}:{port}"

    stream: dict[str, Any] = {"network": net, "security": tls or "none"}
    if tls == "tls":
        stream["tlsSettings"] = {"serverName": sni, "allowInsecure": False}
    elif tls == "reality":
        stream["realitySettings"] = {
            "serverName": sni,
            "publicKey": str(payload.get("pbk", "")),
            "shortId": str(payload.get("sid", "")),
            "fingerprint": str(payload.get("fp", "chrome")),
        }

    if net == "ws":
        stream["wsSettings"] = {"path": path or "/", "headers": {"Host": host_hdr} if host_hdr else {}}
    elif net == "grpc":
        stream["grpcSettings"] = {"serviceName": path.lstrip("/")}
    elif net == "h2":
        stream["httpSettings"] = {"host": [host_hdr] if host_hdr else [], "path": path or "/"}

    outbound = {
        "tag": name,
        "protocol": "vmess",
        "settings": {
            "vnext": [{
                "address": address,
                "port": port,
                "users": [{"id": uid, "alterId": aid, "security": security}],
            }]
        },
        "streamSettings": stream,
    }

    return NodeConfig(
        id=str(uuid.uuid4()),
        name=name,
        protocol="vmess",
        address=address,
        port=port,
        raw_url=url,
        outbound=outbound,
    )


def parse_vless(url: str) -> NodeConfig:
    """
    解析 vless://uuid@host:port?type=ws&security=tls&sni=xxx&path=/path#name
    """
    if not url.startswith("vless://"):
        raise ValueError("Not a vless:// URL")
    parsed = urlparse(url)
    if not parsed.hostname or not parsed.port:
        raise ValueError("vless URL missing host or port")

    uid = parsed.username or ""
    address = parsed.hostname
    port = parsed.port
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    name = unquote(parsed.fragment or "") or f"{address}:{port}"

    net = q.get("type", "tcp") or "tcp"
    security = q.get("security", "none") or "none"
    sni = q.get("sni") or q.get("peer") or address
    flow = q.get("flow", "")

    stream: dict[str, Any] = {"network": net, "security": security}
    if security == "tls":
        stream["tlsSettings"] = {
            "serverName": sni,
            "allowInsecure": False,
            "fingerprint": q.get("fp", "chrome"),
        }
    elif security == "reality":
        stream["realitySettings"] = {
            "serverName": sni,
            "publicKey": q.get("pbk", ""),
            "shortId": q.get("sid", ""),
            "fingerprint": q.get("fp", "chrome"),
            "spiderX": q.get("spx", ""),
        }

    if net == "ws":
        stream["wsSettings"] = {"path": q.get("path", "/"), "headers": {"Host": q.get("host", "")} if q.get("host") else {}}
    elif net == "grpc":
        stream["grpcSettings"] = {"serviceName": q.get("serviceName", "")}

    user_obj: dict[str, Any] = {"id": uid, "encryption": q.get("encryption", "none")}
    if flow:
        user_obj["flow"] = flow

    outbound = {
        "tag": name,
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": address,
                "port": port,
                "users": [user_obj],
            }]
        },
        "streamSettings": stream,
    }

    return NodeConfig(
        id=str(uuid.uuid4()),
        name=name,
        protocol="vless",
        address=address,
        port=port,
        raw_url=url,
        outbound=outbound,
    )


def parse_trojan(url: str) -> NodeConfig:
    """
    解析 trojan://password@host:port?sni=xxx&type=ws&path=/xxx#name
    """
    if not url.startswith("trojan://"):
        raise ValueError("Not a trojan:// URL")
    parsed = urlparse(url)
    if not parsed.hostname or not parsed.port:
        raise ValueError("trojan URL missing host or port")

    password = parsed.username or ""
    address = parsed.hostname
    port = parsed.port
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    name = unquote(parsed.fragment or "") or f"{address}:{port}"

    net = q.get("type", "tcp") or "tcp"
    sni = q.get("sni") or q.get("peer") or address

    stream: dict[str, Any] = {
        "network": net,
        "security": "tls",
        "tlsSettings": {
            "serverName": sni,
            "allowInsecure": q.get("allowInsecure", "0") == "1",
        },
    }
    if net == "ws":
        stream["wsSettings"] = {"path": q.get("path", "/"), "headers": {"Host": q.get("host", "")} if q.get("host") else {}}
    elif net == "grpc":
        stream["grpcSettings"] = {"serviceName": q.get("serviceName", "")}

    outbound = {
        "tag": name,
        "protocol": "trojan",
        "settings": {
            "servers": [{
                "address": address,
                "port": port,
                "password": password,
            }]
        },
        "streamSettings": stream,
    }

    return NodeConfig(
        id=str(uuid.uuid4()),
        name=name,
        protocol="trojan",
        address=address,
        port=port,
        raw_url=url,
        outbound=outbound,
    )


def parse_ss(url: str) -> NodeConfig:
    """
    解析 SIP002 格式：ss://base64(method:password)@host:port#name
    或旧格式：ss://base64(method:password@host:port)#name
    """
    if not url.startswith("ss://"):
        raise ValueError("Not a ss:// URL")

    rest = url[len("ss://"):]
    fragment = ""
    if "#" in rest:
        rest, fragment = rest.split("#", 1)
    name = unquote(fragment) if fragment else ""

    # SIP002: <base64_userinfo>@<host>:<port>[/?plugin=...]
    if "@" in rest:
        userinfo_b64, hostport = rest.split("@", 1)
        try:
            userinfo = _b64_decode_padded(userinfo_b64).decode("utf-8", errors="replace")
        except Exception:
            userinfo = userinfo_b64  # 已明文
        if ":" not in userinfo:
            raise ValueError("ss userinfo missing method:password")
        method, password = userinfo.split(":", 1)
        # 分离 query
        query = ""
        if "?" in hostport:
            hostport, query = hostport.split("?", 1)
        if ":" not in hostport:
            raise ValueError("ss hostport missing port")
        address, port_str = hostport.rsplit(":", 1)
        address = address.strip("/")
        port = int(port_str.rstrip("/"))
    else:
        # 旧格式：整个 base64
        try:
            decoded = _b64_decode_padded(rest).decode("utf-8", errors="replace")
        except Exception as e:
            raise ValueError(f"ss legacy base64 decode failed: {e}") from e
        if "@" not in decoded or ":" not in decoded:
            raise ValueError("ss legacy payload malformed")
        method_pass, hostport = decoded.rsplit("@", 1)
        method, password = method_pass.split(":", 1)
        address, port_str = hostport.rsplit(":", 1)
        port = int(port_str)

    if not name:
        name = f"{address}:{port}"

    outbound = {
        "tag": name,
        "protocol": "shadowsocks",
        "settings": {
            "servers": [{
                "address": address,
                "port": port,
                "method": method,
                "password": password,
            }]
        },
    }

    return NodeConfig(
        id=str(uuid.uuid4()),
        name=name,
        protocol="shadowsocks",
        address=address,
        port=port,
        raw_url=url,
        outbound=outbound,
    )


_PARSERS = {
    "vmess://": parse_vmess,
    "vless://": parse_vless,
    "trojan://": parse_trojan,
    "ss://": parse_ss,
}


def parse_node_url(url: str) -> NodeConfig:
    """根据 URL scheme 自动选择解析器。"""
    url = url.strip()
    for prefix, parser in _PARSERS.items():
        if url.startswith(prefix):
            return parser(url)
    raise ValueError(f"Unsupported node URL scheme: {url[:20]}...")


def parse_subscription_content(content: str) -> list[NodeConfig]:
    """
    解析订阅内容。订阅一般返回 base64 编码的多行节点 URL。

    自动尝试 base64 解码；若失败按明文行解析。
    """
    content = content.strip()
    text: str

    # 尝试 base64 解码
    try:
        decoded_bytes = _b64_decode_padded(content)
        decoded_text = decoded_bytes.decode("utf-8", errors="replace")
        if any(decoded_text.startswith(p) for p in _PARSERS):
            text = decoded_text
        else:
            text = content
    except Exception:
        text = content

    nodes: list[NodeConfig] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            nodes.append(parse_node_url(line))
        except Exception as e:
            logger.debug("skip malformed node line: %s (%s)", line[:40], e)
    return nodes
