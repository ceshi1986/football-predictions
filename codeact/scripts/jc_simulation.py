#!/usr/bin/env python3
"""
竞彩足球模拟投注系统
- 读取 zgzcw 竞彩赔率 + V4.2 Kelly信号 → 决定买什么 → 记录虚拟投注 → 赛后验证结果 → 累计追踪
- 每次运行：先验证昨日pending bets → 读取今日赔率/Kelly → 投注决策 → 记录

竞彩规则:
  - 每注2元
  - 单选=1种组合, 双选=2种组合
  - 串关组合数=各场选法数连乘
  - 总投入=倍数×组合数×2元
  - 回报=倍数×2×命中SP连乘(仅命中组合计赔)
  - 净盈亏=回报-总投入

数据源:
  1. 竞彩赛程+SP赔率: zgzcw live API
  2. Kelly指数: fp-repo/data/500com_daily/YYYYMMDD/zgzcw_kelly_data.json
  3. 比赛结果: zgzcw live API / schedule.json

用法:
  python jc_simulation.py [result_mode] [capital]
  - result_mode: display_only | auto (默认 display_only)
  - capital: 初始本金 (默认 10000)
"""

import asyncio
import sys
import os
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Optional
from pydantic import BaseModel

# ─── 安装依赖 ───────────────────────────────────────────────
def _ensure_deps():
    try:
        import bs4
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "beautifulsoup4", "requests"],
            timeout=60, capture_output=True, text=True,
        )

_ensure_deps()

import requests
from bs4 import BeautifulSoup
from codeact_sdk import CodeActSDK

# ─── SDK 工具版本 ───────────────────────────────────────────
TOOL_SCHEMA_VERSIONS = {
    "codeact_fetch_web": "v1_2c8d0580b3f93a58",
    "codeact_search_web": "v1_5ac1b0eba8c26f2a",
}

# ─── 常量 ───────────────────────────────────────────────────
CST = timezone(timedelta(hours=8))
ZGZCW_LIVE_URL = "https://live.zgzcw.com/ls/AllData.action"
KELLY_DATA_DIR = "/app/data/所有对话/主对话/fp-repo/data/500com_daily"
STATE_DIR = "/app/data/所有对话/主对话/fp-repo/data/jc_simulation"
STATE_FILE = os.path.join(STATE_DIR, "state.json")
OUTPUT_DIR = "./codeact/output"

# 竞彩投注规则
UNIT_BET = 2               # 每注2元

# 投注策略参数 (按预算比例)
STRONG_BUDGET_PCT = 0.02   # 强信号预算: 2%
MEDIUM_BUDGET_PCT = 0.02   # 中等信号预算: 2%
PARLAY_BUDGET_PCT = 0.025  # 串关预算: 2.5%
MIN_ODDS_STRONG = 1.40     # 强信号最低赔率
MAX_ODDS_STRONG = 2.50     # 强信号最高赔率
MAX_PARLAY_MATCHES = 3     # 串关最多场次
SINGLE_SELECT_CONF = 0.65  # 中等信号→单选的置信度阈值
HANDICAP_ODDS_MIN = 1.50   # 考虑让球盘的主赔上限
PARLAY_CONF_MIN = 0.70     # 串关最低置信度

# Kelly信号阈值
DISPERSION_STRONG = 0.07
DISPERSION_MEDIUM = 0.10
GAP_THRESHOLD = 0.03

DIR_NAMES = {"w": "胜", "d": "平", "l": "负"}


# ─── 工具函数 ───────────────────────────────────────────────
def now_cst() -> datetime:
    return datetime.now(CST)

def today_str() -> str:
    return now_cst().strftime("%Y%m%d")

def today_iso() -> str:
    return now_cst().strftime("%Y-%m-%d")

def clean_team_name(raw: str) -> str:
    """清洗队名：去掉排名标记、让球标记等"""
    name = re.sub(r"\[[\d]+\]", "", raw)
    name = re.sub(r"\([\-\d]+\)", "", name)
    name = re.sub(r"^\d+", "", name)
    return name.strip()


