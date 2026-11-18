# PATTERN: util — 新日创建(动态 day-one baseline + 星期干支 + 骨架文件)，从 god module 抽出
# USE WHEN: 改 "第N天" baseline 解析优先级 / 改新日模板骨架 / 改 day-one 中文数字表
# COPY THIS: 无 — 本模块是 server.py §18(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-22, 清册01-§18,Parallel Change expand):
# - 原址 server.py "第N天 baseline" 段(_DAY_CN.._new_day_create),函数体逐字节照搬。
# - 跨模块引用(load_config / _list_journal_files / JOURNAL_DIR / VAULT_DIR / _pretty_rel)
#   改为窄参数注入，server 适配器保持 call-time patch 语义 —
#   tests/test_day_one_and_water_cup.py 的 isolated_vault fixture
#   monkeypatch.setattr(server, "JOURNAL_DIR", ...) + monkeypatch.setattr(server,
#   "load_config", ...) 依赖这条 call-time resolve,顶层 import 会漏接。
# - journal_routes.py:49 `from server import datetime, _new_day_create` 是函数体内
#   lazy import,零改动(patch-where-used 天然兼容)。
from datetime import datetime

# "第N天" baseline:新用户用自己 vault 里最早的 schedule 日为 day-one,
# 没有 schedule 文件就是当天 = 第一天。早期 vault 最早是某个起始日,所以
# 他的 day-one 仍是 5.3,backward compat;陌生新用户装机当天就是第一天。
# 也可以在 .gateway-config.json 里写 "vault_day_one": "YYYY-MM-DD" 显式覆盖。
_DAY_CN = ["零","一","二","三","四","五","六","七","八","九","十",
           "十一","十二","十三","十四","十五","十六","十七","十八","十九","二十",
           "二十一","二十二","二十三","二十四","二十五","二十六","二十七","二十八","二十九","三十"]


def _get_day_one(
    today_iso: str,
    *,
    load_config,
    list_journal_files,
) -> datetime:
    """动态算 day-one。优先级:config 显式 > vault 最早 schedule > 今天。"""
    cfg = load_config() or {}
    explicit = cfg.get("vault_day_one")
    if explicit:
        try:
            return datetime.strptime(explicit, "%Y-%m-%d")
        except ValueError:
            pass  # bad format → 走 fallback
    # 扫 vault 最早 schedule 文件
    try:
        days = list_journal_files()
        if days:
            earliest_iso = days[0].get("date", today_iso)
            return datetime.strptime(earliest_iso, "%Y-%m-%d")
    except Exception:
        pass
    # 兜底:今天就是第一天
    return datetime.strptime(today_iso, "%Y-%m-%d")


def _new_day_create(
    date_iso: str,
    *,
    get_day_one,
    journal_dir,
    vault_dir,
    pretty_rel,
) -> dict:
    """Python 原生 new-day(替代 scripts/new-day.sh;frozen 模式下脚本不在,改这里)。
    返 {ok, created, file, message}。已存在返 created=False。"""
    try:
        target = datetime.strptime(date_iso, "%Y-%m-%d")
    except ValueError:
        return {"ok": False, "error": f"bad date: {date_iso}"}
    day_one = get_day_one(date_iso)
    day_num = (target - day_one).days + 1
    day_cn = _DAY_CN[day_num] if 0 <= day_num <= 30 else str(day_num)
    yy = target.strftime("%y")
    mm = target.month  # 不补零
    dd = target.day
    filename = f"{yy}.{mm}.{dd}(第{day_cn}天).md"
    journal_dir.mkdir(parents=True, exist_ok=True)
    filepath = journal_dir / filename
    if filepath.exists():
        return {"ok": True, "created": False, "file": pretty_rel(filepath),
                "message": f"already exists: {filename}"}
    # 顶部 daily-task section:从 vault/daily-tasks.md 第一个 --- 前抓
    daily_tasks_src = vault_dir / "daily-tasks.md"
    if daily_tasks_src.exists():
        src = daily_tasks_src.read_text(encoding="utf-8")
        top = []
        for line in src.splitlines():
            if line.strip() == "---":
                break
            top.append(line)
        top_section = "\n".join(top).rstrip()
    else:
        # 与移动端 suppTemplate() 字节同源 — 两端全新安装长出同一份初始 md(改一边必须同步另一边)
        top_section = (
            "# 每日打卡\n\n"
            "<!-- 想加打卡项(运动 / 阅读 / 冥想 / 补剂...)?跟 AI 说一声就行 -->\n\n"
            "- [ ] 喝水\n"
            "  - [ ] 1\n"
            "  - [ ] 2\n"
            "  - [ ] 3\n"
            "  - [ ] 4\n"
            "  - [ ] 5\n"
            "  - [ ] 6\n"
            "  - [ ] 7\n"
            "  - [ ] 8\n"
            "- [ ] (添加你的第一个打卡项)"
        )
    # 时间格(7:30 - 23:00,半小时一块,7:00 没有)
    parts = [top_section, "\n---"]
    for h in range(7, 23):
        for m in ("00", "30"):
            if h == 7 and m == "00":
                continue
            parts.append(f"\n# {h}：{m}\n\n##\n\n---")
    parts.append("\n# 23：00\n\n##\n")
    filepath.write_text("\n".join(parts), encoding="utf-8")
    return {"ok": True, "created": True, "file": pretty_rel(filepath),
            "message": f"created: {filename}"}
