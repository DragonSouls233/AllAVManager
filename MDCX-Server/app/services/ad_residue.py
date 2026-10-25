"""推广残留清理：判定媒体目录里的广告插页，以及安全的回收站。

学 peach `web_batch` 的判定思路（判据源自其 2026-09 真实用户实例校准），
适配 MDCX：peach 比对的是「账本 vs 盘」，MDCX 没有账本，直接扫媒体目录树，
按名字形态 + 体积 + 目录上下文打分。

三条设计红线（从 peach 的实测教训直接搬）：
1. **剥完套话还剩内容的文件不是广告**：广告名写得越长反而越安全——
   手游插页 `爱姬远征-免费18禁手游-扫码安装.jpg` 剥完套话还剩 12 字，
   落在中间档，够不上清理门槛。所以 filler 词只参与残留计算，不作命中依据。
2. **成套资源目录里的域名名不是广告**：`bbsxv.xyz-DOCP-324` 躺在 107 项的
   目录里，那是打包渠道给整包起的名；同目录 ≥ BUNDLE_DIR_ASSETS 项时
   域名不计分。广告插页反过来——一两张挤在别人的番号目录里。
3. **大文件自己就是内容**：> CONTENT_BYTES 的视频不判广告（资源站给自己的
   资源改了目录名，不是塞进来的推广）。整包插页加起来都不到 10MB。

删除安全：判定只出报告；清理 = 移入回收站（同卷 rename，manifest 记录
原路径可恢复）；永久删除才硬删且要显式确认。原路径不硬删是这个模块
和 UnrecognizedFiles 既有「删除孤立文件」（send2trash 之外的直接 os.remove）
最大的区别——那个找不回来，这个能反悔。
"""

import asyncio
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.config.manager import get_config
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------- 判定词表
# 只认联系方式与站点形态的推广套话。「微信」「成人游戏」单独出现不算——
# 正片标题里就有（剧情需要）。
PROMO_PHRASE = re.compile(
    r"(扫码|扫一扫|掃一掃|扫描|掃描|QR ?CODE|二维码|二維碼|加微信|加微|威信\d|微信号|"
    r"微信\s*[:：]|免费看|免费玩|福利群|最新地址|"
    r"永久(?:域名|地址|发布)|地址发布器|防屏蔽|资源获取|点击(?:观看|下载|进入)|下载APP|"
    r"签到|代币|领取|"
    r"强力推荐|国产大片|在线视频|線上影片每天火熱更新|手机看片|手機影城|"
    r"大饱眼福|房间火爆|澳门|赌场|博彩|棋牌|加我|"
    r"GAMES?\d*)", re.I)

# 只降低残留、自己不构成命中的套话（手游插页整批绕过硬判据就靠它拉低分数）。
PROMO_FILLER = re.compile(
    r"(免费\d*禁|免费|免費|18禁|手游|手遊|成人遊?戲|成人游戏|下载安装|安装|安裝|访问|訪問)", re.I)

# 域名形态。结尾不能用 \b：`uuc82.com_2` 里 `m` 和 `_` 都是词字符。
PROMO_DOMAIN = re.compile(
    r"(?:https?://)?(?:www\.)?[\w-]{2,}\.(?:com|net|me|la|xyz|cc|tv|top|vip|club|"
    r"info|org|pw|cn|app|site|online|shop)(?![a-z0-9])", re.I)

# 推广站目录的两种形态。裸域名目录（98T.la@账号）是转载水印，不是广告。
AD_DIRPACK = re.compile(
    r"[0-9a-z][-0-9a-z]{1,20}\.[a-z]{2,10}[ \-_]+\[?[A-Za-z]{2,6}-?\d{2,5}", re.I)

# 推广品牌词。单独出现在视频名里不构成证据——只有叠加形态词才计分。
AD_BRAND = re.compile(
    r"(91(?:短视频|视频|国产|AV|約炮|约炮)|成人抖音|快手直播|杏吧|草榴|色中色|成人头条|"
    r"泡芙短视频|含羞草|她趣|台湾UU|全国外围|外围楼凤|楼凤|麻豆传媒映画|蜜桃影像|"
    r"成人游戏|169BBS|SEX169)", re.I)