def load_state() -> dict:
    """加载状态文件"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("[WARN] state.json损坏，重新初始化")
    return {
        "initial_capital": 10000,
        "current_capital": 10000,
        "total_bets": 0,
        "total_wins": 0,
        "pending_bets": [],
        "completed_bets": [],
        "daily_log": [],
        "bet_counter": 0,
    }


def save_state(state: dict):
    """保存状态文件"""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def next_bet_id(state: dict) -> str:
    """生成下一个bet_id"""
    state["bet_counter"] = state.get("bet_counter", 0) + 1
    return f"b_{state['bet_counter']:03d}"


def load_kelly_data(date_str: str) -> dict:
    """加载指定日期的Kelly数据"""
    path = os.path.join(KELLY_DATA_DIR, date_str, "zgzcw_kelly_data.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] 读取Kelly数据失败 {path}: {e}")
    return {}


def fetch_zgzcw_jc_matches(date_iso: str) -> list:
    """从zgzcw live API抓取指定日期的竞彩比赛"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://live.zgzcw.com/jz/",
    }
    params = {"code": "201", "date": date_iso, "ajax": "true"}
    try:
        resp = requests.get(ZGZCW_LIVE_URL, params=params, headers=headers, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] 请求zgzcw竞彩数据失败: {e}")
        return []

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr", class_="matchTr")
    matches = []

    for row in rows:
        tds = row.find_all("td", recursive=False)
        if len(tds) < 10:
            continue
        try:
            jc_num = tds[0].get_text(strip=True)
            league = tds[1].get_text(strip=True)
            time_str = tds[3].get_text(strip=True)
            status_text = tds[4].get_text(strip=True)
            is_completed = status_text == "完"

            home_soup = BeautifulSoup(str(tds[5]), "html.parser")
            home_a = home_soup.find("a")
            home_name = clean_team_name(home_a.get_text(strip=True)) if home_a else clean_team_name(tds[5].get_text(strip=True))

            rq_span = home_soup.find("span", class_="rq")
            handicap = None
            if rq_span:
                rq_data = rq_span.get("rq-data", "")
                if rq_data:
                    try:
                        handicap = int(rq_data)
                    except ValueError:
                        try:
                            handicap = float(rq_data)
                        except ValueError:
                            pass

            score_text = tds[6].get_text(strip=True)
            home_score, away_score = 0, 0
            if is_completed and score_text and score_text != "-":
                m = re.match(r"(\d+)\s*-\s*(\d+)", score_text)
                if m:
                    home_score, away_score = int(m.group(1)), int(m.group(2))

            away_soup = BeautifulSoup(str(tds[7]), "html.parser")
            away_a = away_soup.find("a")
            away_name = clean_team_name(away_a.get_text(strip=True)) if away_a else clean_team_name(tds[7].get_text(strip=True))

            odds_td = tds[10] if len(tds) > 10 else None
            jc_sp = None
            jc_rqsp = None
            oupei = None

            if odds_td:
                jcsp_div = odds_td.find("div", class_="jcsp")
                if jcsp_div:
                    spans = jcsp_div.find_all("span")
                    if len(spans) >= 3:
                        try:
                            jc_sp = {
                                "w": float(spans[0].get_text(strip=True)),
                                "d": float(spans[1].get_text(strip=True)),
                                "l": float(spans[2].get_text(strip=True)),
                            }
                        except ValueError:
                            pass

                jcrqsp_div = odds_td.find("div", class_="jcrqsp")
                if jcrqsp_div:
                    spans = jcrqsp_div.find_all("span")
                    if len(spans) >= 3:
                        try:
                            jc_rqsp = {
                                "w": float(spans[0].get_text(strip=True)),
                                "d": float(spans[1].get_text(strip=True)),
                                "l": float(spans[2].get_text(strip=True)),
                            }
                        except ValueError:
                            pass

                oupei_div = odds_td.find("div", class_="oupei")
                if oupei_div:
                    spans = oupei_div.find_all("span")
                    if len(spans) >= 3:
                        try:
                            oupei = {
                                "w": float(spans[0].get_text(strip=True)),
                                "d": float(spans[1].get_text(strip=True)),
                                "l": float(spans[2].get_text(strip=True)),
                            }
                        except ValueError:
                            pass

            match = {
                "jc_num": jc_num,
                "league": league,
                "time": time_str,
                "home": home_name,
                "away": away_name,
                "completed": is_completed,
                "home_score": home_score,
                "away_score": away_score,
                "handicap": handicap,
                "jc_sp": jc_sp,
                "jc_rqsp": jc_rqsp,
                "oupei": oupei,
            }
            matches.append(match)
        except Exception as e:
            print(f"[WARN] 解析竞彩行失败: {e}")
            continue

    return matches


