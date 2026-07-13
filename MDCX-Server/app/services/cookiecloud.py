"""CookieCloud 同步服务

CookieCloud 协议实现：
1. 浏览器扩展将 Cookie 加密上传到 CookieCloud 服务器
2. 客户端用 (server_url, user_id, password) 拉取加密数据
3. 使用 AES-256-CBC 解密（密钥 = md5(password) 的前 16 字节）
4. 解析 JSON，按域名提取 Cookie 字符串

参考项目：
- CookieCloud 官方客户端 https://github.com/easychen/CookieCloud
- nexus-media / JavdBviewed 的 CookieCloud 集成
"""

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import aiohttp

from app.config.manager import get_config
from app.utils.logger import get_logger

logger = get_logger(__name__)

# CookieCloud 协议常量
COOKIECLOUD_API_PATH = "/get/<uuid>"
COOKIECLOUD_TIMEOUT = 15  # 秒


def _derive_key(password: str) -> bytes:
    """从密码派生 AES 密钥（MD5 前 16 字节）

    CookieCloud 协议规定：key = md5(password)[:16]
    """
    return hashlib.md5(password.encode("utf-8")).hexdigest()[:16].encode("utf-8")


def _evp_bytes_to_key(password: bytes, salt: bytes, keylen: int = 32, ivlen: int = 16) -> tuple[bytes, bytes]:
    """OpenSSL EVP_BytesToKey(MD5, 1 iter) — CryptoJS passphrase 模式派生

    用于解码以 ``Salted__`` 开头的密文（很多第三方 CookieCloud 镜像使用此模式）。
    """
    buf = b""
    prev = b""
    while len(buf) < keylen + ivlen:
        prev = hashlib.md5(prev + password + salt).digest()
        buf += prev
    return buf[:keylen], buf[keylen:keylen + ivlen]