# 与品牌词同现才算推广名的形态词。
AD_BRAND_FORM = re.compile(
    r"(APP|一键|导航|聊天室|免费体验|限时免费|扫码|资源获取|网址|发布页)", re.I)

# 目录名自曝是推广包的形态：`-APP`、`一键约炮`、`論壇文宣`、聊天室等。
AD_DIR_FORM = re.compile(
    r"(論壇文宣|论坛文宣|文宣|宣傳|一键约炮|全国外围|外围楼凤|楼凤|聊天室|"
    r"免费体验|限时免费)", re.I)
# `APP` 按词匹配：`Happy` 里也藏着 `app`，裸子串会把正常目录卷进来。
AD_DIR_APP = re.compile(r"(?:^|[^A-Za-z.])APP(?:[^A-Za-z.]|$)", re.I)
# 品牌名只在目录里还带媒体平台词时才算推广目录；`麻豆传媒` 单独出现可能是厂牌资源目录。
AD_DIR_BRAND_MEDIA = re.compile(
    r"(?:视频|視頻|影视|影視|传媒|傳媒|直播|短视频|短視頻)", re.I)

# 装饰符：挂两个以上才算装饰性命名（单个爱心常见于正常标题）。
DECOR_MARKS = "❤♥❥♡💕💗💖💘💝"

# 保存下来的网页/导航页。媒体目录里的这些没有内容价值。
NAV_SUFFIXES = frozenset({".url"})
PAGE_ARCHIVE_SUFFIXES = frozenset({".mhtml", ".mht", ".htm", ".html"})

# 真番号形态（与 scraper.number.is_jav_code 同源的简化版）：
# 带厂牌前缀和连字号（ABW-153、259LUXU-1141）。没有连字号的是账号名。
REAL_CODE = re.compile(r"^(?:\d{2,3})?[A-Za-z]{2,8}-\d{2,5}$|^FC2", re.I)

# 封面/截图相对正片的固定尾巴（`MIAD573_02_s.jpg` ↔ `MIAD573_02.wmv`）。
SHOT_TAIL = re.compile(r"[-_. ]?(?:s|t|pl|ps|thumb|poster|cover|fanart|big|small)$", re.I)

# 超过这个体积的视频文件自己就是内容，不必再看名字。
CONTENT_BYTES = 1024 ** 3

# 装饰图体积上限（同名配套封面 2MB 级走正片配对豁免，不算）。
DECORATED_MAX_BYTES = 1536 * 1024

# 品牌推广图的体积上限。品牌名 + 这种体积才是广告卡。
BRAND_TINY_BYTES = 300 * 1024

# 视频小于这个体积记一条「只够复核」的弱证据（原「小于 120 MB」）。
JUNK_VIDEO_MAX_BYTES = 120 * 1024 * 1024

# 同一目录里有这么多资产，它就是成套下载的资源包（域名名是打包渠道起的）。
BUNDLE_DIR_ASSETS = 20

# 同一目录里有这么多同类推广名，它们就是成群塞进来的插页。
PROMO_CLUSTER_FILES = 3

# 分数线（与 peach 同名同值）
AUTO_TRASH_SCORE = 60    # ≥60 自动隔离线（junk，建议清理）
JUNK_REVIEW_SCORE = 40   # ≥40 进复核队列（review，人工确认）

# 视频扩展名
VIDEO_SUFFIXES = frozenset({
    ".mp4", ".mkv", ".avi", ".wmv", ".flv", ".mov", ".m4v",
    ".rm", ".rmvb", ".mpg", ".mpeg", ".ts", ".m2ts", ".webm", ".iso",
})
IMAGE_SUFFIXES = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff",
})

# 扫描上限（防爆内存/时间）
SCAN_MAX_ENTRIES = 200_000
SCAN_MAX_DEPTH = 6
SCAN_TIMEOUT_SEC = 300

TRASH_DIRNAME = ".mdcx-trash"


# ---------------------------------------------------------------- 数据结构
@dataclass
class ResidueItem:
    """一条推广残留候选"""
    path: str
    filename: str
    size: int
    score: int
    reasons: list = field(default_factory=list)
    action: str = "kept"        # junk / review / kept
    dir_assets: int = 0         # 同目录资产数（成套判定用）

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "filename": self.filename,
            "size": self.size,
            "score": self.score,
            "reasons": self.reasons,
            "action": self.action,
            "dir_assets": self.dir_assets,
        }