def load_schedule_results(date_iso: str) -> dict:
    """从schedule.json加载已完成比赛结果"""
    schedule_path = "/app/data/所有对话/主对话/fp-repo/schedule.json"
    results = {}
    if not os.path.exists(schedule_path):
        return results
    try:
        with open(schedule_path, "r", encoding="utf-8") as f:
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


# ─── Kelly信号分析 ─────────────────────────────────────────
class KellySignal(BaseModel):
    direction: str
    direction_name: str
    strength: str
    confidence: float
    dispersion: float
    reason: str


def analyze_kelly_signal(kelly_match: dict) -> Optional[KellySignal]:
    """基于V4.2框架分析Kelly信号"""
    companies = kelly_match.get("companies", {})
    if not companies:
        return None

    bet365 = companies.get("bet365")
    weide = companies.get("weide")
    libo = companies.get("libo")

    if not bet365 or not weide:
        return None

    b365_kelly = bet365.get("kelly", [])
    weide_kelly = weide.get("kelly", [])
    b365_payout = bet365.get("payout", 0.92)
    weide_payout = weide.get("payout", 0.93)

    if len(b365_kelly) < 3 or len(weide_kelly) < 3:
        return None

    dirs = ["w", "d", "l"]
    b365_min_idx = min(range(3), key=lambda i: b365_kelly[i])
    weide_min_idx = min(range(3), key=lambda i: weide_kelly[i])
    b365_min_dir = dirs[b365_min_idx]
    weide_min_dir = dirs[weide_min_idx]

    dispersion = abs(b365_kelly[b365_min_idx] - weide_kelly[weide_min_idx])
    avg_payout = (b365_payout + weide_payout) / 2

    # 方向不一致
    if b365_min_dir != weide_min_dir:
        if (b365_kelly[1] < b365_payout and weide_kelly[1] < weide_payout
                and abs(b365_kelly[1] - weide_kelly[1]) < 0.03):
            return KellySignal(
                direction="d", direction_name="平", strength="medium",
                confidence=0.55, dispersion=dispersion,
                reason=f"bet365({DIR_NAMES[b365_min_dir]})与韦德({DIR_NAMES[weide_min_dir]})分歧，但隐藏平局共识",
            )
        return KellySignal(
            direction=b365_min_dir, direction_name=DIR_NAMES[b365_min_dir],
            strength="weak", confidence=0.35, dispersion=dispersion,
            reason=f"方向分歧(b365={DIR_NAMES[b365_min_dir]},weide={DIR_NAMES[weide_min_dir]})，冷门预警",
        )

    # 方向一致
    consensus_dir = b365_min_dir
    b365_min_val = b365_kelly[b365_min_idx]
    weide_min_val = weide_kelly[weide_min_idx]
    avg_min_kelly = (b365_min_val + weide_min_val) / 2
    below_payout = avg_min_kelly < avg_payout

    other_b365 = [b365_kelly[i] for i in range(3) if i != b365_min_idx]
    other_weide = [weide_kelly[i] for i in range(3) if i != weide_min_idx]
    avg_gap = (min(other_b365) - b365_min_val + min(other_weide) - weide_min_val) / 2

    libo_draw_signal = False
    if libo:
        libo_kelly = libo.get("kelly", [])
        libo_payout = libo.get("payout", 0.90)
        if len(libo_kelly) >= 3:
            if libo_kelly[1] < libo_payout:
                libo_draw_signal = True
            libo_odds = libo.get("latest_odds", [])
            b365_odds = bet365.get("latest_odds", [])
            if len(libo_odds) >= 2 and len(b365_odds) >= 2:
                if libo_odds[1] < b365_odds[1] - 0.15:
                    libo_draw_signal = True

    if below_payout and dispersion < DISPERSION_STRONG and avg_gap >= GAP_THRESHOLD:
        strength = "strong"
        confidence = 0.80 + min(0.10, (0.07 - dispersion) * 2)
        if libo and consensus_dir == "d" and libo_draw_signal:
            confidence += 0.05
    elif below_payout and dispersion < DISPERSION_MEDIUM:
        strength = "medium"
        confidence = 0.60 + min(0.10, (0.10 - dispersion) * 2)
    elif below_payout:
        strength = "medium"
        confidence = 0.50
    else:
        strength = "weak"
        confidence = 0.35

    reason_parts = [
        f"bet365+韦德一致指向{DIR_NAMES[consensus_dir]}",
        f"离散度={dispersion:.3f}",
        f"最低Kelly={avg_min_kelly:.2f} vs 返还率={avg_payout:.2f}",
        f"差距={avg_gap:.3f}",
    ]
    if libo_draw_signal:
        reason_parts.append("立博平赔确认" if consensus_dir == "d" else "立博偏平")

    return KellySignal(
        direction=consensus_dir,
        direction_name=DIR_NAMES[consensus_dir],
        strength=strength,
        confidence=round(min(confidence, 0.95), 2),
        dispersion=round(dispersion, 3),
        reason="；".join(reason_parts),
    )


