"""Vault location status, discovery and selection routes."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

import vault_config

router = APIRouter(tags=["vault-config"])

_DATA_HOME = None


def configure_effects(*, data_home) -> None:
    global _DATA_HOME
    _DATA_HOME = data_home


@router.get("/api/vault")
def vault_status():
    return {
        "active_vault": str(_DATA_HOME()),
        "known_vaults": vault_config.list_known(),
        "setup_required": vault_config.setup_required(),
        "config_path": str(vault_config.config_path()),
    }


@router.get("/api/vault/discover_obsidian")
def vault_discover_obsidian():
    return {"vaults": vault_config.discover_obsidian_vaults()}


@router.post("/api/vault/set")
async def vault_set(req: Request):
    body = await req.json()
    path = (body.get("path") or "").strip()
    name = (body.get("name") or "").strip()
    if not path:
        raise HTTPException(400, "need path")
    target = Path(path).expanduser().resolve()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as error:
        raise HTTPException(
            400,
            f"cannot create vault dir: {error}",
        )
    if not target.is_dir():
        raise HTTPException(400, f"path is not a directory: {target}")
    try:
        probe = target / ".human-ai-write-test"
        probe.write_text("ok")
        probe.unlink()
    except Exception as error:
        raise HTTPException(400, f"vault not writable: {error}")
    config = vault_config.set_active(str(target), name)
    needs_restart = str(target) != str(_DATA_HOME())
    return {
        "ok": True,
        "active_vault": config["active_vault"],
        "needs_restart": needs_restart,
        "hint": (
            "新 vault 已写入 config。重启 gateway server 生效。"
            if needs_restart
            else "vault 已确认。"
        ),
    }