# ---------------------------------------------------------------- 评分核心
#: 剥掉域名和推广套话后还剩多少实质描述字符。
#: 这是区分「广告」与「正片被打了站点水印」的关键：
#: `点击观看 房间火爆` 剥完什么都不剩；
#: `236953.xyz 推特新晋4年绿帽美腿淫妻网黄「一个ren」…` 剥完仍有大段内容描述。
#: 🔴 剥掉的词替换成空串而不是空格：空格自己也在计数字符集里，
#: 换成空格等于每剥一个词就补回一个残留（peach 原注释，实测踩过）。
_RESIDUE_CHARS = re.compile(r"[一-鿿぀-ヿ가-힯 A-Za-z]")


def promo_residue(name: str) -> int:
    """剥掉域名/推广套话/filler 后的实质描述字符数。"""
    text = PROMO_DOMAIN.sub("", name or "")
    text = PROMO_PHRASE.sub("", text)
    text = PROMO_FILLER.sub("", text)
    return len(_RESIDUE_CHARS.findall(text))


def is_decorated_name(stem: str) -> bool:
    """名字挂着两个以上装饰符，没有任何实质描述。

    只挂一个爱心不算：Telegram 导出与正常标题里单个爱心常见。
    """
    return sum(str(stem or "").count(m) for m in DECOR_MARKS) >= 2


def has_sibling_original(stem: str, sibling_videos: set) -> bool:
    """同目录里有一条与它同名的正片（它是那条正片的封面/截图）。"""
    key = str(stem or "").casefold()
    if not key:
        return False
    return key in sibling_videos or SHOT_TAIL.sub("", key) in sibling_videos


def is_promo_directory(parts) -> bool:
    """路径里有任意一层目录自曝是推广包。

    三种形态：`APP` 词形（`_含羞草APP`）、促销目录名（`一键约炮`、`論壇文宣`）、
    品牌名叠加媒体词（`_草榴视频`）。只看目录分量，文件名自己是不是推广由调用方判。
    """
    for part in parts:
        text = str(part)
        if AD_DIR_APP.search(text) or AD_DIR_FORM.search(text):
            return True
        if AD_BRAND.search(text) and AD_DIR_BRAND_MEDIA.search(text):
            return True
    return False


