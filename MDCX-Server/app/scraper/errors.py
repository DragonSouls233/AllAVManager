"""刮削过程中的「可判定」异常类型。

## 为什么需要（2026-10-14）

`ScraperEngine._scrape_with_crawler` 对爬虫返回值只有两种处理：
拿到 `ScrapeResult` → 成功；拿到 `None` → **记一次源失败并喂给熔断器**。

这对 PH 是灾难性的：PH 库里约 **52% 的 pending 是死片**（实测抽样 60 部：
LIVE 48.3% / HTTP404 46.7% / "Video Disabled" 5.0%）。死片会被爬虫正确识别
并返回 `None`，但这个 `None` 与"源挂了"完全无法区分 ⇒

   刮 5 部死片 → 累计 5 次 not_found(PERMANENT) → 熔断器跳闸 30 分钟
   → 之后**每一部**（包括本来能刮到的活片）都被瞬间短路返回 None

这正是用户看到的"PORNHUB 刮削点了没效果"。根因不是慢、不是代理不够，
而是**死片把整个 PH 源熔断了**。

所以需要一种爬虫能主动上报"资源确认不存在"的信号，让 engine：
  · **不**把它记成源失败
  · **不**让它触发熔断
  · 把它单独传给上层，好把该片移出 pending 池（否则 4 轮重试全是白跑）
"""

from __future__ import annotations


class ResourceUnavailable(Exception):
    """源站**确认**该资源不存在 / 已下架 / 已删除，再重试也是同样结果。

    与「源故障」的区别（关键）：
      · 404 / 410 / "Video Disabled" / "此视频已被移除" → 本异常（源是健康的）
      · 超时 / 连接重置 / 403 拦截 / 5xx → **不是**本异常（源有问题，应重试）

    爬虫在**能确定**源站给出了"不存在"答复时才抛；拿不到响应（超时/网络错误）
    时**绝不能**抛，否则会把网络抖动误判成死片。
    """

    #: 供上层分类展示的细粒度标识
    kind: str = "unavailable"

    def __init__(self, message: str = "", *, kind: str = "unavailable") -> None:
        super().__init__(message or "资源不可用")
        self.kind = kind
