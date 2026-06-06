"""
vault_config.py — Obsidian-style vault location 管理

OS 级 config 文件:
  Mac:   ~/Library/Application Support/human-ai/config.json
  Linux: ~/.config/human-ai/config.json
  Win:   %APPDATA%\\human-ai\\config.json

格式:
  {
    "active_vault": "/abs/path/to/vault_root",
    "known_vaults": [
      {"name": "personal", "path": "/abs/path"},
      ...
    ],
    "version": 1
  }

vault_root 内部结构:
  {root}/vault/                — 日记 md / 标签聚合 / PULSE / attachments
  {root}/data/                 — daily-task images / scrapbook json/imgs
  {root}/config/               — gateway-config.json (LLM keys)

(active_vault 指向 root,不是 root/vault。注意区别。)

resolve 优先级(打破任意一项即用):
  1. HUMAN_AI_HOME 环境变量(开发覆盖)
  2. config.json 里 active_vault
  3. 默认 ~/.human-ai
"""
from __future__ import annotations

import json
import os
import platform
from pathlib import Path


def _config_dir() -> Path:
    sysname = platform.system()
    if sysname == "Darwin":
        return Path.home() / "Library" / "Application Support" / "human-ai"
    if sysname == "Windows":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "human-ai"
        return Path.home() / "AppData" / "Roaming" / "human-ai"
    # Linux & 其他
    xdg = os.getenv("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".config")
    return base / "human-ai"


def config_path() -> Path:
    return _config_dir() / "config.json"


def load() -> dict:
    """读 vault config。
    主文件不存在 → 返空 dict(走 setup wizard)。
    主文件损坏 → 重命名为 .corrupted.<ts>(保留诊断) + 返空 dict 走 setup wizard
                 (而非 silent return {} 导致用户以为 vault 切到默认 ~/.human-ai)。
    """
    p = config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        try:
            import time as _time
            ts = int(_time.time())
            corrupted = p.with_name(f"{p.name}.corrupted.{ts}")
            p.rename(corrupted)
        except Exception:
            pass  # 重命名失败也只能继续
        return {}


def save(cfg: dict) -> None:
    """atomic tmp+replace,中途崩 = 主文件保持上一致状态,不会 0 字节化。
    (不复用 server.py:_safe_write_text,避免 vault_config → server.py 循环依赖。)
    """
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(p))


def resolve_vault_root() -> Path:
    """启动时调一次。返当前 active vault root(绝对路径)。"""
    env = os.getenv("HUMAN_AI_HOME")
    if env:
        return Path(env).expanduser().resolve()
    cfg = load()
    active = cfg.get("active_vault")
    if active:
        return Path(active).expanduser().resolve()
    return (Path.home() / ".human-ai").resolve()


def setup_required() -> bool:
    """返 true 表示前端要弹 vault 选择 modal:没 config 文件 + 没 env var。"""
    if os.getenv("HUMAN_AI_HOME"):
        return False
    return not config_path().exists()


def list_known() -> list:
    return load().get("known_vaults", [])


def set_active(path: str, name: str = "") -> dict:
    """切换/新建 vault。落到 known_vaults + active_vault。
    返新 cfg。不验证目录(由 caller 验证可读写)。
    """
    p = Path(path).expanduser().resolve()
    cfg = load()
    known = cfg.get("known_vaults", [])
    if not any(v.get("path") == str(p) for v in known):
        known.append({"name": name or p.name, "path": str(p)})
    cfg["known_vaults"] = known
    cfg["active_vault"] = str(p)
    cfg["version"] = 1
    save(cfg)
    return cfg


def discover_obsidian_vaults() -> list:
    """读 Obsidian 自己 config 拿用户已建的 vault 列表。失败返 []。
    (Mac: ~/Library/Application Support/obsidian/obsidian.json)
    """
    sysname = platform.system()
    if sysname == "Darwin":
        p = Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    elif sysname == "Windows":
        appdata = os.getenv("APPDATA")
        p = Path(appdata) / "obsidian" / "obsidian.json" if appdata else None
    else:
        p = Path.home() / ".config" / "obsidian" / "obsidian.json"
    if not p or not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        out = []
        for vid, v in (data.get("vaults") or {}).items():
            vpath = v.get("path")
            if not vpath:
                continue
            out.append({
                "name": Path(vpath).name,
                "path": vpath,
                "currently_open": bool(v.get("open")),
                "_obsidian_id": vid,
            })
        return out
    except Exception:
        return []