def _score_file(
    path: Path,
    size: int,
    dir_assets: int,
    promo_neighbours: int,
    sibling_videos: set,
) -> tuple[int, list]:
    """给单文件打分（对齐 peach `_scored_junk` 主干，去掉账本依赖）。

    MDCX 没有账本，用文件系统近似：
    - medium 按后缀推（video/image/other）
    - code 用 REAL_CODE 判 stem（自曝真番号 → 非视频豁免）
    - duration 不探测（视频的时长证据没有，只留体积与目录弱证据，仅够复核）

    Returns:
        (分数, 理由列表)
    """
    name = path.name
    stem = path.stem
    suffix = path.suffix.lower()
    parent_parts = path.parent.parts

    is_video = suffix in VIDEO_SUFFIXES
    is_image = suffix in IMAGE_SUFFIXES
    is_nav = suffix in NAV_SUFFIXES
    is_page_archive = suffix in PAGE_ARCHIVE_SUFFIXES

    residue = promo_residue(stem)
    promo = bool(PROMO_PHRASE.search(stem) or PROMO_DOMAIN.search(stem))
    bundled = dir_assets >= BUNDLE_DIR_ASSETS

    # 自曝证据：非视频且（自己是真番号 / 内容级体积 / 同目录正片的配套图）
    self_evident = (not is_video) and (
        bool(REAL_CODE.match(stem))
        or size >= CONTENT_BYTES
        or has_sibling_original(stem, sibling_videos)
    )
    decorated = ((not is_video) and is_decorated_name(stem)
                 and size <= DECORATED_MAX_BYTES)
    brand_hit = bool(AD_BRAND.search(stem)) and (
        bool(AD_BRAND_FORM.search(stem))
        or (is_image and size <= BRAND_TINY_BYTES)
    )
    promo_dir = is_promo_directory(parent_parts)

    s = 0
    why: list = []
    # 只够进复核队列的分数（目录/体积证据说明不了它是广告）
    review_only = 0

    # 1) 导航页/网页存档：媒体目录里直接进人工复核（+60）
    if is_nav:
        s += 60
        why.append("网址快捷方式（.url）")
    elif is_page_archive:
        s += 60
        why.append("网页存档（保存下来的推广页）")

    # 2) 核心名字判据（成套资源包豁免：域名是打包渠道给整包起的名）
    if promo and residue < 6 and not bundled:
        # 名字剥完只剩广告本身，这是最硬的信号
        s += 60
        why.append("整个名字都是推广语")
    elif promo and residue < 14 and not bundled:
        s += 30
        why.append("推广语占了名字主体")
        if promo_neighbours >= PROMO_CLUSTER_FILES:
            s += 30
            why.append(f"同目录另有 {promo_neighbours - 1} 个同类推广名")

    # 3) 目录是「域名+番号」的推广打包（自曝文件除外）
    if AD_DIRPACK.search(str(path.parent.name)) and not self_evident:
        s += 45
        why.append("目录是「域名+番号」的推广打包")

    # 4) 非视频的推广形态：装饰符小图 / 品牌推广名 / 住在推广目录
    if (not is_video) and not self_evident and not is_page_archive and not is_nav:
        if decorated:
            s += 60
            why.append("装饰符小图（多装饰符+无实质描述）")
        elif brand_hit:
            s += 60
            why.append("推广品牌名")
        elif promo_dir:
            s += 50
            why.append("住在推广目录")

    # 5) 视频证据（不探测时长：只留体积与目录弱证据，仅够复核）
    if is_video:
        if size < JUNK_VIDEO_MAX_BYTES:
            s += 10
            review_only += 10
            why.append("小于 120MB")
        if promo_dir:
            s += 30
            review_only += 30
            why.append("住在推广目录")

    # 6) 大文件兜底：>1GB 的视频自己就是内容（资源站给自己的资源改了名）
    if is_video and size > CONTENT_BYTES:
        return 0, []

    # 7) review_only 软上限：只够复核的分数撑不到 60 就压到 59
    if review_only and s - review_only < AUTO_TRASH_SCORE:
        s = min(s, AUTO_TRASH_SCORE - 1)

    return s, why


def _dir_asset_count(dir_path: Path) -> int:
    """同目录资产数（文件数，用于成套判定）。出错返回 0（不豁免）。"""
    try:
        with os.scandir(dir_path) as it:
            return sum(1 for e in it if e.is_file())
    except OSError:
        return 0


def _scan_tree_sync(root: Path, items: list, counters: dict,
                    deadline: Optional[float] = None) -> None:
    """同步遍历目录树（在线程里跑）。只读名字+stat，不打开文件。

    deadline: monotonic  deadline，超了就停止下钻（软超时）。
    🔴 只能保证「再也不进新目录」：单个卡死的 os.scandir（掉线 NAS 的典型
    表现）没法从 Python 侧打断，遇到时该次请求仍会挂到系统返回。
    """
    stack = [(root, 0)]
    while stack:
        if deadline is not None and time.monotonic() > deadline:
            counters["timed_out"] = True
            return
        current, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError as e:
            counters["errors"] += 1
            counters.setdefault("error_dirs", []).append(
                {"dir": str(current), "error": f"{type(e).__name__}: {e}"})
            continue
        for entry in entries:
            counters["scanned"] += 1
            if counters["scanned"] > SCAN_MAX_ENTRIES:
                return
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth < SCAN_MAX_DEPTH:
                        stack.append((Path(entry.path), depth + 1))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                p = Path(entry.path)
                # 跳过我们自己的回收站
                if TRASH_DIRNAME in p.parts:
                    continue
                size = entry.stat(follow_symlinks=False).st_size
                items.append((p, size))
            except OSError:
                counters["errors"] += 1


