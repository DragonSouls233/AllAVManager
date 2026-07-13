"""封面水印与裁剪工具

参考 VaultX (watermark.py) + AVDC + JavSP (Slimeface) 的设计：
- 水印工具：文字水印（中文字幕/流出/无码/自定义）+ 图片水印（Logo）
- 裁剪工具：多种裁剪模式（右侧1/3 / 左侧1/3 / 居中 / 人脸检测 / 自定义）
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 水印预设
WATERMARK_PRESETS = {
    "sub": {"text": "中文字幕", "color": (255, 255, 255), "bg": (0, 0, 0)},
    "leak": {"text": "流出", "color": (255, 0, 0), "bg": (255, 255, 255)},
    "uncensored": {"text": "无码", "color": (255, 255, 0), "bg": (0, 0, 0)},
    "chinese": {"text": "国产", "color": (255, 255, 255), "bg": (200, 0, 0)},
    "fc2": {"text": "FC2", "color": (255, 255, 255), "bg": (128, 0, 128)},
    "custom": {"text": "自定义", "color": (255, 255, 255), "bg": (0, 0, 0)},
}

WATERMARK_POSITIONS = ["top_left", "top_right", "bottom_left", "bottom_right"]

CROP_MODES = {
    "right_half": "右侧1/3裁剪",
    "left_half": "左侧1/3裁剪",
    "center": "居中裁剪",
    "face_detect": "人脸检测裁剪",
    "custom": "自定义区域",
}


@dataclass
class WatermarkResult:
    """水印添加结果"""
    success: bool = False
    output_path: str = ""
    error: Optional[str] = None


@dataclass
class CropResult:
    """裁剪结果"""
    success: bool = False
    output_path: str = ""
    mode: str = ""
    error: Optional[str] = None


class WatermarkTool:
    """封面水印添加工具

    支持文字水印和图片水印两种模式。
    """

    def __init__(self, font_size: int = 24, padding: int = 10):
        self.font_size = font_size
        self.padding = padding

    def add_watermark(
        self,
        image_path: str,
        output_path: str,
        marks: list[str],
        position: str = "bottom_right",
        font_size: Optional[int] = None,
    ) -> WatermarkResult:
        """在封面上添加文字水印

        Args:
            image_path: 输入图片路径
            output_path: 输出图片路径
            marks: 水印类型列表，如 ['sub', 'uncensored']
            position: 水印位置 top_left/top_right/bottom_left/bottom_right
            font_size: 字体大小

        Returns:
            WatermarkResult
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return WatermarkResult(success=False, error="缺少 Pillow 库")

        if not os.path.isfile(image_path):
            return WatermarkResult(success=False, error=f"文件不存在: {image_path}")

        try:
            img = Image.open(image_path).convert("RGBA")
            fs = font_size or self.font_size

            for i, mark_key in enumerate(marks):
                preset = WATERMARK_PRESETS.get(mark_key, WATERMARK_PRESETS["custom"])
                text = preset["text"]
                text_color = preset["color"]
                bg_color = preset["bg"]

                pos = self._get_position(image_path, position, i, len(marks), fs)
                self._draw_text(img, text, pos, fs, text_color, bg_color)

            out_dir = os.path.dirname(output_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)

            # 保持原格式
            ext = os.path.splitext(output_path)[1].lower()
            if ext == ".png":
                img.save(output_path, "PNG")
            else:
                img = img.convert("RGB")
                img.save(output_path, "JPEG", quality=95)

            logger.info(f"水印添加成功: {output_path}")
            return WatermarkResult(success=True, output_path=output_path)

        except Exception as e:
            logger.error(f"水印添加失败: {e}")
            return WatermarkResult(success=False, error=str(e))

    def _get_position(self, image_path: str, base_pos: str, index: int, total: int, font_size: int) -> tuple[int, int]:
        """计算水印位置（多水印时顺时针分布）"""
        from PIL import Image
        img = Image.open(image_path)
        w, h = img.size

        positions = ["bottom_right", "bottom_left", "top_right", "top_left"]
        pos = positions[index % 4] if total > 1 else base_pos

        if pos == "top_left":
            return (self.padding, self.padding)
        elif pos == "top_right":
            return (w - 200, self.padding)
        elif pos == "bottom_left":
            return (self.padding, h - 40)
        else:
            return (w - 200, h - 40)

    def _draw_text(self, img, text: str, pos: tuple[int, int], font_size: int,
                   text_color: tuple[int, int, int], bg_color: tuple[int, int, int]):
        """在图片上绘制文字水印"""
        from PIL import ImageDraw, ImageFont

        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pad = 4

        x, y = pos
        draw.rectangle(
            [x, y, x + tw + pad * 2, y + th + pad * 2],
            fill=(*bg_color, 200),
        )
        draw.text((x + pad, y + pad - 2), text, font=font, fill=(*text_color, 255))

    def batch_add_watermark(
        self,
        files: list[dict],
        marks: list[str],
        position: str = "bottom_right",
    ) -> dict:
        """批量添加水印"""
        success = 0
        failed = 0
        errors = []

        for item in files:
            result = self.add_watermark(
                image_path=item["source_path"],
                output_path=item.get("output_path", item["source_path"]),
                marks=marks,
                position=position,
            )
            if result.success:
                success += 1
            else:
                failed += 1
                errors.append({"file": item["source_path"], "error": result.error})

        return {"success": success, "failed": failed, "total": len(files), "errors": errors}