# ─── 投注决策 ───────────────────────────────────────────────
class BetDecision(BaseModel):
    match_id: str
    home: str
    away: str
    league: str
    selection: str              # "胜"/"平"/"负"/"胜+平"/"平+负"
    selection_codes: list[str]  # ["w"] / ["w","d"]
    odds_map: dict              # {"w": 1.59, "d": 3.90}
    primary_odds: float
    signal_strength: str
    budget_pct: float           # 预算比例
    reason: str
    handicap: int = 0          # 让球数(0=非让球, -1=主让1球等)
    handicap_odds: float = 0   # 让球赔率


def make_bet_decisions(matches: list, kelly_data: dict) -> tuple:
    """返回 (decisions, strong_jc_nums)"""
    decisions = []
    kelly_matches = kelly_data.get("matches", {})

    jcid_to_kelly = {}
    for _mid, km in kelly_matches.items():
        jcid = km.get("jingcai_id", "")
        if jcid:
            jcid_to_kelly[jcid] = km

    name_to_kelly = {}
    for _mid, km in kelly_matches.items():
        mname = km.get("match_name", "")
        if mname:
            name_to_kelly[mname] = km

    strong_jc_nums = []

    for match in matches:
        if match["completed"] or not match.get("jc_sp"):
            continue

        jc_num = match["jc_num"]
        home, away, league = match["home"], match["away"], match["league"]
        jc_sp = match["jc_sp"]

        # 匹配Kelly数据
        km = jcid_to_kelly.get(jc_num)
        if not km:
            km = name_to_kelly.get(f"{home} vs {away}")
        if not km:
            for mname, mkm in name_to_kelly.items():
                if home in mname and away in mname:
                    km = mkm
                    break
        if not km:
            continue

        signal = analyze_kelly_signal(km)
        if not signal or signal.strength == "weak":
            continue

        dir_to_sp = {"w": jc_sp["w"], "d": jc_sp["d"], "l": jc_sp["l"]}
        main_odds = dir_to_sp[signal.direction]

        # 强信号: 单选
        if signal.strength == "strong":
            if main_odds < MIN_ODDS_STRONG:
                if main_odds >= 1.20:
                    signal.strength = "medium"
                    signal.confidence = min(signal.confidence, 0.55)
                else:
                    continue
            elif main_odds > MAX_ODDS_STRONG:
                continue

        if signal.strength == "strong":
            handicap_val = 0
            handicap_odds_val = 0.0
            sel_dir = signal.direction
            sel_odds = main_odds
            sel_name = DIR_NAMES[signal.direction]
            # 让球盘: 赔率太低时尝试让球
            if match.get("jc_rqsp") and main_odds < HANDICAP_ODDS_MIN and main_odds >= 1.20:
                rqsp = match["jc_rqsp"]
                rq_handicap = match.get("handicap", 0)
                if rq_handicap and rq_handicap < 0:
                    rq_dir_odds = rqsp.get("l", 0)
                    if rq_dir_odds > main_odds * 1.1 and rq_dir_odds >= 1.50:
                        handicap_val = int(rq_handicap)
                        handicap_odds_val = rq_dir_odds
                        sel_odds = rq_dir_odds
                        sel_name = f"让{rq_handicap}{DIR_NAMES['l']}"
                        signal.reason += f" | 让球{rq_handicap}赔率{rq_dir_odds:.2f}"
            decisions.append(BetDecision(
                match_id=jc_num, home=home, away=away, league=league,
                selection=sel_name,
                selection_codes=[signal.direction],
                odds_map={signal.direction: sel_odds},
                primary_odds=sel_odds,
                signal_strength="strong",
                budget_pct=STRONG_BUDGET_PCT,
                reason=f"强信号: {signal.reason}",
                handicap=handicap_val,
                handicap_odds=handicap_odds_val,
            ))
            strong_jc_nums.append(jc_num)
            continue

        # 中等信号: 高信心→单选, 否则双选
        handicap_val = 0
        handicap_odds_val = 0.0

        if signal.confidence >= SINGLE_SELECT_CONF:
            # 高信心中等信号 → 单选
            sel_odds = main_odds
            sel_name = DIR_NAMES[signal.direction]
            # 让球盘: 赔率太低时尝试让球
            if match.get("jc_rqsp") and main_odds < HANDICAP_ODDS_MIN and main_odds >= 1.20:
                rqsp = match["jc_rqsp"]
                rq_handicap = match.get("handicap", 0)
                if rq_handicap and rq_handicap < 0:
                    rq_dir_odds = rqsp.get("l", 0)
                    if rq_dir_odds > main_odds * 1.1 and rq_dir_odds >= 1.50:
                        handicap_val = int(rq_handicap)
                        handicap_odds_val = rq_dir_odds
                        sel_odds = rq_dir_odds
                        sel_name = f"让{rq_handicap}{DIR_NAMES['l']}"
                        signal.reason += f" | 让球{rq_handicap}赔率{rq_dir_odds:.2f}"
            decisions.append(BetDecision(
                match_id=jc_num, home=home, away=away, league=league,
                selection=sel_name,
                selection_codes=[signal.direction],
                odds_map={signal.direction: sel_odds},
                primary_odds=sel_odds,
                signal_strength="medium",
                budget_pct=MEDIUM_BUDGET_PCT,
                reason=f"中等信号(单选@{signal.confidence:.0%}): {signal.reason}",
                handicap=handicap_val,
                handicap_odds=handicap_odds_val,
            ))
            # 加入串关候选池(需高信心)
            if signal.confidence >= PARLAY_CONF_MIN:
                strong_jc_nums.append(jc_num)
            continue

        if signal.direction == "d":
            second_dir = "w" if jc_sp["w"] < jc_sp["l"] else "l"
        else:
            second_dir = "d"

        main_odds_val = dir_to_sp[signal.direction]
        second_odds_val = dir_to_sp[second_dir]
        effective_min = min(main_odds_val, second_odds_val)
        if effective_min < 1.15:
            continue

        sel_name = f"{DIR_NAMES[signal.direction]}+{DIR_NAMES[second_dir]}"

        decisions.append(BetDecision(
            match_id=jc_num, home=home, away=away, league=league,
            selection=sel_name,
            selection_codes=[signal.direction, second_dir],
            odds_map={signal.direction: main_odds_val, second_dir: second_odds_val},
            primary_odds=main_odds_val,
            signal_strength="medium",
            budget_pct=MEDIUM_BUDGET_PCT,
            reason=f"中等信号: {signal.reason}",
        ))

    return decisions, strong_jc_nums


