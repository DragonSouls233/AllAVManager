"""
Xray 配置生成器

根据节点池 + 内置分流规则生成 xray -c config.json。

设计：
- inbound: socks5 + http（同端口不同 tag）
- outbounds: 每个节点一个 + direct + block
- routing: 目标域名匹配 → 走对应节点 balancer
- 分流规则内置刮削常用站点，用户零配置
"""

from __future__ import annotations

from typing import Any

from app.services.proxy_parser import NodeConfig

# ============================================================
# 内置分流规则：这些站点必须走代理（刮削常用海外源）
# ============================================================
SCRAPE_PROXY_DOMAINS = [
    "javbus.com",
    "javdb.com",
    "javlibrary.com",
    "missav.com",
    "missav.ai",
    "avsox.com",
    "avsox.host",
    "avbase.net",
    "prestige-av.com",
    "mgstage.com",
    "1pondo.tv",
    "10musume.com",
    "caribbeancom.com",
    "heyzo.com",
    "dmm.co.jp",
    "dmm.com",
    "r18.com",
    "fc2.com",
    "fc2cmadb.com",
    "iqqtv.cloud",
    "iqqtv.co",
    "airav.wiki",
    "airav.io",
    "javday.tv",
    "madouqu.com",
    "hdouban.com",
    "cableav.tv",
    "njav.tv",
    "porndb.net",
    "theporndb.net",
    "getchu.com",
    "xcity.jp",
    "kin8tengoku.com",
    "tokyo-hot.com",
    "amazon.co.jp",
    "google.com",  # 用于测速与出口 IP 检查
    "generate_204",
]

# 全局代理域名扩展（如果 mode = global，走这些域名 + 上面全部）
GLOBAL_PROXY_HINTS = ["geosite:geolocation-!cn"]


def build_xray_config(
    nodes: list[NodeConfig],
    *,
    socks_port: int = 18920,
    http_port: int = 18921,
    log_level: str = "warning",
    mode: str = "domain",  # domain / global / direct
    preferred_node_id: str | None = None,  # 手动选节点：锁定该节点走代理
) -> dict[str, Any]:
    """
    根据节点池生成 Xray 完整配置。

    mode:
      domain (默认): 只有 SCRAPE_PROXY_DOMAINS 走代理，其余走直连（推荐）
      global:       非 geosite:cn 全走代理（等同全局代理）
      direct:       完全直连，代理只作为出站备选（一般不用）
    """
    if not nodes:
        # 没节点：只起 inbound 但 outbounds 只有 direct
        outbounds = [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ]
        balancer_tag = None
    else:
        # 手动选节点：锁定单一 outbound，不走 balancer
        if preferred_node_id:
            pref = next((n for n in nodes if n.id == preferred_node_id), None)
        else:
            pref = None

        if pref is not None:
            node_outbounds = [pref.outbound]
            balancer_tag = None
        else:
            node_outbounds = [n.outbound for n in nodes]
            # 保证每个 outbound 有唯一 tag
            seen: dict[str, int] = {}
            for ob in node_outbounds:
                base = ob.get("tag", "node")
                if base in seen:
                    seen[base] += 1
                    ob["tag"] = f"{base}#{seen[base]}"
                else:
                    seen[base] = 0
            balancer_tag = "proxy_balancer"

        outbounds = [
            *node_outbounds,
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ]

    inbounds = [
        {
            "tag": "socks-in",
            "port": socks_port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True, "ip": "127.0.0.1"},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
        },
        {
            "tag": "http-in",
            "port": http_port,
            "listen": "127.0.0.1",
            "protocol": "http",
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
        },
    ]

    # ============ Routing ============
    rules: list[dict[str, Any]] = []

    # 私有地址、本地始终直连
    rules.append({
        "type": "field",
        "outboundTag": "direct",
        "ip": ["geoip:private"],
    })

    if mode == "direct":
        # 全直连
        pass
    elif mode == "global":
        # 中国 IP/域名直连
        rules.append({
            "type": "field",
            "outboundTag": "direct",
            "domain": ["geosite:cn"],
        })
        rules.append({
            "type": "field",
            "outboundTag": "direct",
            "ip": ["geoip:cn"],
        })
        # 其余走代理
        if balancer_tag:
            rules.append({
                "type": "field",
                "balancerTag": balancer_tag,
                "network": "tcp,udp",
            })
    else:
        # domain 模式：只对刮削域名走代理
        if balancer_tag:
            rules.append({
                "type": "field",
                "balancerTag": balancer_tag,
                "domain": [f"domain:{d}" if not d.startswith(("geosite:", "domain:", "regexp:", "keyword:")) else d
                           for d in SCRAPE_PROXY_DOMAINS],
            })
        elif node_outbounds:
            # 手动选了单节点：直接走该 outbound
            rules.append({
                "type": "field",
                "outboundTag": node_outbounds[0]["tag"],
                "domain": [f"domain:{d}" if not d.startswith(("geosite:", "domain:", "regexp:", "keyword:")) else d
                           for d in SCRAPE_PROXY_DOMAINS],
            })

    routing: dict[str, Any] = {
        "domainStrategy": "IPIfNonMatch",
        "rules": rules,
    }
    if balancer_tag:
        routing["balancers"] = [{
            "tag": balancer_tag,
            "selector": [ob["tag"] for ob in node_outbounds],
            "strategy": {"type": "leastPing"},
        }]

    config: dict[str, Any] = {
        "log": {"loglevel": log_level},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": routing,
    }

    # 若有节点，加 observatory 用于 leastPing 策略测速
    if balancer_tag and node_outbounds:
        config["observatory"] = {
            "subjectSelector": [ob["tag"] for ob in node_outbounds],
            "probeUrl": "https://www.google.com/generate_204",
            "probeInterval": "5m",
        }

    return config
