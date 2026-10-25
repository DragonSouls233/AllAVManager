"""
Xray 配置生成器

根据节点池 + 内置分流规则生成 xray -c config.json。

设计：
- inbound: socks5 + http（同端口不同 tag）
- outbounds: 每个节点一个 + direct + block
- routing: 目标域名匹配 → 走对应节点 balancer
- 分流规则内置刮削常用站点，用户零配置

2026-10-20 增强（自动更换节点 + 日本节点分流）：
- 节点按 ``country`` 分池（用户 2026-10-20 要求「所有非中国节点都用上，不要局限美/日」）：
  * DMM 系等**日本地域硬锁**站点 → ``jp_balancer``（仅日本出口节点，池内 leastPing 自动切换）
  * 其余全部刮削源 → ``global_balancer``（**所有非中国节点**，含日本节点，池内 leastPing 自动切换）
  * 中国（CN）节点被 ``EXCLUDED_COUNTRIES`` 显式排除，不进任何 balancer。
- 每个节点额外生成一个**探测专用 socks inbound**，供 ProxyManager 经该节点出口访问
  ip-api 自动探测出口国家（见 app/services/proxy_manager._country_probe_loop）。
- observatory 探测间隔缩短到 1m，死节点更快被 balancer 剔除（自动更换节点）。
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
    # 🔴 PH 封面 / 缩略图 / 样图 CDN：刮削拿到的 cover_url / sample_images 全在这个域下
    #    （ei.phncdn.com、pix-cdn77.phncdn.com、pict.pix-cdn77.phncdn.com …）。
    #    crawler 的 base_url 只声明 pornhub.com 主站，注册中心派生不出 CDN 子域，
    #    必须手写。漏掉→ domain 模式下这些请求直连国内出口 → PH CDN 在海外 →
    #    超时失败（日志里一堆 "ei.phncdn.com ... 重试失败，降级 httpx 再试"）。
    #    2026-10-15 实测：批量刮削封面下载全 WARNING，加此条后改走代理。
    "phncdn.com",
    "google.com",  # 用于测速与出口 IP 检查
    "generate_204",
    # 🔴 磁力搜索源（wants_resources / aggregate_searcher 的 sukebei 源）：
    #    nyaa.si 主站与 sukebei 子站同域，两者都列（nyaa.si 镜像会跳主站）。
    #    2026-10-25 开发机实测直连 200，但服务器是国内出口，domain 模式下
    #    清单外域名一律直连 → 漏配就静默超时（本清单的历史坑，见上方注释），
    #    宁可走代理。加这两条后无论用户有没有配 xray 都能搜。
    "sukebei.nyaa.si",
    "nyaa.si",
]

# ============================================================
# 必须走「日本出口」的站点（见 build_xray_config 的 jp_balancer）。
# 判据：这些站点按地域硬封锁，只有日本 IP 能访问，非日本出口一律 403/地区重定向。
#   - DMM 系（dmm.co.jp / dmm.com / r18.com）是硬性地城锁；用户 2026-10-20 明确
#     「之前专门提取日本节点只是为了 DMM」，所以只列 DMM 系。
# 🔴 不要把 javdb / javbus / javlibrary / 1pondo / heyzo / mgstage 等普通日本源放进来：
#    它们从任意非中国出口都能访问（用户要求「所有节点只要能访问刮削都用上，不要局限
#    美/日」）。把它们塞进 jp_balancer 会把这些源限制成只有日本节点能刮，白白浪费其它
#    可用节点。若实测某个源确实按日本 IP 封锁，再把它加进本列表（并在注释写实测证据）。
# ============================================================
JP_ONLY_DOMAINS = [
    "dmm.co.jp",
    "dmm.com",
    "r18.com",
]

# ============================================================
# 排除国家：来自这些国家的节点不进任何 balancer（连不上海外刮削源，选中也白选）。
# 判据：中国大陆出口 IP 访问 DMM/javbus/pornhub 等会被目标站按地区拦截，leastPing
#     探 google 也大概率超时 → 会被 observatory 健康检查自然剔除；这里显式排除是
#     双保险，也避免「国家还没探测出来」的窗口期误选中国节点。
# country 为 None（尚未探测）的节点一律视为可用，探测完成后由
# proxy_manager._country_probe_loop 重建配置再决定去留。
# ============================================================
EXCLUDED_COUNTRIES = frozenset({"CN"})

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
    """把裸域名补成 Xray 规则串；已是规则串（geosite:/domain:/regexp:/keyword:/…）则原样返回。

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
    jp_country: str = "JP",  # 视为「日本出口」的 country 码（ISO-3166 alpha-2）
    probe_ports: dict[str, int] | None = None,  # node.id -> 探测专用 socks 端口
) -> dict[str, Any]:
    """
    根据节点池生成 Xray 完整配置。

    mode:
      domain (默认): 只对刮削域名走代理，其余走直连（推荐）
      global:       非 geosite:cn 全走代理（等同全局代理）
      direct:       完全直连，代理只作为出站备选（一般不用）

    国家分流（2026-10-20 新增，用户要求「所有非中国节点都用上」）：
      - 节点按 ``country``（ISO-3166 alpha-2）分池；``EXCLUDED_COUNTRIES``（默认 CN）的节点
        不进任何 balancer（连不上海外刮削源）。country 为 None（未探测）暂视为可用。
      - 未手动锁节点时：
        * 若存在日本节点 → 生成 ``jp_balancer``（仅日本节点）+ ``global_balancer``（所有非中国节点）；
          DMM 系（JP_ONLY_DOMAINS，日本地域硬锁）→ jp_balancer，其余全部刮削源 → global_balancer。
        * 若无日本节点 → 退化为单一 ``global_balancer``（所有非中国节点），行为与旧版一致。
        * 若所有节点都被排除（如全是中国节点）→ 不起 balancer，刮削域直连（避免引用不存在的 balancer）。
      - 手动锁节点（preferred_node_id）→ 锁定单 outbound，不走 balancer（手动优先）。
    """
    jp_country = (jp_country or "JP").upper()
    probe_ports = probe_ports or {}

    # 全部节点 outbound（去重 tag）+ node.id -> tag 映射
    all_obs: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    node_id_to_tag: dict[str, str] = {}
    tag_to_node: dict[str, NodeConfig] = {}
    for n in nodes:
        ob = dict(n.outbound)  # 浅拷贝，避免改原对象
        base = ob.get("tag", "node")
        if base in seen:
            seen[base] += 1
            ob["tag"] = f"{base}#{seen[base]}"
        else:
            seen[base] = 0
        all_obs.append(ob)
        node_id_to_tag[n.id] = ob["tag"]
        tag_to_node[ob["tag"]] = n

    jp_balancer_tag: str | None = None
    global_balancer_tag: str | None = None
    node_outbounds: list[dict[str, Any]] = []

    if not nodes:
        # 没节点：只起 inbound 但 outbounds 只有 direct
        outbounds = [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ]
    else:
        # 手动选节点：锁定单一 outbound，不走 balancer
        if preferred_node_id:
            pref = next((n for n in nodes if n.id == preferred_node_id), None)
        else:
            pref = None

        if pref is not None:
            pref_ob = dict(pref.outbound)
            pref_ob["tag"] = f"{pref_ob.get('tag', 'node')}#sel"
            node_id_to_tag[pref.id] = pref_ob["tag"]
            node_outbounds = [pref_ob]
        else:
            # 可用节点 = 非排除国家（country 为 None 视为可用，探测后再定夺）
            usable_obs = [
                ob for ob in all_obs
                if (tag_to_node[ob["tag"]].country or "").upper() not in EXCLUDED_COUNTRIES
            ]
            jp_tags = [
                ob["tag"] for ob in usable_obs
                if (tag_to_node[ob["tag"]].country or "").upper() == jp_country
            ]
            if jp_tags:
                # 有日本节点：双 balancer —— jp 仅日本节点（DMM 系地域硬锁）；
                # global = 所有非中国节点（含日本节点，用户要求节点最大化利用）。
                # jp_tags ⊆ usable_obs，故日本节点存在时可用集必非空，global_balancer 必然启用。
                jp_balancer_tag = "jp_balancer"
                global_balancer_tag = "global_balancer"
            elif usable_obs:
                # 无日本节点：退化为单一全局 balancer（所有非中国节点，与旧版一致）
                global_balancer_tag = "global_balancer"
            # else: 全部节点被排除（如全是中国节点）→ 不起 balancer，刮削域直连（见 routing）
            node_outbounds = all_obs

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

    # 探测专用 inbound：每个节点一个，供 ProxyManager 经该节点出口探测出口国家
    for n in nodes:
        p = probe_ports.get(n.id)
        if not p:
            continue
        inbounds.append({
            "tag": f"probe-{n.id}",
            "port": p,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True, "ip": "127.0.0.1"},
        })

    # ============ Routing ============
    rules: list[dict[str, Any]] = []

    # 私有地址、本地始终直连
    rules.append({
        "type": "field",
        "outboundTag": "direct",
        "ip": ["geoip:private"],
    })

    # 探测路由：每个探测 inbound 强制走对应节点 outbound（必须放在最前，优先级最高）
    for n in nodes:
        p = probe_ports.get(n.id)
        if not p:
            continue
        tag = node_id_to_tag.get(n.id)
        if not tag:
            continue
        rules.append({
            "type": "field",
            "inboundTag": f"probe-{n.id}",
            "outboundTag": tag,
        })

    proxy_domains_all = resolve_proxy_rules()
    jp_rule_domains = [_as_rule(d) for d in JP_ONLY_DOMAINS if d not in DIRECT_EXCEPTIONS]
    jp_set = set(jp_rule_domains)
    global_rule_domains = [d for d in proxy_domains_all if d not in jp_set]

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
        if global_balancer_tag:
            rules.append({
                "type": "field",
                "balancerTag": global_balancer_tag,
                "network": "tcp,udp",
            })
        else:
            # 无可用节点（全被排除/空池）→ 其余全部直连，不引用可能不存在的 balancer，
            # 也不用 node_outbounds[0] 兜底（全是中国节点时那正是连不上海外的出口）。
            rules.append({
                "type": "field",
                "outboundTag": "direct",
                "network": "tcp,udp",
            })
    else:
        # domain 模式：只对刮削域名走代理
        if preferred_node_id and node_outbounds:
            # 手动锁单节点：直接走该 outbound
            rules.append({
                "type": "field",
                "outboundTag": node_outbounds[0]["tag"],
                "domain": proxy_domains_all,
            })
        elif jp_balancer_tag:
            # DMM 系（日本地域硬锁）→ 仅日本节点；其余全部刮削源 → 全局池（所有非中国节点）。
            # 注：jp_balancer_tag 存在 ⟹ 可用集非空（日本节点本身可用）⟹ global_balancer_tag 必存在，
            # 所以这里无需处理「只有日本池」的分支。
            rules.append({
                "type": "field",
                "balancerTag": jp_balancer_tag,
                "domain": jp_rule_domains,
            })
            rules.append({
                "type": "field",
                "balancerTag": global_balancer_tag,
                "domain": global_rule_domains,
            })
        elif global_balancer_tag:
            # 单一全局 balancer（无日本节点，退化为旧版）
            rules.append({
                "type": "field",
                "balancerTag": global_balancer_tag,
                "domain": proxy_domains_all,
            })
        else:
            # 无任何可用节点（全被排除/空池）→ 刮削域直连，避免引用不存在的 balancer 致 xray 起不来
            rules.append({
                "type": "field",
                "outboundTag": "direct",
                "domain": proxy_domains_all,
            })

    routing: dict[str, Any] = {
        "domainStrategy": "IPIfNonMatch",
        "rules": rules,
    }

    balancers: list[dict[str, Any]] = []
    if jp_balancer_tag:
        jp_sel = [
            ob["tag"] for ob in all_obs
            if (tag_to_node[ob["tag"]].country or "").upper() == jp_country
        ]
        balancers.append({
            "tag": jp_balancer_tag,
            "selector": jp_sel,
            "strategy": {"type": "leastPing"},
        })
    if global_balancer_tag:
        # 全局池 = 所有非排除国家节点（含日本节点；排除 CN 等连不上海外源的出口）
        usable_sel = [
            ob["tag"] for ob in all_obs
            if (tag_to_node[ob["tag"]].country or "").upper() not in EXCLUDED_COUNTRIES
        ]
        balancers.append({
            "tag": global_balancer_tag,
            "selector": usable_sel,
            "strategy": {"type": "leastPing"},
        })
    if balancers:
        routing["balancers"] = balancers

    config: dict[str, Any] = {
        "log": {"loglevel": log_level},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": routing,
    }

    # 若有 balancer，加 observatory 用于 leastPing 策略测速 + 死节点自动剔除
    if balancers:
        config["observatory"] = {
            "subjectSelector": [ob["tag"] for ob in all_obs],
            "probeUrl": "https://www.google.com/generate_204",
            # 🔴 2026-10-20：从 5m 缩短到 1m，让 balancer 更快感知节点死亡/恢复
            # （节点挂了自动切换到健康节点 = 「自动更换节点」的核心机制）。
            "probeInterval": "1m",
        }

    return config