# ─── 构建投注记录 ──────────────────────────────────────────
def calc_combos(match_list: list) -> int:
    """计算组合数 = 各场选法数连乘"""
    combos = 1
    for m in match_list:
        combos *= len(m.get("selection_codes", [1]))
    return combos


def build_bet_record(bet_id: str, date: str, bet_type: str, match_details: list,
                     signal_strength: str, budget: float, reason: str) -> dict:
    """
    构建标准投注记录
    - combos: 组合数
    - multiplier: 倍数 (budget / combos / UNIT_BET, 向下取整, 最小1)
    - total_stake: 总投入 = multiplier × combos × 2
    """
    combos = calc_combos(match_details)
    multiplier = max(1, int(budget / (combos * UNIT_BET)))
    total_stake = multiplier * combos * UNIT_BET

    # 串关组合赔率(仅用于显示，实际结算按命中SP计算)
    combined_odds = 1.0
    for m in match_details:
        # 取主选赔率
        primary = list(m.get("odds_map", {}).values())
        combined_odds *= primary[0] if primary else m.get("odds", 1.0)

    return {
        "date": date,
        "bet_id": bet_id,
        "type": bet_type,
        "matches": match_details,
        "combos": combos,
        "multiplier": multiplier,
        "total_stake": total_stake,
        "combined_odds": round(combined_odds, 2),
        "signal_strength": signal_strength,
        "expected_return_if_all_win": round(multiplier * UNIT_BET * combined_odds, 2),
        "result": None,
        "win": None,
        "pnl": None,
        "reason": reason,
        "handicap": match_details[0].get("handicap", 0) if match_details else 0,
    }