class AdResidueService:
    """推广残留判定 + 回收站"""

    # ------------------------------------------------------------ 扫描
    @staticmethod
    def _dedupe_roots(roots: list[Path]) -> list[Path]:
        """去掉重复与互相嵌套的根（media_dirs 里 Z:\\ 和 Z:\\Movies 同时配了，
        不判重同一批文件会进两次结果，用户批清时第二次全报「文件不存在」）。
        """
        kept: list[tuple[str, Path]] = []   # [(规范化绝对路径, 原 Path)]
        for r in roots:
            try:
                cur = os.path.normcase(os.path.abspath(str(r))).rstrip(os.sep)
            except Exception:
                kept.append((str(r), r))
                continue
            if any(cur == k or cur.startswith(k + os.sep) for k, _ in kept):
                continue                      # 已被某个更上层的根覆盖
            kept = [(k, p) for k, p in kept if not k.startswith(cur + os.sep)]
            kept.append((cur, r))
        return [p for _, p in kept]

    async def scan(
        self,
        directories: Optional[list[str]] = None,
    ) -> dict:
        """扫描媒体目录，产出推广残留候选（只读，不动任何文件）。

        Returns:
            {"junk": [...], "review": [...], "summary": {...}}
        """
        if directories is None:
            directories = get_config().scraper.media_dirs or []
        directories = [d for d in directories if d and str(d).strip()]
        if not directories:
            return {"junk": [], "review": [],
                    "summary": {"error": "未配置媒体目录（scraper.media_dirs）"}}

        t0 = time.monotonic()
        deadline = t0 + SCAN_TIMEOUT_SEC
        raw_items: list = []
        counters = {"scanned": 0, "errors": 0}
        roots = self._dedupe_roots([Path(d) for d in directories])
        for root in roots:
            if not root.is_dir():
                counters.setdefault("error_dirs", []).append(
                    {"dir": str(root), "error": "目录不存在或不可读"})
                continue
            await asyncio.to_thread(_scan_tree_sync, root, raw_items, counters, deadline)

        # 目录上下文：按父目录分组
        dir_counts: dict = {}        # 每目录资产数（成套判定）
        dir_videos: dict = {}        # 每目录视频 stem 集合（封面/截图豁免）
        promo_neighbours: dict = {}  # 每目录同类推广名计数（成群插页判定）
        for p, size in raw_items:
            parent = str(p.parent)
            dir_counts[parent] = dir_counts.get(parent, 0) + 1
            if p.suffix.lower() in VIDEO_SUFFIXES:
                dir_videos.setdefault(parent, set()).add(p.stem.casefold())
            # 邻居成群：命中推广词且剥完残留 <14 的才算「同类推广名」
            if PROMO_PHRASE.search(p.stem) or PROMO_DOMAIN.search(p.stem):
                if promo_residue(p.stem) < 14:
                    promo_neighbours[parent] = promo_neighbours.get(parent, 0) + 1

        junk: list = []
        review: list = []
        junk_bytes = 0
        review_bytes = 0
        for p, size in raw_items:
            parent = str(p.parent)
            score, reasons = _score_file(
                p, size,
                dir_assets=dir_counts.get(parent, 0),
                promo_neighbours=promo_neighbours.get(parent, 0),
                sibling_videos=dir_videos.get(parent, set()),
            )
            if score < JUNK_REVIEW_SCORE:
                continue
            action = "junk" if score >= AUTO_TRASH_SCORE else "review"
            item = ResidueItem(
                path=str(p), filename=p.name, size=size, score=score,
                reasons=reasons, action=action, dir_assets=dir_counts.get(parent, 0),
            )
            if action == "junk":
                junk_bytes += size
                junk.append(item.to_dict())
            else:
                review_bytes += size
                review.append(item.to_dict())

        junk.sort(key=lambda x: -x["score"])
        review.sort(key=lambda x: -x["score"])
        elapsed = time.monotonic() - t0
        summary = {
            "scanned_dirs": [str(r) for r in roots],
            "scanned_entries": counters["scanned"],
            "scan_errors": counters["errors"],
            "error_dirs": counters.get("error_dirs", [])[:20],
            "junk_count": len(junk),
            "review_count": len(review),
            "junk_bytes": junk_bytes,
            "review_bytes": review_bytes,
            "candidate_bytes": junk_bytes + review_bytes,
            "timed_out": bool(counters.get("timed_out")),
            "elapsed_sec": round(elapsed, 1),
            "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        logger.info(
            f"[ad_residue] 扫描完成: {counters['scanned']} 项 → "
            f"junk {len(junk)} / review {len(review)}，{elapsed:.1f}s")
        return {"junk": junk, "review": review, "summary": summary}

    # ------------------------------------------------------------ 回收站
    def _trash_root(self) -> Path:
        """回收站根目录：第一媒体目录/.mdcx-trash；跨卷场景退回数据目录。"""
        dirs = get_config().scraper.media_dirs or []
        for d in dirs:
            if d and Path(d).is_dir():
                return Path(d) / TRASH_DIRNAME
        # 兜底：数据目录
        from app.config.manager import get_config_manager
        try:
            base = Path(get_config_manager().computed.data_dir)
        except Exception:
            base = Path("data")
        return base / TRASH_DIRNAME

    async def move_to_trash(self, paths: list[str]) -> dict:
        """移入回收站：同卷 rename 到 .mdcx-trash/日期/，写 manifest。

        同卷 rename 是原子操作且不留副本；跨卷（媒体目录在不同盘）时
        rename 会失败，退回 shutil.move（移动，仍不是复制+删除两条路）。
        返回每条的成功/失败，单个失败不影响其他条目。
        """
        paths = [p for p in paths if p and str(p).strip()]
        if not paths:
            return {"status": "error", "message": "路径列表为空"}
        stamp = time.strftime("%Y%m%d-%H%M%S")
        trash_dir = self._trash_root() / stamp
        results = []
        ok_count = 0
        trash_dir.mkdir(parents=True, exist_ok=True)
        for raw in paths:
            src = Path(raw.strip())
            entry = {"path": str(src), "ok": False, "trash_path": "", "error": ""}
            try:
                if not src.is_file():
                    entry["error"] = "文件不存在（可能已被移走）"
                    results.append(entry)
                    continue
                # 防呆：拒绝把回收站自己的文件再入站
                if TRASH_DIRNAME in src.parts:
                    entry["error"] = "回收站内的文件不能再次入站"
                    results.append(entry)
                    continue
                # 重名加序号
                dst = trash_dir / src.name
                n = 1
                while dst.exists():
                    dst = trash_dir / f"{src.stem}.dup{n}{src.suffix}"
                    n += 1
                try:
                    os.rename(str(src), str(dst))
                except OSError:
                    # 跨卷：退回移动
                    shutil.move(str(src), str(dst))
                entry["ok"] = True
                entry["trash_path"] = str(dst)
                ok_count += 1
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {e}"
            results.append(entry)
        # manifest（原路径 → 回收站路径，恢复用；无新增条目则不写）
        if ok_count:
            manifest = trash_dir / "manifest.json"
            try:
                data = []
                if manifest.is_file():
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                data.extend([{"original": r["path"], "trashed": r["trash_path"],
                              "at": time.strftime("%Y-%m-%d %H:%M:%S")}
                             for r in results if r["ok"]])
                manifest.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
            except Exception as e:
                logger.warning(f"[ad_residue] manifest 写入失败: {e}")
        logger.info(f"[ad_residue] 移入回收站 {ok_count}/{len(paths)} → {trash_dir}")
        return {"status": "ok" if ok_count else "error",
                "moved": ok_count, "total": len(paths),
                "results": results, "trash_dir": str(trash_dir)}

    async def list_trash(self) -> dict:
        """回收站列表：读所有 manifest，按批次分组。"""
        trash_root = self._trash_root()
        batches: list = []
        total_size = 0
        if trash_root.is_dir():
            for batch_dir in sorted(trash_root.iterdir()):
                manifest = batch_dir / "manifest.json"
                if not manifest.is_file():
                    continue
                try:
                    entries = json.loads(manifest.read_text(encoding="utf-8"))
                except Exception:
                    continue
                items = []
                for e in entries:
                    tp = e.get("trashed", "")
                    size = 0
                    exists = Path(tp).is_file()
                    if exists:
                        try:
                            size = Path(tp).stat().st_size
                        except OSError:
                            pass
                    total_size += size
                    items.append({
                        "original": e.get("original", ""),
                        "trashed": tp,
                        "at": e.get("at", ""),
                        "size": size,
                        "exists": exists,
                    })
                batches.append({
                    "batch": batch_dir.name,
                    "items": items,
                    "count": len(items),
                    "size": sum(i["size"] for i in items),
                })
        return {"batches": batches, "total_size": total_size,
                "trash_dir": str(trash_root)}

    async def restore_from_trash(self, trashed_paths: list[str]) -> dict:
        """从回收站恢复：按 manifest 里的 original 路径还回原位。"""
        if not trashed_paths:
            return {"status": "error", "message": "路径列表为空"}
        trash_root = self._trash_root()
        # 建 original → trashed 索引
        index: dict = {}
        if trash_root.is_dir():
            for manifest in trash_root.glob("*/manifest.json"):
                try:
                    for e in json.loads(manifest.read_text(encoding="utf-8")):
                        if e.get("trashed"):
                            index[e["trashed"]] = e.get("original", "")
                except Exception:
                    continue
        results = []
        ok_count = 0
        for raw in trashed_paths:
            tp = str(raw).strip()
            entry = {"trashed": tp, "ok": False, "restored": "", "error": ""}
            try:
                original = index.get(tp, "")
                src = Path(tp)
                if not src.is_file():
                    entry["error"] = "回收站里已没有这个文件"
                    results.append(entry)
                    continue
                if not original:
                    entry["error"] = "manifest 里找不到原路径，无法自动还回"
                    results.append(entry)
                    continue
                dst = Path(original)
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    entry["error"] = "原位置已有同名文件，未覆盖（请先手动处理）"
                    results.append(entry)
                    continue
                try:
                    os.rename(str(src), str(dst))
                except OSError:
                    shutil.move(str(src), str(dst))
                entry["ok"] = True
                entry["restored"] = str(dst)
                ok_count += 1
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {e}"
            results.append(entry)
        # 清理已空批次的 manifest 记录（恢复成功的从 manifest 移除）
        if ok_count:
            self._prune_manifest(trash_root, {r["trashed"] for r in results if r["ok"]})
        return {"status": "ok" if ok_count else "error",
                "restored": ok_count, "total": len(trashed_paths),
                "results": results}

    def _prune_manifest(self, trash_root: Path, restored: set) -> None:
        """把恢复成功的条目从 manifest 移除，空批次连目录一起清。"""
        for manifest in trash_root.glob("*/manifest.json"):
            try:
                entries = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception:
                continue
            left = [e for e in entries if e.get("trashed") not in restored]
            try:
                if left:
                    manifest.write_text(json.dumps(left, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
                else:
                    manifest.unlink()
                    # 批次目录里除了 manifest 没别的就删目录
                    batch_dir = manifest.parent
                    if not any(batch_dir.iterdir()):
                        batch_dir.rmdir()
            except Exception as e:
                logger.warning(f"[ad_residue] manifest 清理失败 {manifest}: {e}")

    async def purge_trash(self, trashed_paths: list[str]) -> dict:
        """永久删除回收站里的文件（硬删，不可恢复）。"""
        if not trashed_paths:
            return {"status": "error", "message": "路径列表为空"}
        trash_root = self._trash_root()
        results = []
        ok_count = 0
        for raw in trashed_paths:
            tp = str(raw).strip()
            entry = {"trashed": tp, "ok": False, "error": ""}
            try:
                # 防呆：只允许删回收站内的路径
                if TRASH_DIRNAME not in Path(tp).parts:
                    entry["error"] = "拒绝删除回收站外的路径"
                    results.append(entry)
                    continue
                src = Path(tp)
                if not src.is_file():
                    entry["error"] = "文件已不在"
                    results.append(entry)
                    continue
                src.unlink()
                entry["ok"] = True
                ok_count += 1
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {e}"
            results.append(entry)
        if ok_count:
            self._prune_manifest(trash_root, {r["trashed"] for r in results if r["ok"]})
        return {"status": "ok" if ok_count else "error",
                "purged": ok_count, "total": len(trashed_paths),
                "results": results}


ad_residue_service = AdResidueService()

__all__ = ["ad_residue_service", "AdResidueService", "ResidueItem"]
