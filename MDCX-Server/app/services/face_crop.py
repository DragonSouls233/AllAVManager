"""AI 人脸裁剪服务

参考 mdc-ng 和 Hazard804-mdcx 的 face_crop.py：
- 使用 YuNet ONNX 模型检测人脸
- 智能裁剪海报/封面，避免人脸被切掉
- 支持旋转回退检测（90/180/270度）
- 模型自动从 HuggingFace 下载

模型来源：https://huggingface.co/onnx-community/face_detection_yunet
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import httpx
from PIL import Image

from app.config.manager import get_config
from app.services.websocket import emit_log

logger = logging.getLogger(__name__)

# YuNet 模型下载地址
MODEL_URL = "https://huggingface.co/onnx-community/face_detection_yunet/resolve/main/onnx/model_fp32.onnx"
MODEL_CACHE_PATH = "data/models/face_detection_yunet_fp32.onnx"

# OpenCV Cascade Classifier 作为兜底方案
CASCADE_PATH_CACHE = None


async def download_yunet_model(target_path: str = MODEL_CACHE_PATH) -> bool:
    """下载 YuNet ONNX 模型"""
    if os.path.exists(target_path):
        return True

    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(MODEL_URL)
            if resp.status_code != 200:
                logger.error(f"下载 YuNet 模型失败: HTTP {resp.status_code}")
                return False
            with open(target_path, "wb") as f:
                f.write(resp.content)
        logger.info(f"YuNet 模型已下载到 {target_path}")
        return True
    except Exception as e:
        logger.error(f"下载 YuNet 模型失败: {e}")
        return False


class FaceCropper:
    """人脸裁剪器"""

    def __init__(
        self,
        model_path: Optional[str] = None,
        min_face_size: int = 80,
        margin_ratio: float = 0.4,
    ):
        self.model_path = model_path or MODEL_CACHE_PATH
        self.min_face_size = min_face_size
        self.margin_ratio = margin_ratio
        self._session = None  # ONNX Runtime session
        self._cv_cascade = None  # OpenCV Cascade 兜底

    async def initialize(self) -> bool:
        """初始化模型"""
        # 优先尝试 YuNet ONNX
        try:
            import onnxruntime as ort
            if not os.path.exists(self.model_path):
                ok = await download_yunet_model(self.model_path)
                if not ok:
                    logger.warning("YuNet 模型下载失败，回退到 OpenCV Cascade")
                    return await self._init_cv_cascade()

            self._session = ort.InferenceSession(
                self.model_path,
                providers=["CPUExecutionProvider"],
            )
            logger.info(f"YuNet 模型已加载: {self.model_path}")
            return True
        except ImportError:
            logger.warning("onnxruntime 未安装，回退到 OpenCV Cascade")
            return await self._init_cv_cascade()
        except Exception as e:
            logger.error(f"YuNet 初始化失败: {e}，回退到 OpenCV Cascade")
            return await self._init_cv_cascade()

    async def _init_cv_cascade(self) -> bool:
        """初始化 OpenCV Cascade 兜底方案"""
        try:
            import cv2
            # 使用 OpenCV 自带的人脸 cascade
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._cv_cascade = cv2.CascadeClassifier(cascade_path)
            if self._cv_cascade.empty():
                logger.error("OpenCV Cascade 加载失败")
                return False
            logger.info("OpenCV Cascade 已加载（兜底方案）")
            return True
        except ImportError:
            logger.error("opencv-python 未安装")
            return False
        except Exception as e:
            logger.error(f"OpenCV Cascade 初始化失败: {e}")
            return False

    def detect_faces_yunet(self, image):
        """使用 YuNet 检测人脸"""
        try:
            import cv2
            import numpy as np

            if isinstance(image, str):
                img = cv2.imread(image)
            elif isinstance(image, Image.Image):
                img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            else:
                img = image

            if img is None:
                return []

            h, w = img.shape[:2]

            # YuNet 输入
            input_name = self._session.get_inputs()[0].name
            # 预处理：resize 到 320x320（YuNet 默认）
            input_size = (320, 320)
            resized = cv2.resize(img, input_size)
            input_data = resized.transpose(2, 0, 1).astype("float32")
            input_data = input_data.reshape(1, 3, *input_size)

            # 推理
            outputs = self._session.run(None, {input_name: input_data})

            # 解析输出（YuNet 输出格式）
            # outputs[0]: [N, 15] - [x, y, w, h, ...landmarks..., score]
            faces = []
            if len(outputs) > 0 and outputs[0].size > 0:
                detections = outputs[0]
                # 缩放回原图坐标
                scale_x = w / input_size[0]
                scale_y = h / input_size[1]

                for det in detections:
                    score = det[-1] if len(det) >= 15 else 0
                    if score < 0.5:
                        continue
                    x, y, fw, fh = det[:4]
                    x = int(x * scale_x)
                    y = int(y * scale_y)
                    fw = int(fw * scale_x)
                    fh = int(fh * scale_y)

                    if fw < self.min_face_size or fh < self.min_face_size:
                        continue

                    faces.append({
                        "x": x,
                        "y": y,
                        "w": fw,
                        "h": fh,
                        "score": float(score),
                    })

            return faces
        except Exception as e:
            logger.error(f"YuNet 检测失败: {e}")
            return []

    def detect_faces_cv(self, image):
        """使用 OpenCV Cascade 检测人脸"""
        try:
            import cv2
            import numpy as np

            if isinstance(image, str):
                img = cv2.imread(image)
            elif isinstance(image, Image.Image):
                img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            else:
                img = image

            if img is None:
                return []

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces_raw = self._cv_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(self.min_face_size, self.min_face_size)
            )

            faces = []
            for (x, y, w, h) in faces_raw:
                faces.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h), "score": 1.0})

            return faces
        except Exception as e:
            logger.error(f"OpenCV 检测失败: {e}")
            return []

    def detect_faces(self, image):
        """检测人脸（优先 YuNet，兜底 OpenCV）"""
        if self._session is not None:
            faces = self.detect_faces_yunet(image)
            if faces:
                return faces
            # YuNet 无结果时尝试旋转
            return self._detect_with_rotation(image)
        elif self._cv_cascade is not None:
            return self.detect_faces_cv(image)
        return []

    def _detect_with_rotation(self, image):
        """带旋转回退的人脸检测"""
        try:
            import cv2
            import numpy as np

            if isinstance(image, str):
                img = cv2.imread(image)
            elif isinstance(image, Image.Image):
                img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            else:
                img = image.copy()

            if img is None:
                return []

            all_faces = []
            for angle in [0, 90, 180, 270]:
                if angle == 0:
                    rotated = img
                else:
                    rotated = cv2.rotate(img, {
                        90: cv2.ROTATE_90_CLOCKWISE,
                        180: cv2.ROTATE_180,
                        270: cv2.ROTATE_90_COUNTERCLOCKWISE,
                    }[angle])

                faces = self.detect_faces_yunet(rotated)
                if faces and angle != 0:
                    # 旋转回原坐标
                    h, w = img.shape[:2]
                    for f in faces:
                        if angle == 90:
                            f["x"], f["y"] = f["y"], w - f["x"] - f["w"]
                        elif angle == 180:
                            f["x"] = w - f["x"] - f["w"]
                            f["y"] = h - f["y"] - f["h"]
                        elif angle == 270:
                            f["x"], f["y"] = h - f["y"] - f["h"], f["x"]
                all_faces.extend(faces)

            return all_faces
        except Exception as e:
            logger.error(f"旋转检测失败: {e}")
            return []

    def smart_crop(
        self,
        image_path: str,
        output_path: str,
        target_ratio: tuple = (2, 3),  # poster 2:3 / cover 4:3
        quality: int = 95,
    ) -> bool:
        """智能裁剪图片

        策略：
        1. 检测所有人脸
        2. 计算人脸中心的包围盒
        3. 按目标比例裁剪，确保人脸在画面中央偏上
        """
        try:
            img = Image.open(image_path)
            if img.mode != "RGB":
                img = img.convert("RGB")

            w, h = img.size
            target_w_ratio, target_h_ratio = target_ratio
            target_ratio_val = target_w_ratio / target_h_ratio

            # 检测人脸
            faces = self.detect_faces(image_path)

            if not faces:
                # 无人脸：从中央裁剪
                if w / h > target_ratio_val:
                    # 原图更宽，裁剪左右
                    new_w = int(h * target_ratio_val)
                    left = (w - new_w) // 2
                    cropped = img.crop((left, 0, left + new_w, h))
                else:
                    # 原图更高，裁剪上下
                    new_h = int(w / target_ratio_val)
                    top = (h - new_h) // 2
                    cropped = img.crop((0, top, w, top + new_h))
            else:
                # 计算人脸中心
                face_centers = []
                for f in faces:
                    cx = f["x"] + f["w"] / 2
                    cy = f["y"] + f["h"] / 2
                    face_centers.append((cx, cy))

                # 取所有人脸的中心点
                avg_x = sum(c[0] for c in face_centers) / len(face_centers)
                avg_y = sum(c[1] for c in face_centers) / len(face_centers)

                # 计算裁剪框（以人脸中心为参考，向上偏移让人脸位于画面上 1/3）
                if w / h > target_ratio_val:
                    # 裁剪左右
                    new_w = int(h * target_ratio_val)
                    # 让人脸 x 居中
                    left = int(avg_x - new_w / 2)
                    left = max(0, min(left, w - new_w))
                    cropped = img.crop((left, 0, left + new_w, h))
                else:
                    # 裁剪上下
                    new_h = int(w / target_ratio_val)
                    # 让人脸位于画面上 1/3
                    target_y = avg_y - new_h * 0.35  # 人脸位于 35% 高度
                    top = int(target_y)
                    top = max(0, min(top, h - new_h))
                    cropped = img.crop((0, top, w, top + new_h))

            # 保存
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            cropped.save(output_path, "JPEG", quality=quality)
            return True
        except Exception as e:
            logger.error(f"智能裁剪失败: {e}")
            return False


# 全局单例
_face_cropper: Optional[FaceCropper] = None


async def get_face_cropper() -> Optional[FaceCropper]:
    """获取全局 FaceCropper 实例"""
    global _face_cropper
    if _face_cropper is None:
        cfg = get_config().face_crop
        cropper = FaceCropper(
            model_path=cfg.model_path,
            min_face_size=cfg.min_face_size,
            margin_ratio=cfg.margin_ratio,
        )
        ok = await cropper.initialize()
        if ok:
            _face_cropper = cropper
        else:
            return None
    return _face_cropper


async def crop_movie_poster(
    movie_id: int,
    source_path: str,
    output_path: str,
    task_id: str = "face-crop",
) -> bool:
    """为影片生成智能裁剪的海报"""
    cropper = await get_face_cropper()
    if cropper is None:
        await emit_log("ERROR", "人脸裁剪器未初始化", task_id=task_id, module="face-crop")
        return False

    cfg = get_config().face_crop

    # 选择目标比例
    if cfg.target == "poster":
        ratio = (2, 3)
    elif cfg.target == "cover":
        ratio = (4, 3)
    else:
        ratio = (2, 3)

    await emit_log("DEBUG", f"开始裁剪海报: movie={movie_id}", task_id=task_id, module="face-crop")

    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(
        None,
        cropper.smart_crop,
        source_path,
        output_path,
        ratio,
        cfg.output_quality,
    )

    if ok:
        await emit_log("SUCCESS", f"海报裁剪完成: movie={movie_id}", task_id=task_id, module="face-crop")
    else:
        await emit_log("ERROR", f"海报裁剪失败: movie={movie_id}", task_id=task_id, module="face-crop")

    return ok


# ============================================
# v4.1 B4：5 点面部标志点检测 + 人脸对齐
# ============================================
#
# 5 点标志点（兼容 YuNet / MediaPipe Face Mesh 的子集）：
#   - right_eye  : 右眼中心
#   - left_eye   : 左眼中心
#   - nose_tip   : 鼻尖
#   - mouth_right: 嘴右角
#   - mouth_left : 嘴左角
#
# 检测优先级：
#   1. MediaPipe Face Mesh（免费，478 点，取子集）
#   2. YuNet ONNX（已在 FaceCropper 中加载，输出自带 5 点）
#
# 人脸对齐策略：
#   - 基于双眼标志点连线计算旋转角度
#   - 用 Pillow 旋转校正后中心裁剪
# ============================================


def _load_image(image) -> Image.Image:
    """把多种输入统一转为 PIL.Image（RGB）

    Args:
        image: 文件路径 / PIL.Image / numpy 数组 / OpenCV BGR 数组

    Returns:
        PIL.Image.Image（RGB 模式）
    """
    if isinstance(image, Image.Image):
        if image.mode != "RGB":
            return image.convert("RGB")
        return image
    if isinstance(image, str):
        return Image.open(image).convert("RGB")
    # 当作 numpy 数组
    try:
        import numpy as np
        import cv2
        arr = np.asarray(image)
        if arr.ndim == 3 and arr.shape[2] == 3:
            # 假设是 BGR（cv2 默认），转为 RGB
            arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
        return Image.fromarray(arr).convert("RGB")
    except Exception as e:
        logger.error(f"加载图像失败: {e}")
        raise


def detect_landmarks_mediapipe(image) -> list[dict]:
    """使用 MediaPipe Face Mesh 检测 5 点标志点

    Args:
        image: 文件路径 / PIL.Image / numpy 数组

    Returns:
        每张人脸的 5 点标志点列表，元素格式：
        {
            "right_eye":  (x, y),
            "left_eye":   (x, y),
            "nose_tip":   (x, y),
            "mouth_right":(x, y),
            "mouth_left": (x, y),
            "score": float,           # 置信度（MediaPipe 无明确分值，固定 1.0）
        }
        无结果返回空列表。
    """
    try:
        import mediapipe as mp
        import numpy as np
    except ImportError:
        logger.debug("mediapipe 未安装，跳过 MediaPipe 检测")
        return []
    except Exception as e:
        logger.debug(f"mediapipe 导入失败: {e}")
        return []

    try:
        pil_img = _load_image(image)
        arr = np.array(pil_img)

        # MediaPipe Face Mesh 索引（478 点云的子集）
        # 右眼/左眼用 Iris 模型的瞳孔中心，鼻尖/嘴角用经典 Face Mesh 索引
        RIGHT_EYE_IDX = 468   # 右眼瞳孔（启用 refine_landmarks 时）
        LEFT_EYE_IDX = 473    # 左眼瞳孔
        NOSE_TIP_IDX = 1
        MOUTH_RIGHT_IDX = 61
        MOUTH_LEFT_IDX = 291

        results_list: list[dict] = []

        with mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=10,
            refine_landmarks=True,
            min_detection_confidence=0.5,
        ) as face_mesh:
            out = face_mesh.process(arr)
            if not out.multi_face_landmarks:
                return []

            h, w = arr.shape[:2]
            for face_lms in out.multi_face_landmarks:
                def _point(idx):
                    lm = face_lms.landmark[idx]
                    return (int(lm.x * w), int(lm.y * h))

                # refine_landmarks 关闭时无 468~477 瞳孔点，回退到眼眶中心
                has_iris = len(face_lms.landmark) > 473
                if has_iris:
                    right_eye = _point(RIGHT_EYE_IDX)
                    left_eye = _point(LEFT_EYE_IDX)
                else:
                    # 33=右眼外角, 133=右眼内角, 362=左眼内角, 263=左眼外角
                    right_eye = _point(33)
                    left_eye = _point(263)

                results_list.append({
                    "right_eye": right_eye,
                    "left_eye": left_eye,
                    "nose_tip": _point(NOSE_TIP_IDX),
                    "mouth_right": _point(MOUTH_RIGHT_IDX),
                    "mouth_left": _point(MOUTH_LEFT_IDX),
                    "score": 1.0,
                })

        return results_list
    except Exception as e:
        logger.error(f"MediaPipe 标志点检测失败: {e}")
        return []


def detect_landmarks_yunet(image) -> list[dict]:
    """使用已加载的 YuNet 模型检测 5 点标志点

    YuNet 输出每行人脸为 [x, y, w, h, re_x, re_y, le_x, le_y, nose_x, nose_y,
    mr_x, mr_y, ml_x, ml_y, score]，5 点标志点已内置。

    Args:
        image: 文件路径 / PIL.Image / numpy 数组

    Returns:
        每张人脸的 5 点标志点列表；若未初始化 YuNet 或检测失败返回空列表。
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []

    try:
        if isinstance(image, str):
            img = cv2.imread(image)
        elif isinstance(image, Image.Image):
            img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        else:
            img = image
        if img is None:
            return []

        h, w = img.shape[:2]
        input_size = (320, 320)
        resized = cv2.resize(img, input_size)
        input_data = resized.transpose(2, 0, 1).astype("float32").reshape(1, 3, *input_size)

        # 复用全局单例
        cropper = _face_cropper
        if cropper is None or cropper._session is None:
            return []

        input_name = cropper._session.get_inputs()[0].name
        outputs = cropper._session.run(None, {input_name: input_data})

        if not outputs or outputs[0].size == 0:
            return []

        detections = outputs[0]
        scale_x = w / input_size[0]
        scale_y = h / input_size[1]

        results_list: list[dict] = []
        for det in detections:
            score = det[-1] if len(det) >= 15 else 0
            if score < 0.5:
                continue
            # det[4:14] = re_x, re_y, le_x, le_y, nose_x, nose_y, mr_x, mr_y, ml_x, ml_y
            def _scale(idx):
                return (int(det[idx] * scale_x), int(det[idx + 1] * scale_y))
            results_list.append({
                "right_eye": _scale(4),
                "left_eye": _scale(6),
                "nose_tip": _scale(8),
                "mouth_right": _scale(10),
                "mouth_left": _scale(12),
                "score": float(score),
            })
        return results_list
    except Exception as e:
        logger.error(f"YuNet 标志点检测失败: {e}")
        return []


