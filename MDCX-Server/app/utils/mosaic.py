"""
马赛克检测模块

基于 OpenCV 检测图片/视频帧中的马赛克区域。
参考 Hazard804/mdcx core/mosaic.py 实现。

检测原理：
1. 将图片转为灰度图
2. 计算局部方差（马赛克区域方差显著低于正常区域）
3. 通过阈值判断是否存在马赛克
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# 马赛克检测参数
MOSAIC_BLOCK_SIZE = 16          # 检测块大小（像素）
MOSAIC_VARIANCE_THRESHOLD = 15  # 方差阈值（低于此值视为马赛克）
MOSAIC_RATIO_THRESHOLD = 0.15   # 马赛克区域占比阈值
DETECT_MAX_SIDE = 1024          # 检测时最大边长（超过则缩放）


class MosaicDetector:
    """
    马赛克检测器

    基于局部方差分析检测图片中是否存在马赛克区域。
    适用于检测视频封面/截图中的马赛克（模糊/像素化区域）。
    """

    def detect_image(self, image_path: str) -> Optional[bool]:
        """
        检测单张图片是否包含马赛克

        Args:
            image_path: 图片路径

        Returns:
            True=有马赛克, False=无马赛克, None=检测失败
        """
        try:
            import cv2

            # 读取图片
            image = cv2.imread(image_path)
            if image is None:
                logger.warning(f"无法读取图片: {image_path}")
                return None

            return self._detect_mosaic(image)

        except ImportError:
            logger.warning("OpenCV 未安装，跳过马赛克检测")
            return None
        except Exception as e:
            logger.error(f"马赛克检测失败: {image_path} - {e}")
            return None

    def _detect_mosaic(self, image: np.ndarray) -> bool:
        """
        检测图像中是否存在马赛克

        Args:
            image: OpenCV 图像 (BGR)

        Returns:
            是否存在马赛克
        """
        height, width = image.shape[:2]

        # 如果图片太大，先缩放
        if max(height, width) > DETECT_MAX_SIDE:
            scale = DETECT_MAX_SIDE / max(height, width)
            new_width = int(width * scale)
            new_height = int(height * scale)
            image = cv2.resize(image, (new_width, new_height))

        # 转为灰度图
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # 使用拉普拉斯算子检测模糊度（整体模糊度评估）
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

        # 如果整体非常模糊，可能是马赛克
        if laplacian_var < 10:
            return True

        # 局部方差分析
        h, w = gray.shape
        mosaic_blocks = 0
        total_blocks = 0

        for y in range(0, h - MOSAIC_BLOCK_SIZE, MOSAIC_BLOCK_SIZE):
            for x in range(0, w - MOSAIC_BLOCK_SIZE, MOSAIC_BLOCK_SIZE):
                block = gray[y:y + MOSAIC_BLOCK_SIZE, x:x + MOSAIC_BLOCK_SIZE]
                variance = block.var()

                if variance < MOSAIC_VARIANCE_THRESHOLD:
                    mosaic_blocks += 1
                total_blocks += 1

        mosaic_ratio = mosaic_blocks / total_blocks if total_blocks > 0 else 0

        logger.debug(
            f"马赛克检测: laplacian_var={laplacian_var:.1f}, "
            f"mosaic_ratio={mosaic_ratio:.3f}, "
            f"mosaic_blocks={mosaic_blocks}/{total_blocks}"
        )

        return mosaic_ratio > MOSAIC_RATIO_THRESHOLD

    def detect_video_frame(
        self,
        video_path: str,
        frame_pos: float = 0.5,
    ) -> Optional[bool]:
        """
        检测视频中某一帧是否包含马赛克

        Args:
            video_path: 视频文件路径
            frame_pos: 帧位置 (0-1)，默认取中间帧

        Returns:
            True=有马赛克, False=无马赛克, None=检测失败
        """
        try:
            import cv2

            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.warning(f"无法打开视频: {video_path}")
                return None

            try:
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                if total_frames <= 0:
                    return None

                target_frame = int(total_frames * frame_pos)
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

                ret, frame = cap.read()
                if not ret:
                    return None

                return self._detect_mosaic(frame)

            finally:
                cap.release()

        except ImportError:
            logger.warning("OpenCV 未安装，跳过视频马赛克检测")
            return None
        except Exception as e:
            logger.error(f"视频马赛克检测失败: {video_path} - {e}")
            return None


# 全局实例
_detector: Optional[MosaicDetector] = None


def get_mosaic_detector() -> MosaicDetector:
    """获取全局马赛克检测器实例"""
    global _detector
    if _detector is None:
        _detector = MosaicDetector()
    return _detector


def detect_mosaic(image_path: str) -> Optional[bool]:
    """
    检测图片是否包含马赛克的便捷函数

    Args:
        image_path: 图片路径

    Returns:
        True=有马赛克, False=无马赛克, None=检测失败
    """
    detector = get_mosaic_detector()
    return detector.detect_image(image_path)
