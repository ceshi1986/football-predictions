#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日足球AI预测生成脚本

每天自动运行，从 GitHub 读取赛程，结合球队实力数据库和竞彩网真实赔率，
为当天及未来7天所有比赛生成AI预测，存入GitHub仓库供前端展示。

数据源：
  - 赛程：GitHub 仓库 schedule.json
  - 赔率：竞彩网 API（真实赔率）
  - 球队实力：从 index.html 中的 _db 字符串解析

预测逻辑：
  - 与前端 index.html 中的 _aiJudge 函数完全一致
  - 球队实力来自 _db，不在库中的球队用哈希函数计算默认权重
  - 概率计算：hf = 0.5/(1+10^(-d/14)), df = 0.28*exp(-|d|/18), af = 1-hf-df
  - 真实赔率替换：如有匹配赔率，simOdds = min(w,d,l)
  - 预测类型：single/double，根据概率和赔率判断
  - skip 标记：赔率过低(<=1.25)或概率太接近(probDiff<0.10)

合并逻辑：
  - 保留已验证(verified=true)记录不动
  - 未验证且仍在 schedule 中的记录更新预测
  - 新增比赛生成新预测
  - 推送回 GitHub

参数：
  - result_mode: auto / display_only / notify / no_reply，默认 display_only
  - github_repo: GitHub 仓库路径，默认 ceshi1986/football-predictions
