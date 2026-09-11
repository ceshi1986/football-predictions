#!/usr/bin/env python3
"""
从竞彩官网 API 抓取足球赔率数据，生成 sporttery_odds/latest.json
供 bet_sim.js 投注计算器使用

赔率格式：乘以100后存为整数（前端 fenToYuan 除以100显示）
"""

import json
import os
import sys
import base64
import requests
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
FP_REPO = "/app/data/所有对话/主对话/fp-repo"
OUTPUT_DIR = os.path.join(FP_REPO, "data", "sporttery_odds")
GITHUB_REPO = "ceshi1986/football-predictions"

API_URL = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.sporttery.cn/",
}


def get_github_token():
    """获取 GitHub Token"""
    for path in [os.path.expanduser("~/.github_token"),
                 os.path.join(FP_REPO, ".github_token")]:
        if os.path.exists(path):
            with open(path) as f:
                token = f.read().strip()
            if token:
                return token
    return os.environ.get("GITHUB_TOKEN", "")


def push_to_github(token, rel_path, content_str, message):
    """通过 GitHub Contents API 推送文件"""
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{rel_path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }
    # 获取现有 SHA
    sha = None
    try:
        req = requests.get(api_url, headers=headers, timeout=15)
        if req.status_code == 200:
            sha = req.json().get("sha")
    except Exception:
        pass

    body = {
        "message": message,
        "content": base64.b64encode(content_str.encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha

    try:
        resp = requests.put(api_url, headers=headers, json=body, timeout=30)
        if resp.status_code in (200, 201):
            commit_sha = resp.json().get("commit", {}).get("sha", "ok")
            print(f"[GitHub] ✅ 推送成功: {rel_path} → {commit_sha[:8]}")
            return True
        else:
            print(f"[GitHub] ❌ 推送失败 ({resp.status_code}): {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"[GitHub] ❌ 推送异常: {e}")
        return False


def odds_to_fen(val_str):
    """将小数赔率转为整数分（×100取整）"""
    try:
        return int(round(float(val_str) * 100))
    except (ValueError, TypeError):
        return 0


def convert_had(odds_raw):
    """转换胜平负赔率"""
    return {
        "h": odds_to_fen(odds_raw.get("h")),
        "d": odds_to_fen(odds_raw.get("d")),
        "a": odds_to_fen(odds_raw.get("a")),
    }


def convert_hhad(odds_raw):
    """转换让球胜平负赔率"""
    result = {
        "h": odds_to_fen(odds_raw.get("h")),
        "d": odds_to_fen(odds_raw.get("d")),
        "a": odds_to_fen(odds_raw.get("a")),
    }
    goal_line = odds_raw.get("goalLineValue", "") or odds_raw.get("goalLine", "")
    if goal_line:
        result["goalLine"] = str(goal_line)
    return result


def convert_crs(odds_raw):
    """转换比分赔率"""
    result = {}
    for k, v in odds_raw.items():
        if k.startswith("s") and not k.endswith("f"):
            result[k] = odds_to_fen(v)
    return result


def convert_ttg(odds_raw):
    """转换总进球数赔率"""
    result = {}
    for k, v in odds_raw.items():
        if k.isdigit() and not k.endswith("f"):
            result[k] = odds_to_fen(v)
    return result


def convert_hafu(odds_raw):
    """转换半全场赔率"""
    result = {}
    for k, v in odds_raw.items():
        if k in ("hh", "hd", "ha", "dh", "dd", "da", "ah", "ad", "aa"):
            result[k] = odds_to_fen(v)
    return result


def convert_match(sub_match):
    """将单场比赛转换为 latest.json 格式"""
    match_num = sub_match.get("matchNum", 0)
    match_num_str = sub_match.get("matchNumStr", "")
    home = sub_match.get("homeTeamAbbName", "")
    away = sub_match.get("awayTeamAbbName", "")
    home_full = sub_match.get("homeTeamAllName", home)
    away_full = sub_match.get("awayTeamAllName", away)
    league = sub_match.get("leagueAbbName", "")
    league_full = sub_match.get("leagueName", league)
    business_date = sub_match.get("businessDate", "")
    match_date = sub_match.get("matchDate", business_date)
    match_time = sub_match.get("matchTime", "")
    sell_status = sub_match.get("sellStatus", 0)

    # 构建 kickoff 时间
    kickoff = ""
    if match_date and match_time:
        kickoff = f"{match_date}T{match_time}:00+08:00"

    # 构建 poolInfo
    pool_info = {}
    for play_type in ["HAD", "HHAD", "CRS", "TTG", "HAFU"]:
        pool_info[play_type] = {
            "bettingSingle": bool(sub_match.get(f"bettingSingle{play_type}", 0)),
            "bettingAllup": bool(sub_match.get(f"bettingAllUp{play_type}", 0)),
            "poolStatus": sub_match.get(f"poolStatus{play_type}", "Selling"),
        }
    # 也检查顶层 bettingSingle/bettingAllUp
    if "bettingSingle" in sub_match:
        for pt in pool_info:
            if sub_match.get("bettingSingle") is not None:
                pool_info[pt]["bettingSingle"] = bool(sub_match["bettingSingle"])
            if sub_match.get("bettingAllUp") is not None:
                pool_info[pt]["bettingAllup"] = bool(sub_match["bettingAllUp"])

    # 构建赔率
    odds = {}
    if "had" in sub_match:
        odds["had"] = convert_had(sub_match["had"])
    if "hhad" in sub_match:
        odds["hhad"] = convert_hhad(sub_match["hhad"])
    if "crs" in sub_match:
        odds["crs"] = convert_crs(sub_match["crs"])
    if "ttg" in sub_match:
        odds["ttg"] = convert_ttg(sub_match["ttg"])
    if "hafu" in sub_match:
        odds["hafu"] = convert_hafu(sub_match["hafu"])

    return {
        "matchNum": match_num,
        "matchNumStr": match_num_str,
        "matchId": sub_match.get("matchId", 0),
        "home": home,
        "away": away,
        "homeFull": home_full,
        "awayFull": away_full,
        "league": league,
        "leagueFull": league_full,
        "kickoff": kickoff,
        "matchDate": business_date.replace("-", ""),
        "matchTime": match_time,
        "sellStatus": sell_status,
        "poolInfo": pool_info,
        "odds": odds,
    }


def fetch_and_generate():
    """主函数：抓取数据并生成 latest.json"""
    print(f"[INFO] 正在从竞彩官网获取赔率数据...")
    
    try:
        resp = requests.get(API_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] 请求失败: {e}")
        return False

    data = resp.json()
    if not data.get("success") or not data.get("value"):
        print(f"[ERROR] API 返回失败: {data.get('errorMessage', 'unknown')}")
        return False

    value = data["value"]
    match_info_list = value.get("matchInfoList", [])
    
    if not match_info_list:
        print("[ERROR] 无比赛数据")
        return False

    # 按日期分组
    matches_by_date = {}
    all_dates = set()
    
    for date_group in match_info_list:
        business_date = date_group.get("businessDate", "")
        date_str = business_date.replace("-", "")
        all_dates.add(date_str)
        
        sub_matches = date_group.get("subMatchList", [])
        converted = []
        for sm in sub_matches:
            try:
                converted.append(convert_match(sm))
            except Exception as e:
                print(f"[WARN] 转换比赛失败: {e}, matchNum={sm.get('matchNumStr')}")
                continue
        matches_by_date[date_str] = converted

    # 按日期排序
    sorted_dates = sorted(all_dates)
    total_matches = sum(len(v) for v in matches_by_date.values())

    now_cst = datetime.now(CST)
    output = {
        "generated_at": now_cst.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "source": "sporttery.cn",
        "play_types": ["HAD", "HHAD", "CRS", "TTG", "HAFU"],
        "dates": sorted_dates,
        "total_matches": total_matches,
        "matches_by_date": matches_by_date,
    }

    # 保存文件
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, "latest.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[SUCCESS] 生成 latest.json: {total_matches} 场比赛, {len(sorted_dates)} 个比赛日")
    print(f"  日期: {', '.join(sorted_dates)}")
    for d in sorted_dates:
        print(f"  {d}: {len(matches_by_date[d])} 场")
    print(f"  文件: {output_path} ({os.path.getsize(output_path)} bytes)")

    # 推送到 GitHub
    token = get_github_token()
    if token:
        with open(output_path, "r", encoding="utf-8") as f:
            content_str = f.read()
        push_to_github(token, "data/sporttery_odds/latest.json", content_str,
                       f"📊 更新竞彩赔率数据 {now_cst.strftime('%Y-%m-%d %H:%M')}")
    else:
        print("[WARN] 未找到 GitHub Token，跳过推送")

    return True


if __name__ == "__main__":
    success = fetch_and_generate()
    if not success:
        sys.exit(1)
