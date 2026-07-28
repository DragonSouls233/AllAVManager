import json
import re
import os
from pathlib import Path

RULES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "chinese_rename_rules.json")

BUILTIN_RULES = [
    # 网站/平台标记
    "!DVDEmpire", "!CHDVDEmpire", "!9Porn", "9Porn.asia",
    "CHT!BT", "!BT", "!DD", "!HD", "!SD",
    "PsychoPorn.com", "PsychoPorn", "PornHub.com", "Pornhub.com",
    "xvideos.com", "xhamster.com", "91Porn",
    # 编码/画质
    "!4K", "!1080P", "!720P", "!HD",
    # 其他
    "!UNION", "!MAX", "!PREMIUM",
]


def _default_rules():
    return {
        "version": 2,
        "builtin_enabled": True,
        "auto_record": True,
        "naming_template": "{code}.{actor}.{title}",
        "ad_rules": {
            "builtin": list(BUILTIN_RULES),
            "user_defined": [],
        },
        "auto_recorded": [],
    }


def _load_rules():
    try:
        with open(RULES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        rules = _default_rules()
        _save_rules(rules)
        return rules


def _save_rules(rules):
    os.makedirs(os.path.dirname(RULES_FILE), exist_ok=True)
    with open(RULES_FILE, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)


def get_rules():
    rules = _load_rules()
    return {
        "builtin": rules.get("ad_rules", {}).get("builtin", BUILTIN_RULES),
        "user_defined": rules.get("ad_rules", {}).get("user_defined", []),
        "auto_recorded": rules.get("auto_recorded", []),
        "builtin_enabled": rules.get("builtin_enabled", True),
        "auto_record": rules.get("auto_record", True),
        "naming_template": rules.get("naming_template", "{code}.{actor}.{title}"),
    }


def update_rules(data: dict):
    rules = _load_rules()
    if "builtin_enabled" in data:
        rules["builtin_enabled"] = data["builtin_enabled"]
    if "auto_record" in data:
        rules["auto_record"] = data["auto_record"]
    if "user_defined" in data:
        rules["ad_rules"]["user_defined"] = data["user_defined"]
    if "naming_template" in data:
        rules["naming_template"] = data["naming_template"]
    _save_rules(rules)
    return get_rules()


def clean_title(title: str) -> str:
    rules = _load_rules()
    ad_rules = []
    if rules.get("builtin_enabled", True):
        ad_rules.extend(rules.get("ad_rules", {}).get("builtin", []))
    ad_rules.extend(rules.get("ad_rules", {}).get("user_defined", []))

    for rule in ad_rules:
        title = title.replace(rule, "")

    cleaned = re.sub(r"[-_.\s]{2,}", ".", title)
    cleaned = cleaned.strip(".-_ ")

    if rules.get("auto_record", True):
        parts = re.split(r"[.!]", title)
        for part in parts:
            if _is_suspicious_ad(part):
                recorded = rules.get("auto_recorded", [])
                if not any(r["pattern"] == part for r in recorded):
                    rules["auto_recorded"].append({
                        "pattern": part,
                        "first_seen": "",
                        "file": "",
                    })
                    _save_rules(rules)
                if part not in rules.get("ad_rules", {}).get("user_defined", []):
                    rules["ad_rules"]["user_defined"].append(part)
                    _save_rules(rules)

    return cleaned


def _is_suspicious_ad(part: str) -> bool:
    part = part.strip()
    if not part:
        return False
    if re.search(r"\.(com|net|org|asia|cc|tv|xxx)$", part, re.I):
        return True
    if part.startswith("!"):
        return True
    if part.startswith("www."):
        return True
    return False