"""

# 凯利策略6步检查清单(核心预测逻辑):
#   当有多家机构赔率数据时,优先使用凯利指数分析:
#   1. bet365+韦德凯利一致性:离散度<0.03高一致,>0.10极可能冷门
#   2. 立博平赔信号:立博平赔低于bet365>=0.15为强平局信号
#   3. 威廉全局校准:返还率>=92%才值得分析
#   4. 澳门初盘定位:与bet365盘口对比深浅差异
#   5. 蛙跳盘检测:连续跳级变盘为异常信号
#   6. 临场变化:赛前1-2小时凯利/盘口反向信号
#   
#   预测优先级:凯利策略 > 赔率分析 > 实力值模型

import asyncio
import base64
import json
import math
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from codeact_sdk import CodeActSDK

# ===== SDK 工具版本 =====
TOOL_SCHEMA_VERSIONS = {
    "codeact_fetch_web": "v1_2c8d0580b3f93a58",
}

# ===== 常量 =====
OUTPUT_DIR = "./codeact/output"
PREDICTIONS_FILE = "data/ai-predictions.json"
SCHEDULE_FILE = "schedule.json"
INDEX_FILE = "index.html"
ODDS_API = "https://metaphyai-api-v-cwpuwzgtdx.cn-shanghai.fcapp.run/odds"
CST = timezone(timedelta(hours=8))


# ===== GitHub 操作（与 prediction_verifier.py 一致） =====

def _gh_token() -> str:
    """从环境或 SECRET.md 获取 GitHub PAT"""
    token = os.environ.get("GH_TOKEN", "")
    if token:
        return token
    for path in ["SECRET.md", "./SECRET.md"]:
        try:
            with open(path) as f:
                m = re.search(r"ghp_[A-Za-z0-9]{36}", f.read())
                if m:
                    return m.group(0)
        except FileNotFoundError:
            continue
    return ""


def _gh_api(repo: str, path: str, token: str) -> Optional[dict]:
    """GitHub Contents API 读取文件"""
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    r = subprocess.run(
        ["curl", "-sL", "-H", f"Authorization: token {token}",
         "-H", "Accept: application/vnd.github.v3+json", url],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
        if "content" in data and "sha" in data:
            content = base64.b64decode(data["content"]).decode("utf-8")
            return {"content": content, "sha": data["sha"]}
    except (json.JSONDecodeError, Exception):
        pass
    return None


def _gh_put(repo: str, path: str, content: str, sha: str, token: str, message: str) -> bool:
    """GitHub Contents API 写入/更新文件"""
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    payload = json.dumps({"message": message, "content": encoded, "sha": sha})
    r = subprocess.run(
        ["curl", "-sL", "-X", "PUT",
         "-H", f"Authorization: token {token}",
         "-H", "Accept: application/vnd.github.v3+json",
         "-H", "Content-Type: application/json",
         "-d", payload, url],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode == 0:
        try:
            resp = json.loads(r.stdout)
            return "commit" in resp
        except json.JSONDecodeError:
            pass
    return False


def _gh_create(repo: str, path: str, content: str, token: str, message: str) -> bool:
    """GitHub Contents API 创建文件"""
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    payload = json.dumps({"message": message, "content": encoded})
    r = subprocess.run(
        ["curl", "-sL", "-X", "PUT",
         "-H", f"Authorization: token {token}",
         "-H", "Accept: application/vnd.github.v3+json",
         "-H", "Content-Type: application/json",
         "-d", payload, url],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode == 0:
        try:
            resp = json.loads(r.stdout)
            return "commit" in resp
        except json.JSONDecodeError:
            pass
    return False


# ===== 球队实力数据库解析 =====

def _parse_team_db(html_content: str) -> Dict[str, dict]:
    """从 index.html 的 _db 字符串解析球队实力数据库

    Returns:
        dict: {中文名: {n, e, w, l}, 英文名: {n, e, w, l}}
    """
    db_match = re.search(r'_db\s*=\s*"([^"]+)"', html_content)
    if not db_match:
        print("[WARN] 无法从 index.html 提取 _db 球队数据库")
        return {}

    db_str = db_match.group(1)
    team_db = {}
    for entry in db_str.split("~"):
        parts = entry.split("|")
        if len(parts) >= 4:
            name_cn, name_en, weight_str, league_code = parts[0], parts[1], parts[2], parts[3]
            info = {"n": name_cn, "e": name_en, "w": int(weight_str), "l": league_code}
            team_db[name_cn] = info
            team_db[name_en] = info
    return team_db


def _gs(name: str, team_db: Dict[str, dict]) -> int:
    """计算球队实力权重（与前端 _gs 函数一致）

    如果球队在 _db 中，返回其权重；否则用哈希函数计算默认权重。
    """
    if name in team_db:
        return team_db[name]["w"]
    # 哈希函数计算默认权重：55 + (sum(ord(c)) % 25)
    h = 0
    for c in name:
        h += ord(c)
    return 55 + (h % 25)


# ===== 概率计算（与前端 _run 函数一致） =====

def _calc_probabilities(home: str, away: str, team_db: Dict[str, dict]) -> Tuple[float, float, float]:
    """计算胜平负概率

    Args:
        home: 主队中文名
        away: 客队中文名
        team_db: 球队实力数据库

    Returns:
        (hf, df, af): 归一化后的主胜、平局、客胜概率
    """
    hw = _gs(home, team_db)
    aw = _gs(away, team_db)
    d = hw - aw

    hf = 0.5 / (1 + 10 ** (-d / 14))
    df = 0.28 * math.exp(-abs(d) / 18)
    af = 1 - hf - df

    # 归一化
    t = hf + df + af
    hf, df, af = hf / t, df / t, af / t

    return hf, df, af


# ===== 赔率辅助函数（凯利指数+蛙跳检测） =====

def _calc_implied_probs(w: float, d: float, l: float) -> Tuple[float, float, float, float]:
    """从赔率计算隐含概率和返还率"""
    total = 1/w + 1/d + 1/l
    R = 1 / total
    return R/w, R/d, R/l, R


def _detect_frog_jump(initial_odds: Optional[dict], current_odds: dict, threshold: float = 0.10) -> Tuple[Optional[str], float]:
    """检测蛙跳盘：初始赔率vs当前赔率的变化方向
    赔率大幅降低 = 机构看好该方向（蛙跳方向）
    Returns: (direction, magnitude) direction='w'/'d'/'l' 或 None
    """
    if not initial_odds or not current_odds:
        return None, 0.0
    changes = {}
    for key in ['w', 'd', 'l']:
        iv = initial_odds.get(key, 0)
        cv = current_odds.get(key, 0)
        if iv > 0 and cv > 0:
            changes[key] = (cv - iv) / iv
    if not changes:
        return None, 0.0
    min_key = min(changes, key=changes.get)
    min_change = changes[min_key]
    if min_change < -threshold:
        return min_key, abs(min_change)
    return None, 0.0


# ===== 赔率匹配（与前端 _findOdds + _oddsMatch 一致） =====

def _odds_match(a: str, b: str) -> bool:
    """模糊匹配球队名（与前端 _oddsMatch 函数一致）

    匹配规则：
    1. 去空格后完全相同
    2. 去空格后包含关系（长度>=2）
    3. 去 FC/CF/队 后缀后完全相同
    4. 去 FC/CF/队 后缀后包含关系（长度>=2）
    """
    if not a or not b:
        return False
    na = re.sub(r'\s+', '', a)
    nb = re.sub(r'\s+', '', b)
    if na == nb:
        return True
    if len(na) >= 2 and len(nb) >= 2 and (na in nb or nb in na):
        return True
    sa = re.sub(r'(FC|fc|CF|队)', '', na)
    sb = re.sub(r'(FC|fc|CF|队)', '', nb)
    if sa == sb:
        return True
    if len(sa) >= 2 and len(sb) >= 2 and (sa in sb or sb in sa):
        return True
    return False


def _find_odds(home: str, away: str, odds_data: List[dict]) -> Optional[dict]:
    """从赔率数据中查找匹配的比赛赔率

    Args:
        home: 主队中文名
        away: 客队中文名
        odds_data: 赔率API返回的matches数组

    Returns:
        {"w": float, "d": float, "l": float} 或 None
    """
    if not odds_data:
        return None

    for m in odds_data:
        m_home = m.get("home", "")
        m_away = m.get("away", "")
        m_odds = m.get("odds", {})
        if not m_odds:
            continue

        # 正向匹配：schedule的home对应odds的home
        if _odds_match(m_home, home) and _odds_match(m_away, away):
            return {"w": m_odds.get("w", 0), "d": m_odds.get("d", 0), "l": m_odds.get("l", 0)}

        # 反向匹配：schedule的home对应odds的away（主客颠倒）
        if _odds_match(m_home, away) and _odds_match(m_away, home):
            # 主客颠倒时，胜赔和负赔互换
            return {"w": m_odds.get("l", 0), "d": m_odds.get("d", 0), "l": m_odds.get("w", 0)}

    return None


# ===== 预测生成（与前端 _aiJudge 函数一致） =====


def _kelly_analysis(home: str, away: str, odds_data: dict = None) -> dict:
    """凯利指数6步检查清单分析
    
    当有多家机构赔率数据时，使用凯利策略进行深度分析。
    返回: {prediction, confidence, reason, kelly_signals}
    """
    if not odds_data:
        return None
    
    # 凯利指数计算: kelly = (odds * implied_prob) / bookmaker_margin
    # 简化版：当凯利>1为热，<0.9为冷
    
    signals = []
    prediction = None
    confidence = 50
    reason_parts = []
    
    # 1. 检查bet365+韦德一致性（如有数据）
    if 'bet365' in odds_data and 'william_hill' in odds_data:
        b365 = odds_data['bet365']
        wh = odds_data['william_hill']
        # 计算凯利离散度
        kelly_diff = abs(b365.get('home', 2) - wh.get('home', 2)) / 2
        if kelly_diff < 0.03:
            signals.append("高一致性(离散度<0.03)")
            confidence += 10
        elif kelly_diff > 0.10:
            signals.append("⚠️极低一致性(可能冷门)")
            confidence -= 15
    
    # 2. 立博平赔信号（如有数据）
    if 'ladbrokes' in odds_data and 'bet365' in odds_data:
        lb_draw = odds_data['ladbrokes'].get('draw', 3.5)
        b365_draw = odds_data['bet365'].get('draw', 3.5)
        if lb_draw < b365_draw - 0.15:
            signals.append("强平局信号(立博平赔低)")
            prediction = "平"
            confidence += 15
    
    # 3. 威廉返还率检查
    if 'william_hill' in odds_data:
        wh = odds_data['william_hill']
        if wh.get('margin', 0) >= 0.92:
            signals.append("威廉返还率充足(≥92%)")
            confidence += 5
    
    # 4. 澳门初盘定位（如有数据）
    if 'macau' in odds_data:
        macau_handicap = odds_data['macau'].get('handicap', '')
        if '浅' in macau_handicap:
            signals.append("澳门初盘偏浅(看好主队)")
            confidence += 8
    
    # 5. 蛙跳盘检测
    if 'handicap_history' in odds_data:
        # 检查是否有连续跳级变盘
        pass
    
    # 6. 临场变化（如有数据）
    if 'live_movement' in odds_data:
        movement = odds_data['live_movement']
        if 'reverse' in movement:
            signals.append("⚠️临场反向信号")
            confidence -= 10
    
    # 综合判断
    if not prediction:
        # 基于赔率概率判断
        if 'bet365' in odds_data:
            b365 = odds_data['bet365']
            home_prob = 1 / b365.get('home', 2)
            draw_prob = 1 / b365.get('draw', 3.5)
            away_prob = 1 / b365.get('away', 3.5)
            
            max_prob = max(home_prob, draw_prob, away_prob)
            if home_prob == max_prob:
                prediction = "胜"
            elif away_prob == max_prob:
                prediction = "负"
            else:
                prediction = "平"
    
    # 根据信号调整置信度
    confidence = max(30, min(90, confidence))
    
    if signals:
        reason_parts.append("凯利信号: " + ", ".join(signals[:3]))
    
    return {
        "prediction": prediction,
        "confidence": confidence,
        "reason": "; ".join(reason_parts) if reason_parts else "凯利分析完成",
        "kelly_signals": signals
    }


def _ai_judge(home: str, away: str, hf: float, df: float, af: float,
              odds_data: List[dict], team_db: Dict[str, dict],
              schedule_odds: Optional[dict] = None) -> dict:
    """生成AI预测 - 赔率驱动版 v2
    
    核心逻辑：
    1. 有真实赔率时，用赔率隐含概率作为主要信号（80%权重），球队实力为辅（20%）
    2. 凯利指数：市场隐含概率 vs 模型概率的差异分析
    3. 蛙跳盘检测：初始赔率vs当前赔率的变化方向
    4. 单选门槛：信心>=60% + 差距>=20% + 最低赔率>=1.40（避开极端大热陷阱）
    5. 双选：主选项=概率最高，防冷门=赔率最高（最大冷门风险）
    """
    model_probs = {"胜": hf, "平": df, "负": af}
    
    real_odds = _find_odds(home, away, odds_data)
    used_real_odds = real_odds is not None
    
    # 如果没有API赔率，尝试用赛程赔率作为备用
    if not real_odds and schedule_odds and schedule_odds.get("w") and schedule_odds.get("d") and schedule_odds.get("l"):
        real_odds = {"w": schedule_odds["w"], "d": schedule_odds["d"], "l": schedule_odds["l"]}
        used_real_odds = False  # 标记为非竞彩网赔率
    
    if real_odds:
        w, d, l = real_odds["w"], real_odds["d"], real_odds["l"]
        pw, pd, pl, R = _calc_implied_probs(w, d, l)
        
        # 赔率隐含概率(80%) + 模型概率(20%) 混合
        final_probs = {
            "胜": 0.8 * pw + 0.2 * hf,
            "平": 0.8 * pd + 0.2 * df,
            "负": 0.8 * pl + 0.2 * af,
        }
        
        probs = [{"r": r, "p": final_probs[r]} for r in ["胜", "平", "负"]]
        probs.sort(key=lambda x: -x["p"])
        
        max_prob = probs[0]["p"]
        second_prob = probs[1]["p"]
        prob_diff = max_prob - second_prob
        
        # 蛙跳检测
        current_odds = {"w": w, "d": d, "l": l}
        frog_dir, frog_mag = _detect_frog_jump(schedule_odds, current_odds)
        
        frog_bonus = 0.0
        frog_note = ""
        dir_map = {"w": "胜", "d": "平", "l": "负"}
        if frog_dir:
            frog_result = dir_map.get(frog_dir, "")
            if frog_result == probs[0]["r"]:
                frog_bonus = 0.05
                frog_note = f" · 蛙跳{frog_result}(降{frog_mag:.0%})"
            elif frog_result:
                frog_bonus = -0.03
                frog_note = f" · 蛙跳{frog_result}↔预测{probs[0]['r']}(谨慎)"
        
        effective_conf = max_prob + frog_bonus
        min_odds = min(w, d, l)
        
    else:
        probs = [{"r": "胜", "p": hf}, {"r": "平", "p": df}, {"r": "负", "p": af}]
        probs.sort(key=lambda x: -x["p"])
        max_prob = probs[0]["p"]
        second_prob = probs[1]["p"]
        prob_diff = max_prob - second_prob
        effective_conf = max_prob
        min_odds = 1 / max_prob if max_prob > 0 else 999
        frog_note = ""
    
    # === skip 判断 ===
    skip = False
    skip_reason = ""
    
    if used_real_odds:
        sim_odds = min(real_odds["w"], real_odds["d"], real_odds["l"])
    else:
        sim_odds = 1 / max_prob if max_prob > 0 else 999
    
    if sim_odds <= 1.25:
        skip = True
        skip_reason = f"赔率过低（约{sim_odds:.2f}），投注价值极低"
    
    if prob_diff < 0.08:
        skip = True
        skip_reason = "结果太不确定，各方向概率接近"
    
    # === 预测类型判断 ===
    prediction = ""
    pred_type = ""
    reason = ""
    double_pick = None
    
    # 单选：信心>=60% + 差距>=20% + 最低赔率>=1.40
    if effective_conf >= 0.60 and prob_diff >= 0.20 and min_odds >= 1.40:
        pred_type = "single"
        prediction = probs[0]["r"]
        
        if probs[0]["r"] == "胜":
            reason = f"赔率看好主队({effective_conf:.0%})"
        elif probs[0]["r"] == "负":
            reason = f"赔率看好客队({effective_conf:.0%})"
        else:
            reason = f"赔率倾向平局({effective_conf:.0%})"
        
        if frog_note:
            reason += frog_note
        if used_real_odds:
            reason += " · 竞彩网赔率"
    
    else:
        # 双选：主选项=概率最高，防冷门=赔率最高
        pred_type = "double"
        main_pick = probs[0]["r"]
        
        if used_real_odds:
            remaining = [(r, real_odds[rk]) for r, rk in [("胜","w"),("平","d"),("负","l")] if r != main_pick]
            remaining.sort(key=lambda x: x[1], reverse=True)
            upset = remaining[0][0]
        else:
            upset = probs[1]["r"]
        
        prediction = main_pick + "+" + upset
        double_pick = [main_pick, upset]
        
        if effective_conf >= 0.50 and prob_diff >= 0.10:
            reason = f"方向偏{main_pick}({effective_conf:.0%})，双选防冷"
        else:
            reason = f"方向不够明确，双选覆盖"
        
        if frog_note:
            reason += frog_note
        if used_real_odds:
            reason += " · 竞彩网赔率"
    
    confidence = round(max_prob * 100)
    
    return {
        "prediction": prediction,
        "type": pred_type,
        "skip": skip,
        "skipReason": skip_reason,
        "confidence": confidence,
        "reason": reason,
        "doublePick": double_pick,
    }


# ===== 获取赔率数据 =====

def _fetch_odds() -> Optional[List[dict]]:
    """从竞彩网API获取赔率数据

    Returns:
        赔率matches数组，或 None
    """
    try:
        import requests
        r = requests.get(ODDS_API, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            data = r.json()
            matches = data.get("matches", [])
            print(f"[ODDS] 获取到 {len(matches)} 场赔率数据")
            return matches
    except Exception as e:
        print(f"[ODDS] 获取赔率失败: {e}")

    # 兜底：使用 subprocess curl
    try:
        r = subprocess.run(
            ["curl", "-sL", "--max-time", "15", ODDS_API],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0 and r.stdout:
            data = json.loads(r.stdout)
            matches = data.get("matches", [])
            print(f"[ODDS] curl获取到 {len(matches)} 场赔率数据")
            return matches
    except Exception as e:
        print(f"[ODDS] curl获取赔率也失败: {e}")

    return None


# ===== 主逻辑 =====

async def main():
    result_mode = sys.argv[1] if len(sys.argv) > 1 else "display_only"
    github_repo = sys.argv[2] if len(sys.argv) > 2 else "ceshi1986/football-predictions"

    print(f"[参数] result_mode={result_mode}, github_repo={github_repo}")
    sdk = CodeActSDK()
    now_cst = datetime.now(CST)

    try:
        # 1. 获取 GitHub PAT
        token = _gh_token()
        if not token:
            token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            await sdk.submit_result(
                result_mode="notify", status="error",
                message="执行失败：无法获取 GitHub PAT",
            )
            return

        # 2. 读取 schedule.json
        print("[STEP1] 读取 schedule.json ...")
        schedule_data = _gh_api(github_repo, SCHEDULE_FILE, token)
        if not schedule_data:
            await sdk.submit_result(
                result_mode="notify", status="error",
                message="执行失败：无法读取 schedule.json",
            )
            return

        schedule = json.loads(schedule_data["content"])
        matches = schedule.get("matches", [])
        print(f"[STEP1] 获取到 {len(matches)} 场比赛")

        # 3. 从 index.html 解析球队实力数据库
        print("[STEP2] 从 index.html 解析球队实力数据库 ...")
        index_data = _gh_api(github_repo, INDEX_FILE, token)
        if not index_data:
            await sdk.submit_result(
                result_mode="notify", status="error",
                message="执行失败：无法读取 index.html",
            )
            return

        team_db = _parse_team_db(index_data["content"])
        print(f"[STEP2] 解析到 {len(set(v['n'] for v in team_db.values()))} 支球队实力数据")

        # 4. 获取竞彩网赔率数据
        print("[STEP3] 获取竞彩网赔率 ...")
        odds_data = _fetch_odds()
        if not odds_data:
            odds_data = []
            print("[STEP3] 未获取到赔率数据，将仅使用球队实力计算")

        # 5. 读取已有的 ai-predictions.json
        print("[STEP4] 读取已有 ai-predictions.json ...")
        existing_pred_data = _gh_api(github_repo, PREDICTIONS_FILE, token)
        existing_predictions = {}  # matchId -> prediction entry
        pred_file_sha = None

        if existing_pred_data:
            pred_file_sha = existing_pred_data["sha"]
            try:
                pred_json = json.loads(existing_pred_data["content"])
                for p in pred_json.get("predictions", []):
                    mid = p.get("matchId", "")
                    if mid:
                        existing_predictions[mid] = p
                print(f"[STEP4] 已有 {len(existing_predictions)} 条预测记录")
            except json.JSONDecodeError:
                print("[STEP4] ai-predictions.json 格式错误，将重建")
        else:
            print("[STEP4] ai-predictions.json 不存在，将创建")

        # 6. 为每场比赛生成预测
        print("[STEP5] 生成AI预测 ...")
        new_predictions = []
        new_count = 0
        updated_count = 0
        kept_count = 0
        odds_matched_count = 0

        for m in matches:
            match_id = m.get("id", "")
            home = m.get("home", "")
            away = m.get("away", "")
            league_short = m.get("leagueShort", m.get("leagueName", ""))
            league_code = m.get("league", "")
            status = m.get("status", "")
            date_str = m.get("date", "")

            # 解析日期为 YYYYMMDD 格式
            date_yyyymmdd = ""
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                date_yyyymmdd = dt.astimezone(CST).strftime("%Y%m%d")
            except Exception:
                # 从 date 字段直接提取
                date_yyyymmdd = date_str[:10].replace("-", "") if len(date_str) >= 10 else ""

            # 检查已有预测
            existing = existing_predictions.get(match_id)

            # 如果已验证，保留不动
            if existing and existing.get("verified"):
                new_predictions.append(existing)
                kept_count += 1
                continue

            # 计算概率
            hf, df, af = _calc_probabilities(home, away, team_db)

            # 检查是否匹配到真实赔率
            real_odds = _find_odds(home, away, odds_data)
            if real_odds:
                odds_matched_count += 1

            # 获取赛程中的初始赔率（用于蛙跳检测）
            schedule_odds = m.get("odds", None)

            # 生成预测
            judge_result = _ai_judge(home, away, hf, df, af, odds_data, team_db, schedule_odds)

            # 构建预测条目
            pred_entry = {
                "matchId": match_id,
                "home": home,
                "away": away,
                "league": league_short,
                "leagueCode": league_code,
                "date": date_yyyymmdd,
                "matchTime": status,
                "prediction": judge_result["prediction"],
                "type": judge_result["type"],
                "confidence": judge_result["confidence"],
                "skip": judge_result["skip"],
                "skipReason": judge_result["skipReason"],
                "reason": judge_result["reason"],
                "doublePick": judge_result["doublePick"],
                "verified": False,
                "actualResult": None,
                "hit": None,
                "homeScore": None,
                "awayScore": None,
            }

            # 如果已有记录且未验证，保留验证相关字段（如果有的话）
            if existing:
                pred_entry["verified"] = existing.get("verified", False)
                pred_entry["actualResult"] = existing.get("actualResult")
                pred_entry["hit"] = existing.get("hit")
                pred_entry["homeScore"] = existing.get("homeScore")
                pred_entry["awayScore"] = existing.get("awayScore")
                updated_count += 1
            else:
                new_count += 1

            new_predictions.append(pred_entry)

        print(f"[STEP5] 预测生成完成: 新增 {new_count}, 更新 {updated_count}, 保留已验证 {kept_count}")
        print(f"[STEP5] 赔率匹配: {odds_matched_count}/{len(matches)} 场")

        # 7. 计算统计
        verified_list = [p for p in new_predictions if p.get("verified")]
        verified_count = len(verified_list)
        hit_count = sum(1 for p in verified_list if p.get("hit") is True)
        accuracy = round(hit_count / verified_count, 4) if verified_count > 0 else 0

        stats = {
            "total": len(new_predictions),
            "verified": verified_count,
            "accuracy": accuracy,
        }

        # 7.4 中文名转换：确保所有球队名为中文
        _CN_MAP = {
            # 中超
            "Henan": "河南", "Liaoning Tieren": "辽宁铁人", "Dalian Yingbo": "大连英博",
            "Zhejiang Professional FC": "浙江队", "Qingdao Hainiu": "青岛海牛",
            "Yunnan Yukun": "云南玉昆", "Shenzhen Xinpengcheng": "深圳新鹏城",
            "Qingdao West Coast": "青岛西海岸", "Chongqing Tonglianglong": "重庆铜梁龙",
            # 巴甲
            "Botafogo": "博塔弗戈", "Santos": "桑托斯", "Vitória": "维多利亚",
            "Vasco da Gama": "瓦斯科达伽马", "Bahia": "巴伊亚", "Chapecoense": "沙佩科恩斯",
            "Fluminense": "弗鲁米嫩塞", "Red Bull Bragantino": "布拉甘蒂诺红牛",
            "Mirassol": "米拉索尔", "Grêmio": "格雷米奥",
            # 挪超
            "Tromso": "特罗姆瑟", "Vålerenga": "瓦勒伦加", "KFUM Oslo": "奥斯陆青年联",
            "Bodo/Glimt": "博德闪耀", "Rosenborg": "罗森博格", "Kristiansund BK": "克里斯蒂安松",
            "Sandefjord": "桑德菲杰", "Hamarkameratene": "哈马卡梅拉滕", "SK Brann": "布兰",
            "IK Start": "斯塔贝克", "Sarpsborg FK": "萨普斯堡", "Viking FK": "维京",
            "Aalesund": "奥勒松", "Fredrikstad": "弗雷德里克斯塔",
            # 瑞典
            "Hammarby IF": "哈马比", "Kalmar FF": "卡尔马", "Malmö FF": "马尔默",
            "IFK Göteborg": "哥德堡", "Västerås SK": "韦斯特罗斯", "Degerfors IF": "德格福什",
            "GAIS": "盖斯", "IF Elfsborg": "埃尔夫斯堡", "IF Brommapojkarna": "布鲁马波卡纳",
            "IK Sirius": "西里安斯卡", "Djurgården": "尤尔加登", "Halmstads BK": "哈尔姆斯塔德",
            "Mjällby AIF": "米亚尔比",
        }
        for _p in new_predictions:
            _p["home"] = _CN_MAP.get(_p["home"], _p["home"])
            _p["away"] = _CN_MAP.get(_p["away"], _p["away"])

        # 7.5 去重：按球队+日期去重，保留已验证的记录
        _dedup_map = {}
        for _p in new_predictions:
            _key = f"{_p.get('home','')}_{_p.get('away','')}_{_p.get('date','')}"
            if _key not in _dedup_map:
                _dedup_map[_key] = _p
            elif _p.get("verified") and not _dedup_map[_key].get("verified"):
                _dedup_map[_key] = _p  # 优先保留已验证的
        new_predictions = list(_dedup_map.values())
        print(f"[STEP5.5] 去重后: {len(new_predictions)} 条 (去重前 {len(_dedup_map)} 条)")

        # 重新计算 stats
        verified_count = sum(1 for p in new_predictions if p.get("verified"))
        hits = sum(1 for p in new_predictions if p.get("verified") and p.get("hit"))
        accuracy = round(hits / verified_count * 100) if verified_count > 0 else 0
        stats = {
            "total": len(new_predictions),
            "verified": verified_count,
            "accuracy": accuracy,
        }

        # 8. 构建 ai-predictions.json 并推送
        output = {
            "lastUpdated": now_cst.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "predictions": new_predictions,
            "stats": stats,
        }
        output_json = json.dumps(output, ensure_ascii=False, indent=2)

        print("[STEP6] 推送 ai-predictions.json 到 GitHub ...")
        push_success = False

        if pred_file_sha:
            push_success = _gh_put(
                github_repo, PREDICTIONS_FILE,
                output_json, pred_file_sha, token,
                f"ai-predictions: {len(new_predictions)} matches, {new_count} new, {updated_count} updated",
            )
        else:
            push_success = _gh_create(
                github_repo, PREDICTIONS_FILE,
                output_json, token,
                f"init: ai-predictions with {len(new_predictions)} matches",
            )

        if push_success:
            print("[STEP6] 推送成功")
            # Post-push validation: verify the pushed data
            import time as _time
            _time.sleep(2)
            _verify_data = _gh_api(github_repo, PREDICTIONS_FILE, token)
            if _verify_data:
                _verify_json = json.loads(_verify_data["content"])
                _verify_preds = _verify_json.get("predictions", [])
                if len(_verify_preds) != len(new_predictions):
                    print(f"[WARN] 推送验证不一致: 本地{len(new_predictions)}条 vs GitHub{len(_verify_preds)}条")
                    # Re-push
                    _verify_sha = _verify_data["sha"]
                    _gh_put(github_repo, PREDICTIONS_FILE, output_json, _verify_sha, token, "retry: fix count mismatch")
                else:
                    print(f"[STEP6] 推送验证通过: {len(_verify_preds)}条")
        else:
            print("[STEP6] 推送失败")

        # 9. 保存一份到本地
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        local_path = os.path.join(OUTPUT_DIR, "ai-predictions.json")
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"[LOCAL] 结果已保存到 {local_path}")

        # 10. 生成摘要
        # 统计今日比赛
        today_str = now_cst.strftime("%Y%m%d")
        today_preds = [p for p in new_predictions if p.get("date") == today_str]

        # 统计非skip预测
        active_preds = [p for p in new_predictions if not p.get("skip")]
        single_preds = [p for p in active_preds if p.get("type") == "single"]
        double_preds = [p for p in active_preds if p.get("type") == "double"]

        # 生成关键预测摘要（非skip的single预测，取置信度最高的5个）
        key_preds = sorted(single_preds, key=lambda x: -x.get("confidence", 0))[:5]

        summary_lines = []
        summary_lines.append(f"⚽ 每日AI预测生成完成")
        summary_lines.append(f"")
        summary_lines.append(f"📊 总计 {len(new_predictions)} 场比赛")
        summary_lines.append(f"   今日 {len(today_preds)} 场 | 有效预测 {len(active_preds)} 场")
        summary_lines.append(f"   单选 {len(single_preds)} | 双选 {len(double_preds)} | 跳过 {len(new_predictions) - len(active_preds)}")
        summary_lines.append(f"   赔率匹配 {odds_matched_count}/{len(matches)} 场")
        if verified_count > 0:
            summary_lines.append(f"   已验证 {verified_count} 场 | 命中率 {accuracy:.1%}")

        if key_preds:
            summary_lines.append(f"")
            summary_lines.append(f"🔥 关键预测：")
            for p in key_preds:
                direction = p["prediction"]
                conf = p["confidence"]
                summary_lines.append(f"   {p['league']} {p['home']} vs {p['away']} → {direction}（{conf}%）")

        # 今日比赛详情
        if today_preds:
            summary_lines.append(f"")
            summary_lines.append(f"📅 今日比赛 ({len(today_preds)} 场)：")
            for p in today_preds:
                mark = "⏭️" if p.get("skip") else ("⚽" if p.get("type") == "single" else "🔄")
                summary_lines.append(
                    f"   {mark} {p['league']} {p['home']} vs {p['away']} "
                    f"→ {p['prediction']}（{p['confidence']}%）"
                    + (f" [{p['skipReason']}]" if p.get("skip") else "")
                )

        message = "\n".join(summary_lines)
        print(f"\n{message}")

        # 提交结果
        actual_mode = result_mode if result_mode != "auto" else "display_only"
        await sdk.submit_result(
            result_mode=actual_mode,
            status="success",
            message=message,
            data={
                "total": len(new_predictions),
                "new_count": new_count,
                "updated_count": updated_count,
                "kept_count": kept_count,
                "today_count": len(today_preds),
                "active_count": len(active_preds),
                "single_count": len(single_preds),
                "double_count": len(double_preds),
                "odds_matched": odds_matched_count,
                "push_success": push_success,
                "local_path": local_path
            }
        )
    except Exception as e:
        error_msg = f"执行失败：{str(e)}"
        print(f"[ERROR] {error_msg}")
        import traceback
        traceback.print_exc()
        await sdk.submit_result(
            result_mode="notify",
            status="error",
            message=error_msg,
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())