# ─── 串关 ───────────────────────────────────────────────────
def build_parlay_bets(strong_jc_nums: list, decisions: list[BetDecision],
                      capital: float) -> list[dict]:
    """从信号比赛中组合串关(只包含单选场次)"""
    if len(strong_jc_nums) < 2:
        return []

    # 所有候选比赛的映射
    candidate_map = {d.match_id: d for d in decisions if d.match_id in strong_jc_nums}
    # 只保留单选的场次(双选不适合串关,组合数爆炸)
    single_candidates = {
        mid: d for mid, d in candidate_map.items()
        if len(d.selection_codes) == 1
    }
    if len(single_candidates) < 2:
        return []

    # 按置信度排序(高→低), 选最佳场次
    sorted_nums = sorted(
        single_candidates.keys(),
        key=lambda x: single_candidates[x].confidence if hasattr(single_candidates[x], 'confidence') else 0,
        reverse=True,
    )
    parlay_nums = sorted_nums[:MAX_PARLAY_MATCHES]
    if len(parlay_nums) < 2:
        return []

    match_details = []
    for jcn in parlay_nums:
        d = single_candidates[jcn]
        match_details.append({
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
        })

    budget = round(capital * PARLAY_BUDGET_PCT, 2)
    n = len(parlay_nums)
    parlay_label = f"{n}串1"
    bet = build_bet_record(
        bet_id=None, date=today_str(), bet_type="parlay",
        match_details=match_details, signal_strength="strong",
        budget=budget, reason=f"串关({parlay_label}): 高信心单选组合",
    )
    bet["parlay_label"] = parlay_label
    return [bet]


# ─── 验证pending bets ──────────────────────────────────────
def get_score_map() -> dict:
    """从多个来源获取已完赛比赛比分"""
    score_map = {}
    for date_iso in [today_iso(), (now_cst() - timedelta(days=1)).strftime("%Y-%m-%d")]:
        matches = fetch_zgzcw_jc_matches(date_iso)
        for m in matches:
            if m["completed"] and m.get("jc_num"):
                score_map[m["jc_num"]] = {
                    "home_score": m["home_score"],
                    "away_score": m["away_score"],
                }
        for k, v in load_schedule_results(date_iso).items():
            if k not in score_map:
                score_map[k] = v
    return score_map


