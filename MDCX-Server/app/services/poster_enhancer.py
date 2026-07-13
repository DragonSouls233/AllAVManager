"""海报增强服务

- 4K/8K 高清海报下载（Amazon Japan 源）
- 水印引擎（基于 Pillow）
- 支持马赛克/无码/中字/4K/8K/字幕/流出 等标签水印

参考 app/services/face_crop.py 的图片处理风格：
- Pillow 处理图片
- httpx 异步下载
- 同步 Pillow 操作通过 asyncio.to_thread 包装
"""

import asyncio
import io
import logging
import os
from typing import Optional

import httpx
from PIL import Image, ImageDraw, ImageFont

from app.config.manager import get_config

logger = logging.getLogger(__name__)


class PosterEnhancerService:
    """海报增强服务"""

    # 水印标签映射
    WATERMARK_LABELS = {
        "mosaic": "马赛克",
        "uncensored": "无码",
        "chinese_sub": "中字",
        "4k": "4K",
        "8k": "8K",
        "subtitle": "字幕",
        "leaked": "流出",
    }

    # 水印位置（相对偏移；负值表示从右/下边算起）
    WATERMARK_POSITIONS = {
        "top-left": (10, 10),
        "top-right": (-10, 10),
        "bottom-left": (10, -10),
        "bottom-right": (-10, -10),
        "center": (0, 0),
    }

    # Amazon Japan 高清封面候选模板（可用番号替换 {code}）
    AMAZON_JP_TEMPLATES = [
        "https://m.media-amazon.com/images/I/{code}._AC_UL320_.jpg",
        "https://images-na.ssl-images-amazon.com/images/I/{code}._SL1000_.jpg",
    ]

    async def enhance_poster(
        self,
        movie_id: int,
        poster_url: str,
        movie_type: str = "",
        enable_watermark: bool = True,
        watermark_position: str = "bottom-right",
        session=None,
    ) -> str:
        """增强海报：下载高清 + 添加水印

        Args:
            movie_id: 影片 ID
            poster_url: 原始海报 URL（失败时原样返回）
            movie_type: 影片类型标签，逗号分隔（mosaic/uncensored/chinese_sub/...）
            enable_watermark: 是否添加水印
            watermark_position: 水印位置
            session: 可选数据库会话

        Returns:
            增强后海报的本地路径；失败时返回原始 poster_url
        """
        config = get_config()

        try:
            # 1. 下载海报（优先 Amazon Japan 高清源）
            image_data = await self._download_poster(poster_url, movie_id)
            if not image_data:
                logger.warning(f"海报下载失败: movie_id={movie_id}")
                return poster_url

            # 2. 同步 Pillow 处理放到线程中执行，避免阻塞事件循环
            output_path = self._get_output_path(movie_id)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._process_image_sync,
                image_data,
                movie_type,
                enable_watermark,
                watermark_position,
                config,
                output_path,
            )

            if result:
                logger.info(f"海报增强完成: movie_id={movie_id}, path={output_path}")
                return output_path
            else:
                logger.warning(f"海报增强 Pillow 处理失败: movie_id={movie_id}")
                return poster_url

        except Exception as e:
            logger.error(f"海报增强失败: movie_id={movie_id}, {e}", exc_info=True)
            return poster_url

    def _process_image_sync(
        self,
        image_data: bytes,
        movie_type: str,
        enable_watermark: bool,
        watermark_position: str,
        config,
        output_path: str,
    ) -> bool:
        """同步处理图片：打开 → 4K 超分（可选） → 加水印 → 保存"""
        try:
            img = Image.open(io.BytesIO(image_data))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            # 3. 可选：4K 超分辨率（简化版：仅放大）
            if config.poster_enhancer.enable_4k_upscale and img.size[0] < 2000:
                img = img.resize((img.size[0] * 2, img.size[1] * 2), Image.LANCZOS)

            # 4. 添加水印
            if enable_watermark and movie_type:
                img = self._add_watermark(img, movie_type, watermark_position, config)

            # 5. 保存增强后海报
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            if img.mode == "RGBA":
                img = img.convert("RGB")
            img.save(output_path, "JPEG", quality=95)
            return True
        except Exception as e:
            logger.error(f"Pillow 处理失败: {e}", exc_info=True)
            return False

    async def _download_poster(self, url: str, movie_id: int) -> Optional[bytes]:
        """下载海报图片

        若启用 Amazon Japan 源且原 URL 看似 Amazon 风格，将尝试更高质量的变体；
        失败时回退到原 URL。
        """
        config = get_config()

        # 启用 Amazon Japan 源时，先尝试高清变体
        candidates = []
        if config.poster_enhancer.amazon_japan_source:
            candidates.extend(self._derive_amazon_hq_urls(url))
        candidates.append(url)

        for candidate in candidates:
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    resp = await client.get(candidate)
                    if resp.status_code != 200 or not resp.content:
                        continue
                    # 简单校验：content-type 以 image/ 开头，或为 PNG/JPEG 魔数
                    content_type = resp.headers.get("content-type", "").lower()
                    is_png = resp.content[:8].startswith(b"\x89PNG")
                    is_jpeg = resp.content[:3] == b"\xff\xd8\xff"
                    if not (content_type.startswith("image/") or is_png or is_jpeg):
                        continue
                    logger.debug(f"海报下载成功: {candidate} (size={len(resp.content)})")
                    return resp.content
            except Exception as e:
                logger.warning(f"海报下载失败: {candidate}, {e}")
                continue
        return None

    def _derive_amazon_hq_urls(self, url: str) -> list[str]:
        """从 Amazon 图片 URL 派生更高质量的变体

        Amazon 图片 URL 形如：
        https://m.media-amazon.com/images/I/ABC123._AC_UL320_.jpg
        可替换后缀为 ._SL1000_ 或 ._SL1500_ 获取更清晰版本。
        """
        if "amazon" not in url:
            return []
        out = []
        for high_suffix in ("._SL1500_.jpg", "._SL1000_.jpg"):
            # 替换最后一段 _*.jpg 后缀
            import re
            new_url = re.sub(r"\._[^.]+_\.jpg$", high_suffix, url)
            if new_url != url:
                out.append(new_url)
        return out

    def _add_watermark(
        self,
        img: Image.Image,
        movie_type: str,
        position: str,
        config,
    ) -> Image.Image:
        """添加水印标签

        步骤：
        1. 解析 movie_type → 中文标签列表
        2. 在 RGBA 叠加层上绘制半透明背景 + 文字
        3. 与原图 alpha_composite 后转回 RGB
        """
        # 获取水印文本
        labels = []
        for t in movie_type.split(","):
            t = t.strip()
            if not t:
                continue
            if t in self.WATERMARK_LABELS:
                labels.append(self.WATERMARK_LABELS[t])
            else:
                labels.append(t)

        if not labels:
            return img

        watermark_text = " | ".join(labels)

        # 转 RGBA 以支持 alpha 合成
        base = img.convert("RGBA")
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 加载字体
        font_size = config.poster_enhancer.watermark_font_size
        font = self._load_font(font_size)

        # 计算文本尺寸
        text_bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]

        # 计算位置
        pos = self.WATERMARK_POSITIONS.get(position, self.WATERMARK_POSITIONS["bottom-right"])
        if position == "center":
            x = (base.width - text_w) // 2
            y = (base.height - text_h) // 2
        else:
            x = pos[0] if pos[0] >= 0 else base.width + pos[0] - text_w
            y = pos[1] if pos[1] >= 0 else base.height + pos[1] - text_h
            # 确保非负
            x = max(0, x)
            y = max(0, y)

        # 绘制半透明背景
        margin = 8
        bg_alpha = int(180 * config.poster_enhancer.watermark_opacity)
        draw.rectangle(
            [x - margin, y - margin, x + text_w + margin, y + text_h + margin],
            fill=(0, 0, 0, bg_alpha),
        )

        # 绘制文字
        text_color = self._hex_to_rgba(
            config.poster_enhancer.watermark_color,
            config.poster_enhancer.watermark_opacity,
        )
        draw.text((x, y), watermark_text, font=font, fill=text_color)

        # alpha 合成
        composited = Image.alpha_composite(base, overlay)
        return composited.convert("RGB")

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont:
        """加载字体

        优先级：
        - 微软雅黑（中文支持）
        - Arial（西文）
        - DejaVu（Linux 兜底）
        - Pillow 默认（最后兜底）
        """
        font_paths = [
            "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
            "C:/Windows/Fonts/arial.ttf",     # Arial
            "C:/Windows/Fonts/simhei.ttf",    # 黑体
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def _hex_to_rgba(self, hex_color: str, opacity: float = 1.0):
        """hex 转 RGBA"""
        hex_color = hex_color.lstrip("#")
        if len(hex_color) != 6:
            hex_color = "FFFFFF"
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return (r, g, b, int(255 * opacity))

    def _get_output_path(self, movie_id: int) -> str:
        """获取输出路径"""
        config = get_config()
        data_dir = config.computed.data_dir
        return os.path.join(str(data_dir), "posters", "enhanced", f"{movie_id}_poster.jpg")

    async def batch_enhance(
        self,
        movie_ids: list[int],
        session=None,
    ) -> dict:
        """批量增强海报

        Args:
            movie_ids: 影片 ID 列表
            session: 数据库会话（必须由调用方传入）

        Returns:
            统计结果 {success, failed, skipped}
        """
        results = {"success": 0, "failed": 0, "skipped": 0}

        if session is None:
            logger.error("batch_enhance 需要传入数据库 session")
            return results

        from app.db.models import Movie

        for movie_id in movie_ids:
            try:
                movie = await session.get(Movie, movie_id)
                if not movie or not movie.poster_url:
                    results["skipped"] += 1
                    continue

                movie_type = self._derive_movie_type(movie)

                enhanced_path = await self.enhance_poster(
                    movie_id,
                    movie.poster_url,
                    ",".join(movie_type),
                    session=session,
                )

                if enhanced_path != movie.poster_url:
                    movie.poster_url = enhanced_path
                    await session.commit()
                    results["success"] += 1
                else:
                    results["skipped"] += 1

            except Exception as e:
                logger.error(f"批量增强 movie_id={movie_id} 失败: {e}", exc_info=True)
                results["failed"] += 1

        return results

    def _derive_movie_type(self, movie) -> list[str]:
        """从影片字段派生水印标签列表"""
        movie_type = []
        if getattr(movie, "is_mosaic", None):
            movie_type.append("mosaic")
        if getattr(movie, "is_uncensored", None):
            movie_type.append("uncensored")
        if getattr(movie, "is_chinese", None):
            movie_type.append("chinese_sub")
        return movie_type


# 全局单例
poster_enhancer_service = PosterEnhancerService()
