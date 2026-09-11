#!/usr/bin/env python3
"""
每日模拟投注单自动生成 + 前端JSON导出 + GitHub推送
- 复用 jc_simulation.py 的决策/结算逻辑
- 将 state.json 转换为前端需要的3个JSON文件
- 通过 GitHub Contents API 推送到仓库

用法:
  python daily_auto_bet.py [result_mode] [capital]
  - result_mode: display_only | notify | auto (默认 display_only)
  - capital: 初始本金 (默认 10000)
"""

import asyncio
import sys
import os
import json
import base64
import traceback
from datetime import datetime, timedelta, timezone

# ─── 路径自动探测 ────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 脚本在 <cwd>/codeact/scripts/ → fp-repo 在 <cwd>/fp-repo/
CWD = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
FP_REPO = os.path.join(CWD, "fp-repo")

# 验证仓库根目录
if not os.path.isdir(os.path.join(FP_REPO, "data")):
    # 兜底：脚本可能直接在 fp-repo/codeact/scripts/ 下
    FP_REPO = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
    if not os.path.isdir(os.path.join(FP_REPO, "data")):
        print(f"[ERROR] 无法定位 fp-repo 根目录, 尝试了:")
        print(f"  1. {os.path.join(CWD, 'fp-repo')}")
        print(f"  2. {CWD}")
        sys.exit(1)

print(f"[路径] FP_REPO = {FP_REPO}")

# ─── 在 import jc_simulation 之前 patch 路径 ─────────────────
# jc_simulation 的模块级常量
KELLY_DATA_DIR = os.path.join(FP_REPO, "data", "500com_daily")
STATE_DIR = os.path.join(FP_REPO, "data", "jc_simulation")
SCHEDULE_PATH = os.path.join(FP_REPO, "schedule.json")

# 将 scripts 目录加入 sys.path 以便 import
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Patch jc_simulation 模块路径
import jc_simulation
jc_simulation.KELLY_DATA_DIR = KELLY_DATA_DIR
jc_simulation.STATE_DIR = STATE_DIR
jc_simulation.STATE_FILE = os.path.join(STATE_DIR, "state.json")
jc_simulation.OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "output")

# Patch load_schedule_results 中的硬编码路径
_orig_load_schedule = jc_simulation.load_schedule_results
def _patched_load_schedule(date_iso: str) -> dict:
    results = {}
    if not os.path.exists(SCHEDULE_PATH):
        return results
    try:
        with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for m in data.get("matches", []):
            if m.get("completed") and m.get("jcNum") and m.get("homeScore") is not None:
                match_date = m.get("date", "")[:10]
                if match_date == date_iso:
                    results[m["jcNum"]] = {
                        "home_score": m.get("homeScore", 0),
                        "away_score": m.get("awayScore", 0),
                    }
    except Exception as e:
        print(f"[WARN] 读取schedule.json失败: {e}")
    return results

jc_simulation.load_schedule_results = _patched_load_schedule

# 现在安全导入所需函数
from jc_simulation import (
    CST, now_cst, today_str, today_iso, DIR_NAMES,
    load_state, save_state, next_bet_id,
    load_kelly_data, fetch_zgzcw_jc_matches,
    make_bet_decisions, build_bet_record, build_parlay_bets,
    check_pending_bets, settle_bet, get_score_map,
    format_daily_summary, analyze_kelly_signal,
)

# ─── SDK ─────────────────────────────────────────────────────
from codeact_sdk import CodeActSDK

# ─── 前端 JSON 转换逻辑 ─────────────────────────────────────

# 方向代码 → 中文
DIR_TO_CN = {"w": "胜", "d": "平", "l": "负"}

# 前端 PLAY_NAMES 映射
# had = 胜平负, hhad = 让球胜平负
PLAY_HAD = "had"
PLAY_HHAD = "hhad"


def _get_play_type(bet: dict) -> str:
    """判断玩法类型: had/hhad"""
    for m in bet.get("matches", []):
        if m.get("handicap") and m["handicap"] != 0:
            return PLAY_HHAD
    return PLAY_HAD


def _get_parlay_type(bet: dict) -> str:
    """判断串关类型: single/parlay_2/parlay_3/..."""
    if bet.get("type") == "parlay":
        n = len(bet.get("matches", []))
        return f"parlay_{n}"
    return "single"


