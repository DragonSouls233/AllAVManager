"""网络存储（SMB 共享 / 映射盘）辅助。

背景
----
MDCX 服务端常以「计划任务 / 服务」方式在**非交互会话**中运行。此时 Windows
不会自动重建用户在交互会话里建立的持久映射（例如 ``Z:\\`` -> ``\\\\dragon\\JAV1``），
于是会出现两个连锁问题：

1. ``/files/browse`` 的「此电脑」只列出 C/D/E 等本地盘 —— 用户在界面上根本
   **选不到网络存储**；
2. 已配置的媒体目录不可达 —— 扫描被跳过、播放失败。

本模块负责（全部 best-effort，绝不阻塞调用方）：
- 读取注册表里的持久映射（即使当前未连接）；
- 把未连接的网络盘重连到当前会话；
- 保存 SMB 凭据并在 ``net use`` 时以 ``/user:`` 显式传入，使**任何会话**
  （含计划任务/服务/SSH）都能认证到远端共享。

⚠️ 服务器侧**不要**依赖 ``cmdkey``：SSH（网络登录 type3）下会报
「CMDKEY: 不能从此登录会话保存凭据。」。凭据请写在
``<DATA_DIR>/config/network_credentials.json``，或用 ``POST /files/network-credentials``。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("mdcx.net_drives")

IS_WINDOWS = sys.platform == "win32"
_CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

try:  # pragma: no cover - 非 Windows 下不可用
    import winreg  # type: ignore
except Exception:  # pragma: no cover
    winreg = None  # type: ignore


def _run(args: list[str], timeout: float = 20.0) -> tuple[int, str]:
    """执行外部命令，带超时（网络盘挂死时不会把调用方拖住）。"""
    try:
        p = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return -1, f"执行超时({timeout}s)"
    except Exception as e:  # noqa: BLE001
        return -2, str(e)

    raw = (p.stdout or b"") + (p.stderr or b"")
    text = ""
    for enc in ("utf-8", "gbk"):
        try:
            text = raw.decode(enc).strip()
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = raw.decode("utf-8", "replace").strip()
    return p.returncode, text


def _reg_value(key, name: str) -> str:
    try:
        v, _t = winreg.QueryValueEx(key, name)  # type: ignore[union-attr]
        return v if isinstance(v, str) else ("" if v is None else str(v))
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# SMB 凭据存储（本机 JSON，位于数据目录 config/ 下）
#
# 为什么不用 cmdkey 作为主通道：
#   ``cmdkey /add`` 在 **非交互登录会话**（SSH 网络登录 type3、服务会话）里会直接
#   报「CMDKEY: 不能从此登录会话保存凭据。」，所以在服务器侧通过 SSH 部署凭据时
#   这条路走不通。
# 因此改为：把凭据存成本机 JSON，由 MDCX 服务进程**在自己的会话里**执行
#   ``net use <盘符> <UNC> /user:<用户> <口令> /persistent:no``
# 这一步在任意会话都可用，且映射对发起进程立即可见。
# cmdkey 仍会尽力写一次（交互式 GUI 场景有效），失败不影响主流程。
# ---------------------------------------------------------------------------

DEFAULT_CRED_KEY = "*"


def _cred_file() -> "Path | None":
    try:
        from app.config.manager import DATA_DIR  # noqa: PLC0415

        return Path(DATA_DIR) / "config" / "network_credentials.json"
    except Exception:  # noqa: BLE001
        try:
            root = Path(__file__).resolve().parents[2]
            return root / "data" / "config" / "network_credentials.json"
        except Exception:  # noqa: BLE001
            return None


def load_credentials() -> dict[str, dict[str, str]]:
    """读取已保存的 SMB 凭据 ``{主机: {'user':..., 'password':...}}``。"""
    hosts = _read_cred_json().get("hosts")
    return hosts if isinstance(hosts, dict) else {}


def save_credentials(host: str, user: str, password: str) -> bool:
    """把凭据写入本机 JSON（追加/覆盖该主机）。"""
    fp = _cred_file()
    if fp is None:
        return False
    key = (host or "").strip()
    if not key:
        return False
    data = _read_cred_json()
    hosts = data.setdefault("hosts", {})
    if not isinstance(hosts, dict):
        hosts = {}
        data["hosts"] = hosts
    # 同名只留键大小写各异的一份，避免 "dragon" / "DRAGON" 重复
    for old in [k for k in list(hosts) if str(k).lower() == key.lower() and k != key]:
        hosts.pop(old, None)
    hosts[key] = {"user": user, "password": password}
    return _write_cred_json(data, fp)


def _read_cred_json() -> dict[str, Any]:
    fp = _cred_file()
    if fp is None or not fp.is_file():
        return {"hosts": {}}
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"hosts": {}}
    except Exception as e:  # noqa: BLE001
        logger.warning("读取网络存储配置失败: %s", e)
        return {"hosts": {}}


def _write_cred_json(data: dict[str, Any], fp: "Path | None" = None) -> bool:
    fp = fp or _cred_file()
    if fp is None:
        return False
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(fp, 0o600)
    except Exception as e:  # noqa: BLE001
        logger.warning("写入网络存储配置失败: %s", e)
        return False
    return True


def load_configured_mappings() -> list[dict[str, str]]:
    """读取配置里声明的「盘符 ↔ UNC」清单（注册表为空时的重建依据）。"""
    raw = _read_cred_json().get("mappings")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        drive = str(item.get("drive") or "").strip()
        remote = str(item.get("remote") or "").strip()
        if not drive or not remote.startswith("\\\\"):
            continue
        if not drive.endswith(":"):
            drive += ":"
        out.append({"drive": drive.upper(), "remote": remote})
    return out


def save_configured_mappings(mappings: list[dict[str, str]]) -> bool:
    """写入「盘符 ↔ UNC」清单（整体替换）。"""
    clean: list[dict[str, str]] = []
    for item in mappings or []:
        if not isinstance(item, dict):
            continue
        drive = str(item.get("drive") or "").strip()
        remote = str(item.get("remote") or "").strip()
        if not drive or not remote.startswith("\\\\"):
            continue
        if not drive.endswith(":"):
            drive += ":"
        clean.append({"drive": drive.upper(), "remote": remote})
    data = _read_cred_json()
    data["mappings"] = clean
    return _write_cred_json(data)


def delete_saved_credentials(host: str) -> bool:
    hosts = load_credentials()
    target = (host or "").strip().lower()
    remaining = {k: v for k, v in hosts.items() if str(k).lower() != target}
    if len(remaining) == len(hosts):
        return False
    data = _read_cred_json()
    data["hosts"] = remaining
    return _write_cred_json(data)


def _unc_host(remote: str) -> str:
    s = (remote or "").strip().lstrip("\\").lstrip("/")
    for sep in ("\\", "/"):
        s = s.split(sep)[0] if sep in s else s
    return s


# ---------------------------------------------------------------------------
# 「当前会话里真实存在的网络盘」——注册表兜底
#
# 注册表可能因为历史操作（例如 ``net use X: /delete``）丢掉持久条目，但服务进程
# 会话里的映射仍在。此时如果只看注册表就会「什么都列不出来 → 什么都不重连」。
# 所以这里用 Win32 API 把当前会话真实的网络盘也读出来，与注册表取并集。
# ---------------------------------------------------------------------------

def _win32_drive_letters() -> list[str]:
    """返回当前会话里所有盘符，形如 ``['C:', 'Z:']``。"""
    try:
        import ctypes  # noqa: PLC0415

        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return [chr(ord("A") + i) + ":" for i in range(26) if mask & (1 << i)]
    except Exception:  # noqa: BLE001
        return []


def _win32_unc_for_drive(letter: str) -> str:
    """取映射盘的远端 UNC（mpr.dll!WNetGetConnectionW），非网络盘返回空串。"""
    try:
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        buf = ctypes.create_unicode_buffer(2048)
        size = wintypes.DWORD(len(buf))
        rc = ctypes.windll.mpr.WNetGetConnectionW(
            letter.rstrip("\\/"), buf, ctypes.byref(size)
        )
        return buf.value if rc == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def list_live_mappings() -> list[dict[str, Any]]:
    """当前会话里真实连着的网络盘（不查注册表）。"""
    if not IS_WINDOWS:
        return []
    out: list[dict[str, Any]] = []
    for letter in _win32_drive_letters():
        unc = _win32_unc_for_drive(letter)
        if not unc.startswith("\\\\"):
            continue
        out.append(
            {"drive": letter, "remote": unc, "user": "", "sid": "LIVE", "source": "live"}
        )
    return out


def credential_for(remote: str) -> "tuple[str, str] | None":
    """按 UNC 里的主机（名字或 IP）查找凭据；找不到则用通配键 ``*``。"""
    creds = load_credentials()
    if not creds:
        return None
    host = _unc_host(remote)
    candidates = [host.lower()]
    try:
        import socket  # noqa: PLC0415

        for info in socket.getaddrinfo(host, None):
            ip = info[4][0]
            if ip and ip.lower() not in candidates:
                candidates.append(ip.lower())
    except Exception:  # noqa: BLE001
        pass
    for cand in candidates:
        for k, v in creds.items():
            if str(k).lower() == cand and isinstance(v, dict) and v.get("user"):
                return str(v["user"]), str(v.get("password", ""))
    star = creds.get(DEFAULT_CRED_KEY)
    if isinstance(star, dict) and star.get("user"):
        return str(star["user"]), str(star.get("password", ""))
    return None


def _mask(text: str, secret: "str | None") -> str:
    """命令回显里抹掉口令，避免写进日志。"""
    if secret and secret in text:
        return text.replace(secret, "******")
    return text


def list_credential_hosts() -> list[dict[str, str]]:
    """列出已保存凭据的主机（不含口令）。"""
    out = []
    for host, v in load_credentials().items():
        if isinstance(v, dict):
            out.append({"host": str(host), "user": str(v.get("user", ""))})
    return out


def list_persistent_mappings() -> list[dict[str, Any]]:
    """读取注册表里所有用户的持久网络映射（即使当前会话未连接）。

    返回 ``[{'drive': 'Z:', 'remote': '\\\\dragon\\JAV1', 'user': '...', 'sid': ...}]``，
    按盘符去重（本用户优先）。
    """
    if not IS_WINDOWS or winreg is None:
        return []

    found: dict[str, dict[str, Any]] = {}

    def _scan_root(root) -> None:
        try:
            with winreg.OpenKey(root, "") as base:  # type: ignore[union-attr]
                i = 0
                while True:
                    try:
                        sid = winreg.EnumKey(base, i)  # type: ignore[union-attr]
                    except OSError:
                        break
                    i += 1
                    if sid.endswith("_Classes"):
                        continue
                    _scan_network(sid)
        except Exception as e:  # noqa: BLE001
            logger.debug("枚举注册表根失败: %s", e)

    def _scan_network(sid: str) -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_USERS, rf"{sid}\Network") as nk:  # type: ignore[union-attr]
                i = 0
                while True:
                    try:
                        letter = winreg.EnumKey(nk, i)  # type: ignore[union-attr]
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(nk, letter) as dk:  # type: ignore[union-attr]
                            remote = _reg_value(dk, "RemotePath")
                            user = _reg_value(dk, "UserName")
                    except OSError:
                        continue
                    if remote:
                        found[letter.upper()] = {
                            "drive": f"{letter.upper()}:",
                            "remote": remote,
                            "user": user,
                            "sid": sid,
                        }
        except OSError:
            return

    _scan_root(winreg.HKEY_USERS)  # type: ignore[union-attr]

    # 当前登录用户的映射优先级最高
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Network") as nk:  # type: ignore[union-attr]
            i = 0
            while True:
                try:
                    letter = winreg.EnumKey(nk, i)  # type: ignore[union-attr]
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(nk, letter) as dk:  # type: ignore[union-attr]
                        remote = _reg_value(dk, "RemotePath")
                        user = _reg_value(dk, "UserName")
                except OSError:
                    continue
                if remote:
                    found[letter.upper()] = {
                        "drive": f"{letter.upper()}:",
                        "remote": remote,
                        "user": user,
                        "sid": "CURRENT_USER",
                    }
    except OSError:
        pass

    # 兜底 2：配置里显式声明的「盘符 ↔ UNC」清单
    # （注册表条目被误删、或机器重启后会话里没有任何映射时，全靠它重建）
    for cfg in load_configured_mappings():
        key = cfg["drive"].upper().rstrip(":")
        if key not in found:
            found[key] = {
                "drive": cfg["drive"],
                "remote": cfg["remote"],
                "user": "",
                "sid": "CONFIG",
                "source": "config",
            }

    # 兜底 1：注册表里没有的，用当前会话里真实连着的网络盘补齐
    # （历史 ``net use X: /delete`` 会抹掉持久条目 → 只看注册表会「一片空白」）
    for live in list_live_mappings():
        key = live["drive"].upper().rstrip(":")
        if key not in found:
            found[key] = live

    return sorted(found.values(), key=lambda x: x["drive"])


def probe_path(path: str, timeout: float = 6.0) -> bool:
    """带超时的路径可达性探测（守护线程，网络盘无响应时按时返回 False）。"""
    box = {"ok": False}

    def _work() -> None:
        try:
            box["ok"] = os.path.isdir(path)
        except Exception:  # noqa: BLE001
            box["ok"] = False

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout)
    return bool(box["ok"])


def is_connected(drive: str, timeout: float = 6.0) -> bool:
    if not IS_WINDOWS:
        return False
    return probe_path(drive.rstrip("\\/") + "\\", timeout=timeout)


def set_credentials(target: str, user: str, password: str, timeout: float = 20.0) -> tuple[bool, str]:
    """保存 SMB 凭据。

    ``target`` 可以是主机名（``dragon``）、IP（``192.168.10.112``）或 ``*``（通配）。
    主通道是本机 JSON（任意会话可用）；同时尽力写一次凭据管理器（交互式会话有效）。
    """
    if not IS_WINDOWS:
        return False, "非 Windows 平台"
    target = (target or "").strip()
    if not target:
        return False, "target 不能为空"

    json_ok = save_credentials(target, user, password)
    code, out = _run(
        ["cmdkey", f"/add:{target}", f"/user:{user}", f"/pass:{password}"], timeout
    )
    msg = _mask(out or f"退出码 {code}", password).strip()
    if code == 0:
        return json_ok, "凭据已保存（本机配置 + 凭据管理器）"
    if json_ok:
        return True, f"凭据已保存到本机配置；凭据管理器写入被拒（{msg}）"
    return False, f"保存失败：{msg}"


def delete_credentials(target: str, timeout: float = 20.0) -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "非 Windows 平台"
    code, out = _run(["cmdkey", f"/delete:{target}"], timeout)
    return code == 0, out or f"退出码 {code}"


def _is_name_in_use(text: str) -> bool:
    """``net use`` 的报错是否属于「本地设备名已在使用中 / 多重连接」（错误 85 / 1219）。"""
    t = text or ""
    low = t.lower()
    return (
        "错误 85" in t
        or "error 85" in low
        or "1219" in t
        or "multiple connections" in low
        or "多重连接" in t
        or "已在使用中" in t
    )


def connect(
    drive: str,
    remote: str,
    timeout: float = 25.0,
    user: "str | None" = None,
    password: "str | None" = None,
) -> tuple[bool, str]:
    """在当前进程所在会话里建立映射。

    未显式给凭据时，会自动从本机凭据配置里按 UNC 主机查找并用 ``/user:`` 传入 ——
    这样即使凭据管理器不可用（非交互会话），也能连上共享。

    ⚠️ **不要一上来就 ``net use <盘符> /delete``**：那会把注册表里的持久映射条目
    一并抹掉，下次启动就「没有东西可重连」了。这里先用 ``/persistent:yes`` 直接
    重建（Windows 会更新同名持久条目），只有碰到错误 85 才删了重来。
    """
    if not IS_WINDOWS:
        return False, "非 Windows 平台"
    letter = drive.rstrip(":\\/").upper() + ":"
    if is_connected(letter, timeout=4.0):
        return True, "已连接"

    if user is None and password is None:
        found = credential_for(remote)
        if found:
            user, password = found

    def _args() -> list[str]:
        if user:
            if password:
                return ["net", "use", letter, remote, password, f"/user:{user}", "/persistent:yes"]
            return ["net", "use", letter, remote, f"/user:{user}", "/persistent:yes"]
        return ["net", "use", letter, remote, "/persistent:yes"]

    code, out = _run(_args(), timeout)
    if code != 0 and _is_name_in_use(out):
        logger.info("[net] %s 盘符残留占用，先删除再重建", letter)
        _run(["net", "use", letter, "/delete", "/y"], 8.0)
        code, out = _run(_args(), timeout)

    if code == 0 and is_connected(letter, timeout=4.0):
        return True, "已连接"
    detail = _mask(out, password).strip()
    if not detail:
        detail = "退出码 %s" % code
    elif user:
        detail = f"[以 {user} 连接] {detail}"
    return False, detail


def disconnect(drive: str, timeout: float = 15.0) -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "非 Windows 平台"
    letter = drive.rstrip(":\\/").upper() + ":"
    code, out = _run(["net", "use", letter, "/delete", "/y"], timeout)
    return code == 0, out or f"退出码 {code}"


def status(probe_timeout: float = 4.0) -> list[dict[str, Any]]:
    """列出持久映射及其当前连接状态（不尝试重连）。"""
    out = []
    for m in list_persistent_mappings():
        item = dict(m)
        item["connected"] = is_connected(m["drive"], timeout=probe_timeout)
        out.append(item)
    return out


def repersist(drive: str, remote: str, timeout: float = 20.0) -> tuple[bool, str]:
    """把「当前已连上但注册表里没有」的映射重新写成持久条目。

    场景：历史上有人跑过 ``net use X: /delete``，映射还在会话里，但 HKCU\\Network
    的条目没了 —— 一旦重启机器就再也连不上。这里用同一条 ``net use``（带
    ``/persistent:yes``）把条目补回来。
    """
    if not IS_WINDOWS:
        return False, "非 Windows 平台"
    letter = drive.rstrip(":\\/").upper() + ":"
    found = credential_for(remote)
    user, password = found if found else (None, None)
    if user and password:
        args = ["net", "use", letter, remote, password, f"/user:{user}", "/persistent:yes"]
    elif user:
        args = ["net", "use", letter, remote, f"/user:{user}", "/persistent:yes"]
    else:
        args = ["net", "use", letter, remote, "/persistent:yes"]
    code, out = _run(args, timeout)
    detail = _mask(out, password).strip() or f"退出码 {code}"
    return code == 0, detail


def ensure_all(probe_timeout: float = 4.0, connect_timeout: float = 25.0) -> list[dict[str, Any]]:
    """把「持久映射但当前不可用」的网络盘全部重连，并补回丢失的持久条目。返回逐项结果。"""
    if not IS_WINDOWS:
        return []
    results: list[dict[str, Any]] = []
    for m in list_persistent_mappings():
        item = dict(m)
        if is_connected(m["drive"], timeout=probe_timeout):
            item["connected"] = True
            item["message"] = "已连接"
            # 只在会话/配置里存在、注册表里没有 → 顺手补回持久条目
            if m.get("source") in ("live", "config"):
                ok, msg = repersist(m["drive"], m["remote"])
                item["message"] = "已连接（持久条目已补回）" if ok else f"已连接（持久条目补回失败: {msg}）"
        else:
            ok, msg = connect(m["drive"], m["remote"], timeout=connect_timeout)
            item["connected"] = ok
            item["message"] = msg
        results.append(item)
        logger.info(
            "[net] %s -> %s : %s", item["drive"], item["remote"],
            "OK" if item["connected"] else f"失败({item['message']})",
        )
    return results


def mount_unc(unc: str, timeout: float = 10.0) -> tuple[bool, str]:
    """无盘符直连一个 UNC 路径（用于按需认证，等价于 net use <unc>）。"""
    if not IS_WINDOWS:
        return False, "非 Windows 平台"
    unc = (unc or "").strip()
    if not unc.startswith("\\\\"):
        return False, "不是合法的 UNC 路径"
    found = credential_for(unc)
    if found:
        user, password = found
        _run(["net", "use", unc, "/delete", "/y"], 8.0)
        if password:
            args = ["net", "use", unc, password, f"/user:{user}", "/persistent:no"]
        else:
            args = ["net", "use", unc, f"/user:{user}", "/persistent:no"]
    else:
        args = ["net", "use", unc, "/persistent:no"]
    code, out = _run(args, timeout)
    ok = code == 0 or probe_path(unc, timeout=5.0)
    detail = _mask(out or ("已连接" if ok else f"退出码 {code}"), found[1] if found else None)
    return ok, detail.strip()
