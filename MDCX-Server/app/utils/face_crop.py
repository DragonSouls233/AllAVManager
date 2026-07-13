"""
演员头像人脸裁剪

参考 Hazard804 mdcx/core/face_crop.py 实现。
使用 OpenCV YuNet 模型检测人脸并裁剪头像。
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# YuNet 模型配置
YUNET_MODEL_URL = "https://huggingface.co/opencv/opencv_zoo/resolve/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
YUNET_MODEL_NAME = "face_detection_yunet_2023mar.onnx"
YUNET_SCORE_THRESHOLD = 0.7
YUNET_NMS_THRESHOLD = 0.3
YUNET_TOP_K = 5000
YUNET_DETECT_MAX_SIDE = 800

# 输出头像尺寸
AVATAR_SIZE = (400, 400)

# 人脸框扩展比例（上下左右各扩展的比例）
FACE_EXPAND_RATIO = 0.3


@dataclass(frozen=True)
class FaceBox:
    """人脸框"""
    left: int
    top: int
    right: int
    bottom: int
    score: float = 0.0

    @property
    def width(self) -> int:
        return max(self.right - self.left, 0)

    @property
    def height(self) -> int:
        return max(self.bottom - self.top, 0)


class FaceCropper:
    """
    人脸裁剪器

    使用 OpenCV YuNet 模型检测图片中的人脸，
    裁剪并缩放为统一尺寸的头像。
    """

    # 类级别标记：是否已尝试过下载模型（避免每个演员都重试）
    _download_attempted = False

    def __init__(self, model_dir: Optional[str] = None):
        """
        初始化

        Args:
            model_dir: 模型文件目录（默认自动下载到 data/cache/face_detector）
        """
        self.model_dir = Path(model_dir) if model_dir else Path("data/cache/face_detector")
        self.model_path = self.model_dir / YUNET_MODEL_NAME
        self._model = None

    def _ensure_model(self) -> None:
        """确保模型文件存在"""
        if self._model is not None:
            return

        if not self.model_path.exists() and not FaceCropper._download_attempted:
            FaceCropper._download_attempted = True  # 只尝试一次
            try:
                self._download_model()
            except Exception as e:
                logger.warning(f"下载 YuNet 模型失败，将使用 Haar Cascade 回退: {e}")

        # 即使下载失败也尝试加载（如果文件已存在）
        try:
            import cv2
            if self.model_path.exists():
                self._model = cv2.FaceDetectorYN.create(
                    str(self.model_path),
                    "",
                    (320, 320),
                    YUNET_SCORE_THRESHOLD,
                    YUNET_NMS_THRESHOLD,
                    YUNET_TOP_K,
                )
                logger.info("YuNet 人脸检测模型加载成功")
            else:
                logger.debug("YuNet 模型文件不存在，将使用 Haar Cascade 回退")
                self._model = None
        except Exception as e:
            logger.debug(f"无法加载 YuNet 模型，回退到 OpenCV Haar Cascade: {e}")
            self._model = None

    def _download_model(self) -> None:
        """下载 YuNet 模型（支持代理）"""
        self.model_dir.mkdir(parents=True, exist_ok=True)

        import urllib.request

        logger.info(f"下载 YuNet 模型: {YUNET_MODEL_URL}")

        # 尝试通过代理下载
        proxy_url = self._get_proxy_url()
        if proxy_url:
            logger.info(f"使用代理下载模型: {proxy_url}")
            handler = urllib.request.ProxyHandler({
                "http": proxy_url,
                "https": proxy_url,
            })
            opener = urllib.request.build_opener(handler)
        else:
            opener = urllib.request.build_opener()

        with opener.open(YUNET_MODEL_URL, timeout=60) as resp:
            with open(str(self.model_path), "wb") as f:
                f.write(resp.read())
        logger.info("YuNet 模型下载完成")

    @staticmethod
    def _get_proxy_url() -> Optional[str]:
        """获取代理URL：统一走内置 xray / 旧版 config.proxy 的唯一定义源"""
        from app.services.proxy_manager import get_effective_proxy_url
        return get_effective_proxy_url()

    def detect_faces(self, image_path: str) -> list[FaceBox]:
        """
        检测图片中的人脸

        Args:
            image_path: 图片路径

        Returns:
            人脸框列表（按置信度降序）
        """
        self._ensure_model()

        try:
            import cv2

            # 读取图片
            image = cv2.imread(image_path)
            if image is None:
                logger.warning(f"无法读取图片: {image_path}")
                return []

            height, width = image.shape[:2]

            # 如果图片太大，先缩放
            scale = 1.0
            if max(height, width) > YUNET_DETECT_MAX_SIDE:
                scale = YUNET_DETECT_MAX_SIDE / max(height, width)
                new_width = int(width * scale)
                new_height = int(height * scale)
                image = cv2.resize(image, (new_width, new_height))

            if self._model is not None:
                # 使用 YuNet 模型
                self._model.setInputSize((image.shape[1], image.shape[0]))
                _, faces = self._model.detect(image)

                if faces is None:
                    return []

                results = []
                for face in faces:
                    x, y, w, h = face[:4].astype(int)
                    results.append(FaceBox(
                        left=x,
                        top=y,
                        right=x + w,
                        bottom=y + h,
                        score=float(face[-1]),
                    ))

                # 按置信度降序
                results.sort(key=lambda f: f.score, reverse=True)

                # 如果缩放过了，还原坐标
                if scale != 1.0:
                    results = [_scale_face_box(f, scale, width, height) for f in results]

                return results

            else:
                # 回退到 Haar Cascade
                return self._detect_with_haar(image, scale, width, height)

        except Exception as e:
            logger.error(f"人脸检测失败: {e}")
            return []

    def _detect_with_haar(
        self, image: np.ndarray, scale: float, orig_width: int, orig_height: int
    ) -> list[FaceBox]:
        """使用 Haar Cascade 回退方案"""
        try:
            import cv2

            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            cascade = cv2.CascadeClassifier(cascade_path)

            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 5)

            results = []
            for (x, y, w, h) in faces:
                results.append(FaceBox(
                    left=x,
                    top=y,
                    right=x + w,
                    bottom=y + h,
                    score=0.5,
                ))

            results.sort(key=lambda f: f.score, reverse=True)

            if scale != 1.0:
                results = [_scale_face_box(f, scale, orig_width, orig_height) for f in results]

            return results

        except Exception as e:
            logger.error(f"Haar Cascade 检测失败: {e}")
            return []

    def crop_face(
        self,
        image_path: str,
        output_path: str,
        target_size: tuple[int, int] = AVATAR_SIZE,
    ) -> Optional[str]:
        """
        检测并裁剪人脸头像

        流程：
        1. 检测人脸
        2. 扩展人脸框（上下左右各扩展 30%）
        3. 裁剪并缩放到目标尺寸

        Args:
            image_path: 原图路径
            output_path: 输出路径
            target_size: 目标尺寸 (宽, 高)

        Returns:
            输出路径，失败返回 None
        """
        try:
            # 检测人脸
            faces = self.detect_faces(image_path)

            # 打开原图
            with Image.open(image_path) as img:
                img_width, img_height = img.size

                if faces:
                    # 取置信度最高的人脸
                    face = faces[0]

                    # 扩展人脸框
                    face_width = face.width
                    face_height = face.height
                    expand_x = int(face_width * FACE_EXPAND_RATIO)
                    expand_y = int(face_height * FACE_EXPAND_RATIO)

                    left = max(face.left - expand_x, 0)
                    top = max(face.top - expand_y, 0)
                    right = min(face.right + expand_x, img_width)
                    bottom = min(face.bottom + expand_y, img_height)

                    # 裁剪
                    cropped = img.crop((left, top, right, bottom))
                else:
                    # 未检测到人脸，使用图片中心区域
                    logger.info(f"未检测到人脸，使用中心裁剪: {image_path}")
                    size = min(img_width, img_height)
                    left = (img_width - size) // 2
                    top = (img_height - size) // 2
                    cropped = img.crop((left, top, left + size, top + size))

                # 缩放到目标尺寸
                cropped = cropped.resize(target_size, Image.Resampling.LANCZOS)

                # 保存
                output_path = Path(output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                cropped.save(output_path, "JPEG", quality=90)

                logger.info(f"头像裁剪完成: {output_path}")
                return str(output_path)

        except Exception as e:
            logger.error(f"头像裁剪失败: {image_path} - {e}")
            return None

    def crop_actor_avatar(
        self,
        image_url: str,
        actor_name: str,
        output_dir: str,
    ) -> Optional[str]:
        """
        下载并裁剪演员头像

        Args:
            image_url: 头像图片 URL
            actor_name: 演员名
            output_dir: 输出目录

        Returns:
            保存的文件路径
        """
        import httpx

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 下载图片
        temp_path = output_dir / f"{actor_name}_temp.jpg"
        try:
            response = httpx.get(image_url, timeout=30, follow_redirects=True)
            response.raise_for_status()
            with open(temp_path, "wb") as f:
                f.write(response.content)
        except Exception as e:
            logger.error(f"下载头像失败: {image_url} - {e}")
            return None

        # 裁剪
        output_path = output_dir / f"{actor_name}.jpg"
        result = self.crop_face(str(temp_path), str(output_path))

        # 清理临时文件
        if temp_path.exists():
            temp_path.unlink()

        return result


def _scale_face_box(face: FaceBox, scale: float, image_width: int, image_height: int) -> FaceBox:
    """缩放人脸框坐标"""
    return FaceBox(
        left=max(int(round(face.left / scale)), 0),
        top=max(int(round(face.top / scale)), 0),
        right=min(int(round(face.right / scale)), image_width),
        bottom=min(int(round(face.bottom / scale)), image_height),
        score=face.score,
    )


# 全局实例
_cropper: Optional[FaceCropper] = None


def get_face_cropper() -> FaceCropper:
    """获取全局人脸裁剪器实例"""
    global _cropper
    if _cropper is None:
        _cropper = FaceCropper()
    return _cropper


def crop_actor_face(
    image_url: str,
    actor_name: str,
    output_dir: str,
) -> Optional[str]:
    """
    裁剪演员头像的便捷函数

    Args:
        image_url: 头像图片 URL
        actor_name: 演员名
        output_dir: 输出目录

    Returns:
        保存的文件路径
    """
    cropper = get_face_cropper()
    return cropper.crop_actor_avatar(image_url, actor_name, output_dir)