def _build_selections(match_info: dict) -> list:
    """构建中文选项列表，如 ['胜'], ['胜','平'], ['让-1负']"""
    codes = match_info.get("selection_codes", [])
    handicap = match_info.get("handicap", 0)
    selections = []

    if handicap and handicap != 0:
        # 让球玩法: 选项带让球数
        for code in codes:
            cn = DIR_TO_CN.get(code, code)
            selections.append(f"让{handicap}{cn}")
    else:
        for code in codes:
            cn = DIR_TO_CN.get(code, code)
            selections.append(cn)

    return selections


def bet_to_frontend_json(bet: dict) -> dict:
    """将 state 中的 bet 记录转换为前端 predictions/bets/<date>.json 格式"""
    play_type = _get_play_type(bet)
    parlay_type = _get_parlay_type(bet)

    # 状态
    if bet.get("result") is not None:
        status = "settled"
        win = bool(bet.get("win", False))
    else:
        status = "pending"
        win = None

    # 金额(元→分)
    total_stake_fen = int(round(bet.get("total_stake", 0) * 100))
    max_prize_fen = int(round(bet.get("expected_return_if_all_win", 0) * 100))

    # 比赛列表
    matches = []
    for m in bet.get("matches", []):
        matches.append({
            "matchNumStr": m.get("id", ""),
            "match_id": m.get("id", ""),
            "home": m.get("home", ""),
            "away": m.get("away", ""),
            "selections": _build_selections(m),
        })

    return {
        "parlay_type": parlay_type,
        "play_type": play_type,
        "status": status,
        "win": win,
        "combos": bet.get("combos", 1),
        "multiplier": bet.get("multiplier", 1),
        "total_stake_fen": total_stake_fen,
        "max_prize_fen": max_prize_fen,
        "matches": matches,
    }


def build_daily_bets_json(bets: list) -> dict:
    """构建 predictions/bets/<YYYYMMDD>.json"""
    return {
        "bets": [bet_to_frontend_json(b) for b in bets]
    }


