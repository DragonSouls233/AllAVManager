"""
图片下载和处理
"""

import asyncio
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from PIL import Image

from app.utils.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


class ImageProcessor:
    """
    图片处理器
    
    负责：
    - 下载封面/海报/剧照
    - 图片格式转换
    - 图片裁剪/缩放
    - 保存到本地
    """
    
    # 支持的图片格式
    SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    
    # 默认图片尺寸
    POSTER_SIZE = (400, 600)      # 海报尺寸
    FANART_SIZE = (1920, 1080)   # 背景图尺寸
    THUMB_SIZE = (400, 225)      # 缩略图尺寸
    ACTOR_SIZE = (200, 200)      # 演员头像尺寸

    # ============================================
    # srcset 高清封面解析(借鉴 JavSP avwiki.py:24-36)
    # ============================================

    @staticmethod
    def parse_srcset(srcset_attr: str) -> dict[int, str]:
        """解析 HTML img[srcset] 属性,返回 {宽度px: url} 映射

        借鉴 JavSP avwiki.py:24-32 的 srcset 解析逻辑。
        srcset 标准格式: "url1 800w, url2 1200w, url3 1600w"

        Args:
            srcset_attr: img 标签的 srcset 属性值

        Returns:
            {宽度: url} 字典,解析失败返回空 dict
        """
        if not srcset_attr:
            return {}
        result: dict[int, str] = {}
        try:
            for item in srcset_attr.split(", "):
                parts = item.strip().split()
                if len(parts) != 2:
                    continue
                url, width_desc = parts
                width = int(width_desc.rstrip("w"))
                result[width] = url
        except (ValueError, IndexError) as e:
            logger.debug(f"srcset 解析失败: {srcset_attr!r} - {e}")
        return result

    @staticmethod
    def pick_highest_res(srcset_attr: str, fallback_url: Optional[str] = None) -> Optional[str]:
        """从 srcset 中选取最高清的封面 URL

        借鉴 JavSP avwiki.py:33-36 的 max_pic 选取逻辑。
        若 srcset 解析失败,回退到 fallback_url(对应 JavSP 的 cover_tag.get('src'))。

        Args:
            srcset_attr: img[srcset] 属性值
            fallback_url: srcset 不可用时的回退 URL(通常是 img 的 src 属性)

        Returns:
            最高清封面 URL,均不可用时返回 None
        """
        src_map = ImageProcessor.parse_srcset(srcset_attr)
        if src_map:
            # 按宽度降序取第一个(最高清)
            return sorted(src_map.items(), key=lambda x: x[0], reverse=True)[0][1]
        return fallback_url

    def __init__(
        self,
        output_dir: str,
        max_concurrent: int = 5,
        timeout: int = 30,
    ):
        """
        初始化图片处理器
        
        Args:
            output_dir: 输出目录
            max_concurrent: 最大并发下载数
            timeout: 下载超时时间（秒）
        """
        self.output_dir = Path(output_dir)
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client: Optional[AsyncHttpClient] = None
    
    async def __aenter__(self) -> "ImageProcessor":
        """上下文管理器入口"""
        self._client = AsyncHttpClient(timeout=self.timeout)
        await self._client.init_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """上下文管理器退出"""
        if self._client:
            await self._client.close_session()
    
    async def download_image(
        self,
        url: str,
        save_path: str,
        referer: Optional[str] = None,
    ) -> Optional[str]:
        """
        下载图片
        
        Args:
            url: 图片URL
            save_path: 保存路径
            referer: Referer头
            
        Returns:
            保存的文件路径，失败返回 None
        """
        if not self._client:
            raise RuntimeError("ImageProcessor not initialized")
        
        async with self._semaphore:
            try:
                headers = {}
                if referer:
                    headers["Referer"] = referer
                
                response = await self._client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.warning(f"Download failed: {url} (status={response.status_code})")
                    return None
                
                # 确保目录存在
                save_path = Path(save_path)
                save_path.parent.mkdir(parents=True, exist_ok=True)
                
                # 保存图片
                with open(save_path, "wb") as f:
                    f.write(response.content)
                
                logger.debug(f"Downloaded: {url} -> {save_path}")
                return str(save_path)
            
            except Exception as e:
                logger.error(f"Download error: {url} - {e}")
                return None
    
    async def download_and_process(
        self,
        url: str,
        save_path: str,
        size: Optional[tuple[int, int]] = None,
        crop: bool = False,
        referer: Optional[str] = None,
    ) -> Optional[str]:
        """
        下载并处理图片
        
        Args:
            url: 图片URL
            save_path: 保存路径
            size: 目标尺寸（宽，高）
            crop: 是否裁剪到目标尺寸
            referer: Referer头
            
        Returns:
            保存的文件路径
        """
        if not self._client:
            raise RuntimeError("ImageProcessor not initialized")
        
        async with self._semaphore:
            try:
                headers = {}
                if referer:
                    headers["Referer"] = referer
                
                response = await self._client.get(url, headers=headers)
                
                if response.status_code != 200:
                    return None
                
                # 打开图片
                image = Image.open(BytesIO(response.content))
                
                # 转换为 RGB（去除 alpha 通道）
                if image.mode in ("RGBA", "P"):
                    image = image.convert("RGB")
                
                # 调整尺寸
                if size:
                    if crop:
                        image = self._crop_to_size(image, size)
                    else:
                        image = self._resize_to_size(image, size)
                
                # 保存
                save_path = Path(save_path)
                save_path.parent.mkdir(parents=True, exist_ok=True)
                
                image.save(save_path, "JPEG", quality=90)
                
                return str(save_path)
            
            except Exception as e:
                logger.error(f"Process error: {url} - {e}")
                return None
    
    def _resize_to_size(self, image: Image.Image, size: tuple[int, int]) -> Image.Image:
        """
        等比缩放图片到目标尺寸内
        """
        width, height = size
        img_width, img_height = image.size
        
        # 计算缩放比例
        ratio = min(width / img_width, height / img_height)
        new_size = (int(img_width * ratio), int(img_height * ratio))
        
        return image.resize(new_size, Image.Resampling.LANCZOS)
    
    def _crop_to_size(self, image: Image.Image, size: tuple[int, int]) -> Image.Image:
        """
        裁剪图片到精确尺寸（居中裁剪）
        """
        target_width, target_height = size
        img_width, img_height = image.size
        
        # 计算裁剪区域
        ratio = max(target_width / img_width, target_height / img_height)
        new_width = int(img_width * ratio)
        new_height = int(img_height * ratio)
        
        # 先缩放
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # 居中裁剪
        left = (new_width - target_width) // 2
        top = (new_height - target_height) // 2
        right = left + target_width
        bottom = top + target_height
        
        return image.crop((left, top, right, bottom))
    
    async def download_cover(
        self,
        url: str,
        movie_dir: str,
        filename: str = "poster.jpg",
        referer: Optional[str] = None,
    ) -> Optional[str]:
        """
        下载封面图
        
        Args:
            url: 封面URL
            movie_dir: 电影目录
            filename: 文件名
            referer: Referer头
            
        Returns:
            保存的文件路径
        """
        save_path = Path(movie_dir) / filename
        return await self.download_image(url, str(save_path), referer)
    
    async def download_fanart(
        self,
        url: str,
        movie_dir: str,
        filename: str = "fanart.jpg",
        referer: Optional[str] = None,
    ) -> Optional[str]:
        """
        下载背景图
        
        Args:
            url: 图片URL
            movie_dir: 电影目录
            filename: 文件名
            referer: Referer头
            
        Returns:
            保存的文件路径
        """
        save_path = Path(movie_dir) / filename
        return await self.download_image(url, str(save_path), referer)
    
    async def download_samples(
        self,
        urls: list[str],
        movie_dir: str,
        subdir: str = "extrafanart",
        referer: Optional[str] = None,
    ) -> list[str]:
        """
        下载样图
        
        Args:
            urls: 图片URL列表
            movie_dir: 电影目录
            subdir: 子目录名
            referer: Referer头
            
        Returns:
            成功下载的文件路径列表
        """
        if not urls:
            return []
        
        sample_dir = Path(movie_dir) / subdir
        sample_dir.mkdir(parents=True, exist_ok=True)
        
        results = []
        
        for i, url in enumerate(urls):
            # 获取扩展名
            ext = self._get_ext(url) or ".jpg"
            filename = f"{i+1:02d}{ext}"
            save_path = sample_dir / filename
            
            result = await self.download_image(url, str(save_path), referer)
            if result:
                results.append(result)
        
        return results
    
    async def download_actor_avatar(
        self,
        url: str,
        actor_dir: str,
        actor_name: str,
        referer: Optional[str] = None,
    ) -> Optional[str]:
        """
        下载演员头像
        
        Args:
            url: 头像URL
            actor_dir: 演员目录
            actor_name: 演员名
            referer: Referer头
            
        Returns:
            保存的文件路径
        """
        actor_dir = Path(actor_dir)
        actor_dir.mkdir(parents=True, exist_ok=True)
        
        # 清理文件名
        safe_name = self._sanitize_filename(actor_name)
        save_path = actor_dir / f"{safe_name}.jpg"
        
        return await self.download_and_process(
            url,
            str(save_path),
            size=self.ACTOR_SIZE,
            crop=True,
            referer=referer,
        )
    
    def _get_ext(self, url: str) -> Optional[str]:
        """从URL获取扩展名"""
        path = urlparse(url).path
        ext = os.path.splitext(path)[1].lower()
        return ext if ext in self.SUPPORTED_FORMATS else None
    
    def _sanitize_filename(self, name: str) -> str:
        """清理文件名"""
        # 移除非法字符
        illegal_chars = '<>:"/\\|?*'
        for char in illegal_chars:
            name = name.replace(char, "")
        return name.strip()


async def download_movie_images(
    cover_url: Optional[str],
    sample_urls: list[str],
    movie_dir: str,
    referer: Optional[str] = None,
) -> dict[str, any]:
    """
    下载电影图片的便捷函数
    
    Args:
        cover_url: 封面URL
        sample_urls: 样图URL列表
        movie_dir: 电影目录
        referer: Referer头
        
    Returns:
        下载结果
    """
    result = {
        "poster": None,
        "fanart": None,
        "samples": [],
    }
    
    async with ImageProcessor(movie_dir) as processor:
        # 下载封面
        if cover_url:
            result["poster"] = await processor.download_cover(
                cover_url, movie_dir, referer=referer
            )
            # 封面也用作背景图
            if result["poster"]:
                result["fanart"] = await processor.download_fanart(
                    cover_url, movie_dir, referer=referer
                )
        
        # 下载样图
        if sample_urls:
            result["samples"] = await processor.download_samples(
                sample_urls, movie_dir, referer=referer
            )
    
    return result