def _decrypt_aes_cbc(key: bytes, iv: bytes, body: bytes) -> bytes:
    """AES-CBC 解密 + PKCS7 去填充。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(body) + decryptor.finalize()
    unpadder = sym_padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def _decrypt_cookie_data(encrypted: str, password: str, user_id: Optional[str] = None) -> dict:
    """解密 CookieCloud 加密数据

    实际部署中存在多套常见协议，按顺序尝试直到成功。

    关键（按官方 easychen/CookieCloud 协议规范）:

    1. **legacy 模式**（CryptoJS ``AES.encrypt(msg, key)`` 默认，最常见）：
       - 派生 passphrase = ``md5(user_id + '-' + password).hexdigest()[:16]``（16B hex 字符串）
       - 密文 = ``base64("Salted__" + salt[8] + AES-256-CBC(cipher))``
       - 解密：取前 8 字节 salt → 整段 passphrase 走 ``EVP_BytesToKey(MD5, 1 iter)`` 出 48B
         → 前 32B = AES-256 key，后 16B = iv

    2. **aes-128-cbc-fixed 模式**（0.3.0+ 新算法）：
       - 派生 key = ``md5(user_id + '-' + password).hexdigest()[:16]``（16B）作 AES-128 密钥
       - 固定 IV = ``\\x00 * 16``
       - 密文 = ``base64(AES-128-CBC(cipher))``，**无 Salted__ 头**

    3. **老版显式 key/iv 模式**（旧仓库兼容）：
       - 派生 key = ``md5(password).hexdigest()[:16]``（16B），iv = key
       - AES-128-CBC，密文 = ``base64(AES-128-CBC(cipher))``，**无 Salted__ 头**

    Args:
        encrypted: 来自 ``/get/<uuid>`` 的 base64 加密数据
        password: 本地密码
        user_id: CookieCloud 用户 UUID（必须传才能正确解开 legacy/fixed 模式）
    """
    import base64

    raw = base64.b64decode(encrypted)
    pwd_bytes = password.encode("utf-8")
    last_err: Optional[Exception] = None

    # 构造官方 key 派生所需的 16B hex passphrase（仅在 user_id 已知时使用）
    if user_id:
        official_passphrase = hashlib.md5((user_id + "-" + password).encode("utf-8")).hexdigest()[:16].encode("utf-8")
        official_key_hex = hashlib.md5((user_id + "-" + password).encode("utf-8")).hexdigest()[:16].encode("utf-8")
    else:
        official_passphrase = None
        official_key_hex = None

    # --- 尝试 1: legacy 模式（密文以 Salted__ 开头，passphrase = MD5(uuid+'-'+pwd).hex[:16]） ---
    if raw[:8] == b"Salted__":
        if official_passphrase is not None:
            try:
                salt = raw[8:16]
                body = raw[16:]
                key, iv = _evp_bytes_to_key(official_passphrase, salt, 32, 16)
                plaintext = _decrypt_aes_cbc(key, iv, body)
                return json.loads(plaintext.decode("utf-8"))
            except Exception as e:
                last_err = e
                logger.debug(f"CookieCloud legacy 模式(user_id 派生) 解密失败, 尝试其他: {e}")
        # 兼容: 一些老版/不规范的镜像用裸密码当 passphrase
        try:
            salt = raw[8:16]
            body = raw[16:]
            key, iv = _evp_bytes_to_key(pwd_bytes, salt, 32, 16)
            plaintext = _decrypt_aes_cbc(key, iv, body)
            return json.loads(plaintext.decode("utf-8"))
        except Exception as e:
            last_err = e
            logger.debug(f"CookieCloud legacy 模式(裸密码) 解密失败, 尝试其他: {e}")

    # --- 尝试 2: aes-128-cbc-fixed 模式（无 Salted__ 头，固定 IV=0x00*16） ---
    if official_key_hex is not None:
        try:
            iv_zero = b"\x00" * 16
            plaintext = _decrypt_aes_cbc(official_key_hex, iv_zero, raw)
            return json.loads(plaintext.decode("utf-8"))
        except Exception as e:
            last_err = e
            logger.debug(f"CookieCloud fixed 模式(user_id 派生) 解密失败, 尝试其他: {e}")

    # --- 尝试 3: 老版显式 key/iv 模式（裸密码派生） ---
    try:
        key = _derive_key(password)
        iv = key
        plaintext = _decrypt_aes_cbc(key, iv, raw)
        return json.loads(plaintext.decode("utf-8"))
    except Exception as e:
        last_err = e

    logger.error(f"CookieCloud 解密失败: {last_err}")
    raise last_err if last_err else RuntimeError("CookieCloud 解密失败")


def _format_cookies_for_domain(cookies_data: dict, target_domain: str) -> Optional[str]:
    """从 CookieCloud 数据中提取指定域名的 Cookie 字符串

    Args:
        cookies_data: 解密后的 Cookie 数据，格式为 {"domain1": [{"name":"x","value":"y"}], ...}
        target_domain: 目标域名（如 "javdb.com"）

    Returns:
        Cookie 字符串（如 "key1=val1; key2=val2"）或 None
    """
    # 精确匹配 + 后缀匹配（处理 .javdb.com 子域名）
    matched_cookies = []

    for domain, cookies in cookies_data.items():
        if domain == target_domain or domain.endswith(f".{target_domain}"):
            if isinstance(cookies, list):
                for c in cookies:
                    if isinstance(c, dict) and "name" in c and "value" in c:
                        matched_cookies.append(f"{c['name']}={c['value']}")

    if not matched_cookies:
        return None

    # 去重（同名的保留最后一个）
    seen = {}
    for item in matched_cookies:
        name, _, value = item.partition("=")
        seen[name] = value

    return "; ".join(f"{k}={v}" for k, v in seen.items())


class CookieCloudService:
    """CookieCloud 同步服务"""

    def __init__(self):
        self._sync_task: Optional[asyncio.Task] = None
        self._last_sync_status: dict = {"ok": False, "msg": "未同步", "count": 0, "at": None}

    async def sync_once(self) -> dict:
        """执行一次同步

        Returns:
            {"ok": bool, "msg": str, "count": int, "updated": dict}
        """
        cfg = get_config().cookiecloud
        if not cfg.enabled:
            return {"ok": False, "msg": "CookieCloud 未启用", "count": 0, "updated": {}}

        if not cfg.server_url or not cfg.user_id or not cfg.password:
            return {"ok": False, "msg": "配置不完整（需 server_url + user_id + password）", "count": 0, "updated": {}}

        try:
            # 1. 拉取加密数据
            server_url = cfg.server_url.rstrip("/")
            api_url = f"{server_url}/get/{cfg.user_id}"

            timeout = aiohttp.ClientTimeout(total=COOKIECLOUD_TIMEOUT)
            # 统一走项目唯一定义源：优先内置 xray 实际端口，回退旧版 config.proxy
            proxy = None
            try:
                from app.services.proxy_manager import get_effective_proxy_url
                proxy = get_effective_proxy_url()
            except Exception:
                pass

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(api_url, proxy=proxy) as resp:
                    if resp.status != 200:
                        return {"ok": False, "msg": f"服务器返回 {resp.status}", "count": 0, "updated": {}}
                    data = await resp.json()

            if not data.get("encrypted"):
                return {"ok": False, "msg": "服务器返回数据格式错误（无 encrypted 字段）", "count": 0, "updated": {}}

            # 2. 解密
            cookies_data = _decrypt_cookie_data(data["encrypted"], cfg.password, user_id=cfg.user_id)

            # cookiecloud 数据格式: {"cookie_data": {"domain": [...]}, "updated_at": ...}
            # 兼容两种格式：直接是 domain→cookies 字典，或包装在 cookie_data 里
            if "cookie_data" in cookies_data:
                cookies_data = cookies_data["cookie_data"]

            # 3. 按域名映射提取 Cookie
            updated = {}
            for domain, field_name in cfg.domain_mapping.items():
                cookie_str = _format_cookies_for_domain(cookies_data, domain)
                if cookie_str:
                    updated[field_name] = cookie_str
                    logger.info(f"CookieCloud 同步 {domain} → {field_name} ({len(cookie_str)} chars)")

            if not updated:
                return {"ok": False, "msg": "未匹配到任何配置的域名 Cookie", "count": 0, "updated": {}}

            # 4. 写回 CrawlerConfig
            from app.config.manager import get_config_manager
            config = get_config()
            for field_name, cookie_value in updated.items():
                setattr(config.crawler, field_name, cookie_value)
            # 更新最后同步时间
            config.cookiecloud.last_sync_at = datetime.now(timezone.utc).isoformat()
            get_config_manager().save()

            self._last_sync_status = {
                "ok": True,
                "msg": f"成功同步 {len(updated)} 个站点的 Cookie",
                "count": len(updated),
                "at": config.cookiecloud.last_sync_at,
            }

            logger.info(f"CookieCloud 同步完成: {self._last_sync_status['msg']}")
            return {"ok": True, "msg": self._last_sync_status["msg"], "count": len(updated), "updated": updated, "at": config.cookiecloud.last_sync_at}

        except Exception as e:
            logger.error(f"CookieCloud 同步失败: {e}")
            self._last_sync_status = {"ok": False, "msg": str(e), "count": 0, "at": None}
            return {"ok": False, "msg": str(e), "count": 0, "updated": {}}

    def get_status(self) -> dict:
        """获取上次同步状态"""
        cfg = get_config().cookiecloud
        return {
            "enabled": cfg.enabled,
            "server_url": cfg.server_url,
            "user_id": cfg.user_id[:8] + "..." if len(cfg.user_id) > 8 else cfg.user_id,
            "auto_sync_interval": cfg.auto_sync_interval,
            "last_sync_at": cfg.last_sync_at,
            "domain_mapping": cfg.domain_mapping,
            "last_status": self._last_sync_status,
        }

    async def start_auto_sync(self):
        """启动自动同步后台任务"""
        if self._sync_task and not self._sync_task.done():
            return

        async def _loop():
            while True:
                try:
                    cfg = get_config().cookiecloud
                    if cfg.enabled:
                        await self.sync_once()
                    interval = cfg.auto_sync_interval
                except Exception as e:
                    logger.error(f"CookieCloud 自动同步异常: {e}")
                    interval = 3600
                await asyncio.sleep(interval)

        self._sync_task = asyncio.create_task(_loop())
        logger.info("CookieCloud 自动同步任务已启动")

    async def stop_auto_sync(self):
        """停止自动同步"""
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            self._sync_task = None
            logger.info("CookieCloud 自动同步任务已停止")


# 全局单例
cookiecloud_service = CookieCloudService()


__all__ = ["cookiecloud_service", "CookieCloudService"]