def build_stats_json(state: dict) -> dict:
    """构建 data/bet_sim/stats.json"""
    completed = state.get("completed_bets", [])
    pending = state.get("pending_bets", [])
    initial_capital = state.get("initial_capital", 10000)
    current_capital = state.get("current_capital", 10000)

    # ── overall ──
    total_stake_fen = 0
    total_return_fen = 0
    total_bets = 0
    win_bets = 0

    for b in completed:
        total_stake_fen += int(round(b.get("total_stake", 0) * 100))
        total_return = b.get("total_return", 0) or 0
        total_return_fen += int(round(total_return * 100))
        total_bets += 1
        if b.get("win"):
            win_bets += 1

    pnl_fen = total_return_fen - total_stake_fen
    roi_pct = round(pnl_fen / total_stake_fen * 100, 2) if total_stake_fen > 0 else 0
    win_rate_pct = round(win_bets / total_bets * 100, 1) if total_bets > 0 else 0

    overall = {
        "total_stake_fen": total_stake_fen,
        "total_return_fen": total_return_fen,
        "pnl_fen": pnl_fen,
        "roi_pct": roi_pct,
        "total_bets": total_bets,
        "win_bets": win_bets,
        "win_rate_pct": win_rate_pct,
        "pending_count": len(pending),
    }

    # ── groups: 按 play_type + parlay_type 分组 ──
    group_map = {}  # key: (play_type, parlay_type)
    PARLAY_CN = {"single": "单关", "parlay_2": "2串1", "parlay_3": "3串1", "parlay_4": "4串1"}
    PLAY_CN = {"had": "胜平负", "hhad": "让球胜平负"}

    for b in completed:
        pt = _get_play_type(b)
        plt = _get_parlay_type(b)
        key = (pt, plt)
        if key not in group_map:
            group_map[key] = {
                "play_type": pt,
                "play_name": PLAY_CN.get(pt, pt),
                "parlay_type": plt,
                "parlay_name": PARLAY_CN.get(plt, plt),
                "bet_count": 0,
                "win_count": 0,
                "total_stake_fen": 0,
                "total_return_fen": 0,
            }
        g = group_map[key]
        g["bet_count"] += 1
        if b.get("win"):
            g["win_count"] += 1
        g["total_stake_fen"] += int(round(b.get("total_stake", 0) * 100))
        g["total_return_fen"] += int(round((b.get("total_return", 0) or 0) * 100))

    groups = []
    for g in group_map.values():
        g_pnl = g["total_return_fen"] - g["total_stake_fen"]
        g_roi = round(g_pnl / g["total_stake_fen"] * 100, 2) if g["total_stake_fen"] > 0 else 0
        g_wr = round(g["win_count"] / g["bet_count"] * 100, 1) if g["bet_count"] > 0 else 0
        groups.append({
            "play_type": g["play_type"],
            "play_name": g["play_name"],
            "parlay_type": g["parlay_type"],
            "parlay_name": g["parlay_name"],
            "bet_count": g["bet_count"],
            "win_rate_pct": g_wr,
            "total_stake_fen": g["total_stake_fen"],
            "total_return_fen": g["total_return_fen"],
            "pnl_fen": g_pnl,
            "roi_pct": g_roi,
        })

    # ── daily: 按日期汇总 ──
    daily_map = {}  # key: date_str(YYYYMMDD)
    for b in completed:
        d = b.get("date", "")
        if not d:
            continue
        if d not in daily_map:
            daily_map[d] = {
                "stat_date": d,
                "bets": 0,
                "wins": 0,
                "stakes_fen": 0,
                "returns_fen": 0,
                "pnl_fen": 0,
            }
        dd = daily_map[d]
        dd["bets"] += 1
        if b.get("win"):
            dd["wins"] += 1
        dd["stakes_fen"] += int(round(b.get("total_stake", 0) * 100))
        dd["returns_fen"] += int(round((b.get("total_return", 0) or 0) * 100))

    for dd in daily_map.values():
        dd["pnl_fen"] = dd["returns_fen"] - dd["stakes_fen"]

    daily = sorted(daily_map.values(), key=lambda x: x["stat_date"])

    # ── last_30_curve: 最近30天累计PnL ──
    # 按日期排序计算累计
    cum_pnl = 0
    all_daily_sorted = sorted(daily_map.values(), key=lambda x: x["stat_date"])
    # 取最近30天
    last_30 = all_daily_sorted[-30:] if len(all_daily_sorted) > 30 else all_daily_sorted
    last_30_curve = []
    running_pnl = 0
    for dd in all_daily_sorted:
        running_pnl += dd["pnl_fen"]
    # 只保留最近30天
    if len(all_daily_sorted) > 30:
        start_pnl = sum(d["pnl_fen"] for d in all_daily_sorted[:-30])
    else:
        start_pnl = 0
    running_pnl = start_pnl
    for dd in last_30:
        running_pnl += dd["pnl_fen"]
        last_30_curve.append({
            "date": dd["stat_date"],
            "cumulative_pnl_fen": running_pnl,
        })

    return {
        "generated_at": now_cst().isoformat(),
        "overall": overall,
        "groups": groups,
        "daily": daily,
        "last_30_curve": last_30_curve,
    }


def build_bets_json(state: dict) -> dict:
    """构建 data/bet_sim/bets.json (近期投注列表)"""
    all_bets = list(state.get("completed_bets", [])) + list(state.get("pending_bets", []))
    # 按日期倒序
    all_bets.sort(key=lambda b: b.get("date", ""), reverse=True)
    # 最近50条
    recent = all_bets[:50]

    bets_out = []
    for b in recent:
        play_type = _get_play_type(b)
        parlay_type = _get_parlay_type(b)

        if b.get("result") is not None:
            status = "settled"
            win = bool(b.get("win", False))
            pnl_fen = int(round((b.get("pnl", 0) or 0) * 100))
        else:
            status = "pending"
            win = None
            pnl_fen = 0

        # 格式化日期
        bet_date_raw = b.get("date", "")
        if len(bet_date_raw) == 8:
            bet_date = f"{bet_date_raw[:4]}-{bet_date_raw[4:6]}-{bet_date_raw[6:8]}"
        else:
            bet_date = bet_date_raw

        matches = []
        for m in b.get("matches", []):
            matches.append({
                "matchNumStr": m.get("id", ""),
                "matchId": m.get("id", ""),
                "home": m.get("home", ""),
                "away": m.get("away", ""),
            })

        bets_out.append({
            "play_type": play_type,
            "parlay_type": parlay_type,
            "status": status,
            "win": win,
            "pnl_fen": pnl_fen,
            "bet_date": bet_date,
            "combos": b.get("combos", 1),
            "multiplier": b.get("multiplier", 1),
            "matches": matches,
        })

    return {
        "generated_at": now_cst().isoformat(),
        "total": len(bets_out),
        "bets": bets_out,
    }