class ImageCropper:
    """封面裁剪工具"""

    def __init__(self):
        pass

    def crop(
        self,
        image_path: str,
        output_path: str,
        mode: str = "center",
        custom_box: Optional[tuple[int, int, int, int]] = None,
    ) -> CropResult:
        """裁剪封面图片

        Args:
            image_path: 输入图片路径
            output_path: 输出图片路径
            mode: 裁剪模式 center / right_half / left_half / face_detect / custom
            custom_box: 自定义区域 (left, top, right, bottom)

        Returns:
            CropResult
        """
        try:
            from PIL import Image
        except ImportError:
            return CropResult(success=False, error="缺少 Pillow 库")

        if not os.path.isfile(image_path):
            return CropResult(success=False, error=f"文件不存在: {image_path}")

        try:
            img = Image.open(image_path)
            w, h = img.size
            box = None

            if mode == "center":
                # 居中裁剪：取中间 2/3
                crop_w = int(w * 0.67)
                crop_h = int(h * 0.67)
                left = (w - crop_w) // 2
                top = (h - crop_h) // 2
                box = (left, top, left + crop_w, top + crop_h)

            elif mode == "right_half":
                # 右侧 1/3（最常见的人像封面在右侧）
                crop_w = w // 2
                box = (w - crop_w, 0, w, h)

            elif mode == "left_half":
                # 左侧 1/3
                crop_w = w // 2
                box = (0, 0, crop_w, h)

            elif mode == "face_detect":
                box = self._face_detect_crop(img)

            elif mode == "custom" and custom_box:
                box = custom_box

            if not box:
                return CropResult(success=False, error=f"无效的裁剪模式: {mode}")

            cropped = img.crop(box)
            cropped = cropped.resize((int(w * 0.5), int(h * 0.5)), Image.Resampling.LANCZOS)

            out_dir = os.path.dirname(output_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)

            ext = os.path.splitext(output_path)[1].lower()
            if ext == ".png":
                cropped.save(output_path, "PNG")
            else:
                cropped.save(output_path, "JPEG", quality=95)

            logger.info(f"裁剪成功 [{mode}]: {output_path}")
            return CropResult(success=True, output_path=output_path, mode=mode)

        except Exception as e:
            logger.error(f"裁剪失败 [{mode}]: {e}")
            return CropResult(success=False, error=str(e), mode=mode)

    def _face_detect_crop(self, img) -> Optional[tuple[int, int, int, int]]:
        """人脸检测裁剪

        使用 OpenCV Haar Cascade 检测人脸，然后以人脸为中心裁剪。
        如果检测失败，回退到右侧 1/3 裁剪。
        """
        w, h = img.size

        try:
            import cv2
            import numpy as np

            cv_img = np.array(img.convert("RGB"))
            gray = cv2.cvtColor(cv_img, cv2.COLOR_RGB2GRAY)

            face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            faces = face_cascade.detectMultiScale(gray, 1.1, 3, minSize=(30, 30))

            if len(faces) > 0:
                # 取最大的人脸
                face = max(faces, key=lambda f: f[2] * f[3])
                fx, fy, fw, fh = face
                center_x = fx + fw // 2
                center_y = fy + fh // 2

                # 以人脸为中心裁剪宽高比 2:3
                crop_w = int(h * 0.5)
                crop_h = h

                left = max(0, center_x - crop_w // 2)
                right = min(w, left + crop_w)
                if right - left < crop_w:
                    left = max(0, right - crop_w)

                logger.debug(f"人脸检测成功: {len(faces)} 个人脸, 裁剪区域 ({left}, 0, {right}, {h})")
                return (left, 0, right, h)

        except ImportError:
            logger.debug("OpenCV 未安装，回退到右侧裁剪")
        except Exception as e:
            logger.debug(f"人脸检测失败: {e}")

        # 回退：右侧 1/3
        crop_w = w // 2
        return (w - crop_w, 0, w, h)


def add_watermark(image_path: str, output_path: str, mark: str = "sub", **kwargs) -> WatermarkResult:
    """便捷函数：添加单个水印"""
    tool = WatermarkTool()
    return tool.add_watermark(image_path, output_path, [mark], **kwargs)


def crop_cover(image_path: str, output_path: str, mode: str = "center") -> CropResult:
    """便捷函数：裁剪封面"""
    cropper = ImageCropper()
    return cropper.crop(image_path, output_path, mode)


__all__ = [
    "WatermarkTool",
    "ImageCropper",
    "WatermarkResult",
    "CropResult",
    "WATERMARK_PRESETS",
    "WATERMARK_POSITIONS",
    "CROP_MODES",
    "add_watermark",
    "crop_cover",
]