def determine_result(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "w"
    elif home_score == away_score:
        return "d"
    else:
        return "l"


def settle_bet(bet: dict, score_map: dict) -> Optional[dict]:
    """
    通用结算逻辑(单关/双选/串关统一处理)

    竞彩结算规则:
    - 总投入 = multiplier × combos × 2元
    - 枚举所有组合，找出命中组合
    - 命中组合回报 = multiplier × 2 × 该组合各场命中SP连乘
    - 总回报 = 所有命中组合回报之和
    - 净盈亏 = 总回报 - 总投入
    """
    bet_copy = json.loads(json.dumps(bet))
    matches = bet_copy["matches"]
    multiplier = bet_copy["multiplier"]

    # ── 构建每场的可选方向和对应SP ──
    match_options = []  # 每场: [{dir: "w", sp: 1.59}, {dir: "d", sp: 3.90}]
    match_results = []  # 每场实际结果

    for match_info in matches:
        jc_num = match_info["id"]
        scores = score_map.get(jc_num)

        if not scores:
            return None  # 比赛未结束，无法结算

        actual = determine_result(scores["home_score"], scores["away_score"])
        # 让球盘: 调整比分后判定结果
        handicap = match_info.get("handicap", 0)
        if handicap:
            adj_home = scores["home_score"] + handicap
            adj_away = scores["away_score"]
            actual = determine_result(adj_home, adj_away)
        match_results.append({
            "jc_num": jc_num,
            "actual": actual,
            "score": f"{scores['home_score']}-{scores['away_score']}",
        })

        options = []
        for code in match_info.get("selection_codes", []):
            sp = match_info.get("odds_map", {}).get(code, 0)
            if sp == 0:
                sp = match_info.get("odds", 0)
            options.append({"dir": code, "sp": sp})
        match_options.append(options)

    # ── 枚举所有组合，找命中组合 ──
    from itertools import product as iter_product

    total_return = 0.0
    winning_combo_descs = []

    for combo in iter_product(*match_options):
        # combo: 每场选了哪个方向
        all_hit = True
        combo_sp_product = 1.0
        combo_desc_parts = []

        for i, opt in enumerate(combo):
            actual = match_results[i]["actual"]
            if opt["dir"] == actual:
                combo_sp_product *= opt["sp"]
                combo_desc_parts.append(f"{DIR_NAMES[opt['dir']]}✅")
            else:
                all_hit = False
                combo_desc_parts.append(f"{DIR_NAMES[opt['dir']]}❌")
                break  # 串关全中才算，有一场不中整组废

        if all_hit:
            # 这个组合命中了
            combo_return = multiplier * UNIT_BET * combo_sp_product
            total_return += combo_return
            winning_combo_descs.append(" ".join(combo_desc_parts))

    total_stake = bet_copy["total_stake"]
    pnl = round(total_return - total_stake, 2)

    # ── 构建结果描述 ──
    result_parts = []
    for i, mr in enumerate(match_results):
        sel_desc = matches[i].get("selection", "")
        hit = mr["actual"] in matches[i].get("selection_codes", [])
        mark = "✅" if hit else "❌"
        result_parts.append(f"{mr['jc_num']} {mr['score']} {DIR_NAMES[mr['actual']]}{mark}")

    bet_copy["result"] = " ".join(result_parts)
    bet_copy["win"] = total_return > 0
    bet_copy["pnl"] = pnl
    bet_copy["total_return"] = round(total_return, 2)

    return bet_copy


def check_pending_bets(state: dict) -> tuple:
    """验证pending bets, 返回 (completed_bets, still_pending_bets)"""
    score_map = get_score_map()
    completed = []
    still_pending = []

    for bet in state.get("pending_bets", []):
        result = settle_bet(bet, score_map)
        if result is not None:
            completed.append(result)
        else:
            still_pending.append(bet)

    return completed, still_pending


# ─── 格式化输出 ─────────────────────────────────────────────
def format_daily_summary(state: dict, today_bets: list, settled_results: list) -> str:
    """格式化每日投注摘要"""
    today = now_cst().strftime("%Y-%m-%d")
    capital = state["current_capital"]
    initial = state["initial_capital"]
    pnl = capital - initial
    pnl_pct = (pnl / initial * 100) if initial > 0 else 0
    total_bets = state["total_bets"]
    total_wins = state["total_wins"]
    hit_rate = (total_wins / total_bets * 100) if total_bets > 0 else 0

    lines = [
        f"📊 竞彩模拟投注 - {today}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 本金：{initial:.0f}元",
        f"📈 累计：{'+'if pnl>=0 else ''}{pnl:.0f}元 ({'+'if pnl>=0 else ''}{pnl_pct:.1f}%)",
        f"🎯 命中率：{hit_rate:.0f}% ({total_wins}胜/{total_bets}注)",
        f"💵 当前资金：{capital:.0f}元",
    ]

    if settled_results:
        lines.append("")
        lines.append("✅ 已结算结果：")
        for i, bet in enumerate(settled_results, 1):
            m0 = bet["matches"][0]
            if bet["type"] == "parlay":
                match_desc = "+".join(m["id"] for m in bet["matches"])
                sel_desc = "+".join(m["selection"] for m in bet["matches"])
            else:
                match_desc = m0["id"]
                sel_desc = m0.get("selection", "")
                handicap = m0.get("handicap", 0)
                if handicap:
                    sel_desc = f"让{handicap}{sel_desc}"

            pnl_str = f"+{bet['pnl']:.0f}" if bet["pnl"] >= 0 else f"{bet['pnl']:.0f}"
            is_double = "+" in sel_desc and bet["type"] == "single"
            if bet["type"] == "parlay":
                bet_label = bet.get("parlay_label", f"{len(bet['matches'])}串1")
            elif is_double:
                bet_label = "双选"
            else:
                bet_label = "单选"
            lines.append(
                f"{i}. [{bet_label}] {match_desc} {m0['home']} vs {m0['away']} → {sel_desc} | "
                f"{bet['result']} {pnl_str}元"
            )

    if today_bets:
        lines.append("")
        lines.append(f"📝 今日投注（{len(today_bets)}注）：")
        for i, bet in enumerate(today_bets, 1):
            m0 = bet["matches"][0]
            if bet["type"] == "parlay":
                match_desc = "+".join(m["id"] for m in bet["matches"])
                sel_desc = "+".join(m["selection"] for m in bet["matches"])
                parlay_label = bet.get("parlay_label", f"{len(bet['matches'])}串1")
                lines.append(
                    f"{i}. [{parlay_label}] {match_desc} → {sel_desc} @ {bet['combined_odds']} | "
                    f"{bet['multiplier']}倍×{bet['combos']}注={bet['total_stake']}元"
                )
            else:
                is_double = len(m0.get("selection_codes", [])) > 1
                handicap = m0.get("handicap", 0)
                if handicap:
                    bet_label = f"让{handicap}单选"
                else:
                    bet_label = "双选" if is_double else "单选"
                if is_double and m0.get("odds_map"):
                    odds_parts = [f"{DIR_NAMES[k]}{v:.2f}" for k, v in m0["odds_map"].items()]
                    odds_str = "/".join(odds_parts)
                else:
                    odds_str = f"@{m0['odds']:.2f}"
                lines.append(
                    f"{i}. [{bet_label}] {m0['id']} {m0['home']} vs {m0['away']} → {m0['selection']} {odds_str} | "
                    f"{bet['multiplier']}倍×{bet['combos']}注={bet['total_stake']}元"
                )
    else:
        lines.append("")
        lines.append("📝 今日投注：无符合条件的信号，空仓等待 🔄")

    return "\n".join(lines)


# ─── 主流程 ─────────────────────────────────────────────────
async def main():
    result_mode = sys.argv[1] if len(sys.argv) > 1 else "display_only"
    initial_capital = float(sys.argv[2]) if len(sys.argv) > 2 else 10000

    print(f"[参数] result_mode={result_mode}, initial_capital={initial_capital}")
    sdk = CodeActSDK()

    try:
        # ── 0. 加载状态 ──
        state = load_state()
        if not state.get("initial_capital") or state.get("initial_capital") == 0:
            state["initial_capital"] = initial_capital
            state["current_capital"] = initial_capital
            print(f"[初始化] 本金={initial_capital}")

        # ── 1. 验证pending bets ──
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
                print(f"  {bet['bet_id']}: {bet['result']} PnL={pnl}")

            state["pending_bets"] = still_pending
            print(f"  已结算{len(completed_bets)}注，仍pending{len(still_pending)}注")
        else:
            print("  无pending投注")

        # ── 2. 幂等检查 ──
        today = today_str()
        existing_today = [b for b in state.get("pending_bets", []) if b.get("date") == today]
        if existing_today:
            print(f"\n[幂等] 今日已有{len(existing_today)}注pending，跳过新投注")
            today_bets = existing_today
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
                print(f"  {d.match_id} {d.home} vs {d.away} [{d.league}] → {d.selection} | "
                      f"{label} | {bet['multiplier']}倍×{bet['combos']}注={bet['total_stake']}元")

            # ── 7. 串关 ──
            if len(strong_jc_nums) >= 2:
                parlays = build_parlay_bets(strong_jc_nums, decisions, capital)
                for p in parlays:
                    p["bet_id"] = next_bet_id(state)
                    p["date"] = today
                    today_bets.append(p)
                    match_desc = "+".join(m["id"] for m in p["matches"])
                    print(f"  [串关] {match_desc} @ {p['combined_odds']} | "
                          f"{p['multiplier']}倍×{p['combos']}注={p['total_stake']}元")

            # ── 8. 记录 ──
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

        # ── 10. 输出 ──
        summary = format_daily_summary(state, today_bets, settled_results)
        print(f"\n{summary}")

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        report_path = os.path.join(OUTPUT_DIR, f"jc_simulation_{today}.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(summary)
            f.write("\n\n--- 详细投注记录 ---\n")
            f.write(json.dumps(state, ensure_ascii=False, indent=2))

        # ── 11. 提交 ──
        actual_mode = result_mode if result_mode != "auto" else "display_only"
        await sdk.submit_result(
            result_mode=actual_mode,
            status="success",
            message=summary,
            data={
                "current_capital": state["current_capital"],
                "pnl": round(state["current_capital"] - state["initial_capital"], 2),
                "total_bets": state["total_bets"],
                "total_wins": state["total_wins"],
                "pending_count": len(state.get("pending_bets", [])),
                "today_bets": len(today_bets),
                "report_path": report_path,
            },
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        await sdk.submit_result(
            result_mode="notify",
            status="error",
            message=f"竞彩模拟投注执行失败: {e}",
            data={"error_type": type(e).__name__},
        )


asyncio.run(main())
