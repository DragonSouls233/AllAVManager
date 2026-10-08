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

import logging
from typing import Any

from app.services.proxy_parser import NodeConfig

logger = logging.getLogger(__name__)

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
    "pornhub.com",
    "cn.pornhub.com",
    "google.com",  # 用于测速与出口 IP 检查
    "generate_204",
]

# 全局代理域名扩展（如果 mode = global，走这些域名 + 上面全部）
GLOBAL_PROXY_HINTS = ["geosite:geolocation-!cn"]

# ============================================================
# 直连例外：这些域名**只有国内出口可达**，走代理反而会被目标站按境外 IP 拒绝
# ============================================================
# 判据要写在注释里，别凭感觉加：
#   cn.myjav.tv —— 域名本身即表明是 CN 镜像站，境外 IP 访问会被拒
DIRECT_EXCEPTIONS = frozenset({
    "cn.myjav.tv",
})


def _registered_crawler_domains() -> set[str]:
    """从 crawler 注册中心派生需要代理的域名。

    存在的理由（2026-10-08 实测）：
        ``SCRAPE_PROXY_DOMAINS`` 是手写清单，而它是 domain 模式下**唯一**决定
        "谁走代理"的东西 —— 清单外的域名一律直连。实测已生成的
        data/proxy/xray_config.json 里只有 39 条域名规则，而 89 个已注册
        crawler 中有 53 个声明的 base_url 域名不在清单内（javmenu.com /
        javmost.ws / jav.place / javdatabase.com / freejavbt.com / avmoo.shop /
        jav.sb 等，全部在主力/辅助源序里）。结果是这些源在 domain 模式下
        **静默直连**，在国内出口表现为超时而非报错，很难排查。

    改为从注册中心派生后：新增 crawler 再也不会漏配代理。

    懒导入说明（重要）：
        本模块被 ``proxy_manager`` 在模块级 import，而 crawler 侧又依赖
        proxy_manager。若在模块级 import app.crawlers 会形成循环导入，
        因此这里放在函数内懒导入；失败时返回空集合，由调用方退回手写清单。
    """
    try:
        from urllib.parse import urlparse

        from app.crawlers import list_crawlers
    except Exception:  # pragma: no cover - 注册中心不可用时不应阻断配置生成
        logger.debug("注册中心不可用，跳过 crawler 域名派生", exc_info=True)
        return set()

    hosts: set[str] = set()
    try:
        for info in list_crawlers():
            raw = (getattr(info, "base_url", "") or "").strip()
            if not raw:
                continue
            if "://" not in raw:
                raw = "https://" + raw
            host = urlparse(raw).hostname
            if not host:
                continue
            host = host.lower()
            if host.startswith("www."):
                host = host[4:]
            # 必须是像样的域名（排除 IP、占位符、单标签）
            if "." not in host or host.replace(".", "").isdigit():
                continue
            hosts.add(host)
    except Exception:  # pragma: no cover
        logger.warning("派生 crawler 代理域名失败，退回手写清单", exc_info=True)
        return set()

    return hosts


def _as_rule(d: str) -> str:
    """把裸域名补成 Xray 规则串；已是规则串（geosite:/domain:/keyword:/…）则原样返回。

    🔴 不能简单地给所有条目都加 ``domain:`` 前缀：ref201 的补充规则里有
    ``keyword:jav`` 这类子串规则，被改成 ``domain:jav`` 就退化成"匹配名为 jav
    的域名及其子域"，等于规则失效。
    """
    if d.startswith(("geosite:", "domain:", "regexp:", "keyword:", "full:")):
        return d
    return f"domain:{d}"


def resolve_proxy_rules() -> list[str]:
    """最终生效的代理规则（已带 Xray 前缀，可直接进 routing.rules[].domain）。

    组成：手写清单 ∪ crawler 注册中心派生 ∪ ref201 NSFW 补充 − 直连例外。

    手写清单保留的价值：镜像域名、CDN，以及 crawler 运行时才动态拿到的域
    （如 javbus 镜像轮换）无法从 base_url 派生，仍需人工维护。
    """
    merged: set[str] = set()

    for d in SCRAPE_PROXY_DOMAINS:
        if d not in DIRECT_EXCEPTIONS:
            merged.add(_as_rule(d))

    for d in _registered_crawler_domains():
        if d not in DIRECT_EXCEPTIONS:
            merged.add(_as_rule(d))

    try:
        from app.services.nsfw_domains import nsfw_rules

        for r in nsfw_rules():
            val = r.split(":", 1)[1] if ":" in r else r
            if val in DIRECT_EXCEPTIONS:
                continue
            merged.add(r)
    except Exception:  # pragma: no cover
        logger.debug("NSFW 补充规则不可用，忽略", exc_info=True)

    return sorted(merged)


def resolve_proxy_domains() -> list[str]:
    """裸域名集合（诊断 / 测试用）。

    只含 ``domain:`` 精确规则，不含 ``keyword:`` 子串规则 —— 后者不是域名，
    拿来做"某 crawler 域名是否被覆盖"的判断会误判。
    """
    return sorted(r.split(":", 1)[1] for r in resolve_proxy_rules() if r.startswith("domain:"))


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
    # 🔴 必须预先初始化：无节点时下面的 else 分支不会赋值它，
    #    而 domain 模式末尾要读 `elif node_outbounds:` —— 未初始化会抛
    #    UnboundLocalError，导致「没配节点时启动代理直接崩溃」
    #    （proxy_manager._build_config() 无条件调用本函数）。
    node_outbounds: list[dict[str, Any]] = []

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

    # 代理规则：手写 ∪ crawler 注册中心派生 ∪ ref201 NSFW 补充（已带前缀）
    proxy_domains = resolve_proxy_rules()

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
                "domain": proxy_domains,
            })
        elif node_outbounds:
            # 手动选了单节点：直接走该 outbound
            rules.append({
                "type": "field",
                "outboundTag": node_outbounds[0]["tag"],
                "domain": proxy_domains,
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