def detect_landmarks(image) -> list[dict]:
    """检测 5 点面部标志点（v4.1 B4）

    优先使用 MediaPipe（免费，需安装 mediapipe 包），失败则回退到 YuNet。

    Args:
        image: 文件路径 / PIL.Image / numpy 数组

    Returns:
        每张人脸的 5 点标志点列表，元素结构同 detect_landmarks_mediapipe。
    """
    # 1. 优先 MediaPipe
    try:
        lms = detect_landmarks_mediapipe(image)
        if lms:
            return lms
    except Exception as e:
        logger.debug(f"MediaPipe 标志点检测异常，回退 YuNet: {e}")

    # 2. 回退 YuNet
    try:
        lms = detect_landmarks_yunet(image)
        if lms:
            return lms
    except Exception as e:
        logger.debug(f"YuNet 标志点检测异常: {e}")

    return []


def align_face(
    image,
    landmarks: dict,
    target_size: tuple[int, int] = (224, 224),
    eye_scale: float = 0.45,
) -> Image.Image:
    """基于 5 点标志点对齐人脸（v4.1 B4）

    流程：
        1. 根据双眼标志点计算旋转角度
        2. 用 Pillow 旋转图像使双眼水平
        3. 以双眼中心为参考，按比例放大裁剪框
        4. 中心裁剪到 target_size

    Args:
        image: 文件路径 / PIL.Image / numpy 数组
        landmarks: 单张人脸的 5 点标志点 dict（必须含 right_eye / left_eye）
        target_size: 输出图像尺寸 (width, height)
        eye_scale: 双眼距离在裁剪宽度中的占比（越大裁得越紧）

    Returns:
        对齐并裁剪后的 PIL.Image（RGB）
    """
    import math

    pil_img = _load_image(image)
    img_w, img_h = pil_img.size

    re = landmarks.get("right_eye")
    le = landmarks.get("left_eye")
    if not re or not le:
        # 无双眼标志点：直接中心裁剪
        target_w, target_h = target_size
        ratio = target_w / target_h
        if img_w / img_h > ratio:
            new_w = int(img_h * ratio)
            left = (img_w - new_w) // 2
            return pil_img.crop((left, 0, left + new_w, img_h)).resize(target_size)
        else:
            new_h = int(img_w / ratio)
            top = (img_h - new_h) // 2
            return pil_img.crop((0, top, img_w, top + new_h)).resize(target_size)

    # 1. 计算旋转角度（注意 PIL y 轴向下，故用反向）
    dx = le[0] - re[0]
    dy = le[1] - re[1]
    # 当左眼在右眼右侧时（镜像人脸），dx 为正，角度需取反
    angle = math.degrees(math.atan2(dy, dx))

    # 2. 旋转图像（围绕双眼中点）
    eye_center = ((re[0] + le[0]) / 2.0, (re[1] + le[1]) / 2.0)
    rotated = pil_img.rotate(
        -angle,
        resample=Image.BILINEAR,
        center=eye_center,
    )

    # 旋转后，眼睛中点坐标不变（rotate 绕 center 旋转）
    new_center_x, new_center_y = eye_center

    # 3. 计算裁剪尺寸：双眼距离作为基准
    eye_dist = math.hypot(dx, dy)
    if eye_dist <= 0:
        eye_dist = max(img_w, img_h) * 0.2

    target_w, target_h = target_size
    # 裁剪宽度 = 眼距 / eye_scale；高度按目标比例推算
    crop_w = max(int(eye_dist / eye_scale), target_w)
    crop_h = int(crop_w * target_h / target_w)

    # 限制在图像范围内
    crop_w = min(crop_w, rotated.size[0])
    crop_h = min(crop_h, rotated.size[1])

    # 4. 中心裁剪
    left = int(new_center_x - crop_w / 2)
    top = int(new_center_y - crop_h / 2)
    left = max(0, min(left, rotated.size[0] - crop_w))
    top = max(0, min(top, rotated.size[1] - crop_h))

    cropped = rotated.crop((left, top, left + crop_w, top + crop_h))
    return cropped.resize(target_size, Image.BILINEAR)