# ─── 写入本地文件 ────────────────────────────────────────────

def write_json_file(rel_path: str, data: dict) -> str:
    """写入 JSON 文件到 fp-repo 目录下，返回完整路径"""
    full_path = os.path.join(FP_REPO, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[写入] {rel_path} ({os.path.getsize(full_path)} bytes)")
    return full_path


def export_all_jsons(state: dict, today: str, today_bets: list) -> dict:
    """
    将 state 导出为前端需要的3个JSON文件
    返回 {file_path: rel_path} 映射
    """
    results = {}

    # 1. predictions/bets/<YYYYMMDD>.json - 当日模拟单
    # 包含今日 pending + 今日已结算的
    today_all_bets = []
    for b in state.get("pending_bets", []):
        if b.get("date") == today:
            today_all_bets.append(b)
    for b in state.get("completed_bets", []):
        if b.get("date") == today:
            today_all_bets.append(b)

    # 如果今天没新注，但有传入的 today_bets 也用
    if not today_all_bets and today_bets:
        today_all_bets = today_bets

    daily_json = build_daily_bets_json(today_all_bets)
    results["daily_bets"] = write_json_file(
        f"predictions/bets/{today}.json", daily_json
    )

    # 2. data/bet_sim/stats.json - 战绩统计
    stats_json = build_stats_json(state)
    results["stats"] = write_json_file("data/bet_sim/stats.json", stats_json)

    # 3. data/bet_sim/bets.json - 近期投注列表
    bets_json = build_bets_json(state)
    results["bets"] = write_json_file("data/bet_sim/bets.json", bets_json)

    return results


# ─── GitHub 推送 ─────────────────────────────────────────────

def get_github_token() -> str:
    """获取 GitHub Token (不硬编码)"""
    # 1. 环境变量
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token.strip()

    # 2. 仓库根目录 .github_token 文件
    token_path = os.path.join(FP_REPO, ".github_token")
    if os.path.exists(token_path):
        with open(token_path, "r") as f:
            return f.read().strip()

    # 3. 约定路径
    home_token = os.path.expanduser("~/.github_token")
    if os.path.exists(home_token):
        with open(home_token, "r") as f:
            return f.read().strip()

    return ""


def github_push_file(token: str, repo: str, file_path: str, content: str, message: str) -> bool:
    """
    通过 GitHub Contents API 推送文件
    - file_path: 仓库内相对路径 (如 predictions/bets/20260911.json)
    - content: 文件内容字符串
    """
    import urllib.request
    import urllib.error

    api_url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }

    # 获取当前文件 sha (用于更新)
    existing_sha = None
    try:
        req = urllib.request.Request(api_url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            existing = json.loads(resp.read().decode())
            existing_sha = existing.get("sha")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            pass  # 文件不存在，新建
        else:
            print(f"[WARN] GET sha 失败 ({e.code}): {e.reason}")
    except Exception as e:
        print(f"[WARN] GET sha 异常: {e}")

    # 构建 PUT body
    content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    body = {
        "message": message,
        "content": content_b64,
    }
    if existing_sha:
        body["sha"] = existing_sha

    body_json = json.dumps(body).encode("utf-8")

    try:
        req = urllib.request.Request(api_url, data=body_json, headers=headers, method="PUT")
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            print(f"[GitHub] ✅ {file_path} → {result.get('content', {}).get('html_url', 'ok')}")
            return True
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if e.fp else ""
        print(f"[GitHub] ❌ PUT {file_path} 失败 ({e.code}): {err_body[:300]}")
        return False
    except Exception as e:
        print(f"[GitHub] ❌ PUT {file_path} 异常: {e}")
        return False


def push_all_to_github(token: str, repo: str, files: dict) -> tuple:
    """
    推送所有 JSON 文件到 GitHub
    files: {key: full_local_path}
    返回 (success_count, fail_count)
    """
    success = 0
    fail = 0
    commit_msg = f"🤖 每日模拟投注自动更新 {now_cst().strftime('%Y-%m-%d %H:%M')}"

    for key, local_path in files.items():
        # 计算仓库内相对路径
        rel_path = os.path.relpath(local_path, FP_REPO)
        # 读取文件内容
        with open(local_path, "r", encoding="utf-8") as f:
            content = f.read()

        if github_push_file(token, repo, rel_path, content, commit_msg):
            success += 1
        else:
            fail += 1

    return success, fail


# ─── 主流程 ─────────────────────────────────────────────────

GITHUB_REPO = "ceshi1986/football-predictions"


async def main():
    result_mode = sys.argv[1] if len(sys.argv) > 1 else "display_only"
    initial_capital = float(sys.argv[2]) if len(sys.argv) > 2 else 10000

    print(f"[参数] result_mode={result_mode}, initial_capital={initial_capital}")
    print(f"[路径] FP_REPO={FP_REPO}")
    print(f"[路径] KELLY_DATA_DIR={KELLY_DATA_DIR}")
    print(f"[路径] STATE_DIR={STATE_DIR}")

    sdk = CodeActSDK()

    try:
        # ── 0. 加载状态 ──
        state = load_state()
        if not state.get("initial_capital") or state.get("initial_capital") == 0:
            state["initial_capital"] = initial_capital
            state["current_capital"] = initial_capital
            print(f"[初始化] 本金={initial_capital}")

        # ── 1. 结算昨日 pending bets ──
        print("\n=== 验证pending投注 ===")
        settled_results = []
        if state.get("pending_bets"):
            completed_bets, still_pending = check_pending_bets(state)

            for bet in completed_bets:
                pnl = bet.get("pnl", 0)
                state["current_capital"] = round(state["current_capital"] + pnl, 2)
                state["total_bets"] += 1
                if bet.get("win"):
                    state["total_wins"] += 1
                state["completed_bets"].append(bet)
                settled_results.append(bet)
                print(f"  {bet['bet_id']}: {bet.get('result', '?')} PnL={pnl}")

            state["pending_bets"] = still_pending
            print(f"  已结算{len(completed_bets)}注，仍pending{len(still_pending)}注")
        else:
            print("  无pending投注")

        # ── 2. 幂等检查: 今日是否已生成 ──
        today = today_str()
        existing_today = [b for b in state.get("pending_bets", []) if b.get("date") == today]
        already_completed_today = [b for b in state.get("completed_bets", []) if b.get("date") == today]

        if existing_today:
            print(f"\n[幂等] 今日已有{len(existing_today)}注pending，跳过新投注")
            today_bets = existing_today
        elif already_completed_today:
            print(f"\n[幂等] 今日已有{len(already_completed_today)}注已结算，跳过新投注")
            today_bets = []
        else:
            # ── 3. 读取今日竞彩比赛 ──
            print("\n=== 读取今日竞彩赔率 ===")
            today_matches = fetch_zgzcw_jc_matches(today_iso())
            print(f"  今日竞彩: {len(today_matches)}场")
            open_matches = [m for m in today_matches if not m["completed"] and m.get("jc_sp")]
            print(f"  未开赛+有SP: {len(open_matches)}场")

            # ── 4. 读取Kelly数据 ──
            print("\n=== 读取Kelly数据 ===")
            kelly_data = load_kelly_data(today)
            if not kelly_data:
                yesterday_str = (now_cst() - timedelta(days=1)).strftime("%Y%m%d")
                kelly_data = load_kelly_data(yesterday_str)
                if kelly_data:
                    print(f"  使用昨日({yesterday_str})Kelly数据")
            kelly_total = kelly_data.get("total_matches", 0)
            print(f"  Kelly: {kelly_total}场")

            # ── 5. 投注决策 ──
            print("\n=== 投注决策 ===")
            decisions, strong_jc_nums = make_bet_decisions(open_matches, kelly_data)
            print(f"  决策: {len(decisions)}注 (强信号{len(strong_jc_nums)}个)")

            # ── 6. 构建投注记录 ──
            today_bets = []
            capital = state["current_capital"]

            for d in decisions:
                budget = round(capital * d.budget_pct, 2)
                match_detail = {
                    "id": d.match_id,
                    "home": d.home,
                    "away": d.away,
                    "league": d.league,
                    "selection": d.selection,
                    "selection_codes": d.selection_codes,
                    "odds": d.primary_odds,
                    "odds_map": d.odds_map,
                    "handicap": d.handicap,
                    "handicap_odds": d.handicap_odds,
                }
                bet = build_bet_record(
                    bet_id=next_bet_id(state),
                    date=today,
                    bet_type="single",
                    match_details=[match_detail],
                    signal_strength=d.signal_strength,
                    budget=budget,
                    reason=d.reason,
                )
                today_bets.append(bet)
                is_double = len(d.selection_codes) > 1
                label = "双选" if is_double else "单选"
                ev_str = f"EV={d.ev:+.1%}"
                print(f"  {d.match_id} {d.home} vs {d.away} [{d.league}] → {d.selection} | "
                      f"{label} | 赔率{d.primary_odds:.2f} | {ev_str} | {bet['multiplier']}倍×{bet['combos']}注={bet['total_stake']}元")

            # ── 7. 串关 (仅2串1) ──
            if len(strong_jc_nums) >= 2:
                parlays = build_parlay_bets(strong_jc_nums, decisions, capital)
                for p in parlays:
                    p["bet_id"] = next_bet_id(state)
                    p["date"] = today
                    today_bets.append(p)
                    match_desc = "+".join(m["id"] for m in p["matches"])
                    print(f"  [2串1] {match_desc} @ {p['combined_odds']:.2f} | "
                          f"{p['multiplier']}倍×{p['combos']}注={p['total_stake']}元")

            # ── 8. 记录到 state ──
            state["pending_bets"].extend(today_bets)
            daily_entry = {
                "date": today,
                "bets_placed": len(today_bets),
                "total_stake": sum(b["total_stake"] for b in today_bets),
                "bets": [b["bet_id"] for b in today_bets],
            }
            state.setdefault("daily_log", []).append(daily_entry)

        # ── 9. 保存状态 ──
        save_state(state)
        print(f"\n[状态] 当前资金: {state['current_capital']:.2f}元")

        # ── 10. 导出前端JSON ──
        print("\n=== 导出前端JSON ===")
        exported = export_all_jsons(state, today, today_bets)
        print(f"  导出完成: {len(exported)}个文件")

        # ── 11. 推送到GitHub ──
        print("\n=== 推送GitHub ===")
        token = get_github_token()
        if not token:
            print("[WARN] 未找到 GITHUB_TOKEN，跳过推送。JSON已写入本地。")
            print("  设置方式: export GITHUB_TOKEN=xxx 或写入 ~/.github_token")
            gh_success, gh_fail = 0, 0
        else:
            gh_success, gh_fail = push_all_to_github(token, GITHUB_REPO, exported)
            print(f"  推送结果: {gh_success}成功, {gh_fail}失败")

        # ── 12. 格式化输出 ──
        summary = format_daily_summary(state, today_bets, settled_results)
        print(f"\n{summary}")

        # 也写一份本地报告
        output_dir = os.path.join(SCRIPT_DIR, "..", "output")
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, f"jc_simulation_{today}.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(summary)
            f.write("\n\n--- 详细投注记录 ---\n")
            f.write(json.dumps(state, ensure_ascii=False, indent=2))

        # ── 13. 提交结果 ──
        actual_mode = result_mode if result_mode != "auto" else "display_only"
        push_status = "✅已推送" if gh_success > 0 and gh_fail == 0 else (
            f"⚠️部分推送({gh_success}/{gh_success+gh_fail})" if gh_success > 0 else
            "❌未推送(无Token或全部失败)" if not token else "❌推送失败"
        )

        msg_parts = [
            f"📊 每日模拟投注 {today}",
            f"💰 资金: {state['current_capital']:.0f}元",
            f"📈 盈亏: {state['current_capital'] - state['initial_capital']:+.0f}元",
            f"🎯 今日: {len(today_bets)}注",
            f"📤 {push_status}",
        ]
        message = "\n".join(msg_parts)

        try:
            await sdk.submit_result(
                result_mode=actual_mode,
                status="success",
                message=message,
                data={
                    "date": today,
                    "current_capital": state["current_capital"],
                    "pnl": round(state["current_capital"] - state["initial_capital"], 2),
                    "total_bets": state["total_bets"],
                    "total_wins": state["total_wins"],
                    "today_bets": len(today_bets),
                    "exported_files": len(exported),
                    "github_push": {"success": gh_success, "fail": gh_fail},
                    "report_path": report_path,
                },
            )
        except Exception as sdk_err:
            # SDK不可用时(非codeact环境)打印结果即可
            print(f"\n[SDK] submit_result 跳过: {sdk_err}")
            print(f"\n--- 最终结果 ---")
            print(message)

    except Exception as e:
        traceback.print_exc()
        try:
            await sdk.submit_result(
                result_mode="notify",
                status="error",
                message=f"每日模拟投注执行失败: {e}",
                data={"error_type": type(e).__name__},
            )
        except Exception:
            pass
        sys.exit(1)


asyncio.run(main())
