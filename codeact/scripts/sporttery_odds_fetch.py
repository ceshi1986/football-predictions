#!/usr/bin/env python3
"""
竞彩官方赔率抓取脚本 (sporttery webapi)
- 抓取5类玩法固定奖金: 胜平负(had) / 让球胜平负(hhad) / 比分(crs) / 总进球(ttg) / 半全场(hafu)
- 每场每玩法包含单关标识(bettingSingle)和串关标识(bettingAllup)
- 保存到 fp-repo/data/sporttery_odds/YYYYMMDD.json
- 云端优先，失败则走 Windows 住宅机兜底（预留接口）

用法:
  python sporttery_odds_fetch.py [result_mode] [repo_dir]
  - result_mode: display_only | auto (默认 display_only)
  - repo_dir: fp-repo 绝对路径 (默认自动推断)
"""
import asyncio
import json
import os
import sys
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Optional

import base64
import requests

from codeact_sdk import CodeActSDK

TOOL_SCHEMA_VERSIONS = {
    "codeact_fetch_web": "v1_2c8d0580b3f93a58",
    "codeact_search_web": "v1_5ac1b0eba8c26f2a",
}

CST = timezone(timedelta(hours=8))
SPORTTERY_API = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry"
POOL_CODES = "had,hhad,crs,ttg,hafu"
GITHUB_REPO = "ceshi1986/football-predictions"

# 玩法代码→中文名映射
PLAY_TYPE_MAP = {
    "HAD": "胜平负",
    "HHAD": "让球胜平负",
    "CRS": "比分",
    "TTG": "总进球",
    "HAFU": "半全场",
}


def now_cst() -> datetime:
    return datetime.now(CST)


def safe_float(v) -> Optional[float]:
    """安全转换赔率字符串为float(分单位整数)，失败返回None"""
    try:
        if v is None or v == "" or v == "--":
            return None
        f = float(v)
        if f <= 1.0:
            return None
        # 保留2位小数，以"分"为单位存储整数，避免浮点误差
        return int(round(f * 100))
    except (ValueError, TypeError):
        return None


def parse_had_odds(had: dict) -> Optional[dict]:
    """解析胜平负赔率"""
    if not had:
        return None
    h = safe_float(had.get("h"))
    d = safe_float(had.get("d"))
    a = safe_float(had.get("a"))
    if h is None and d is None and a is None:
        return None
    return {"h": h, "d": d, "a": a}


def parse_hhad_odds(hhad: dict) -> Optional[dict]:
    """解析让球胜平负赔率"""
    if not hhad:
        return None
    h = safe_float(hhad.get("h"))
    d = safe_float(hhad.get("d"))
    a = safe_float(hhad.get("a"))
    goal_line = hhad.get("goalLineValue") or hhad.get("goalLine") or ""
    if h is None and d is None and a is None:
        return None
    return {"h": h, "d": d, "a": a, "goalLine": goal_line}


def parse_crs_odds(crs: dict) -> Optional[dict]:
    """解析比分赔率"""
    if not crs:
        return None
    result = {}
    # sXXsYY 格式: 主XX-客YY
    score_keys = [
        "s00s00", "s00s01", "s00s02", "s00s03", "s00s04", "s00s05",
        "s01s00", "s01s01", "s01s02", "s01s03", "s01s04", "s01s05",
        "s02s00", "s02s01", "s02s02", "s02s03", "s02s04", "s02s05",
        "s03s00", "s03s01", "s03s02", "s03s03",
        "s04s00", "s04s01", "s04s02",
        "s05s00", "s05s01", "s05s02",
        "s1sh", "s1sd", "s1sa",  # 胜其他 / 平其他 / 负其他
    ]
    for k in score_keys:
        v = safe_float(crs.get(k))
        if v is not None:
            result[k] = v
    if not result:
        return None
    return result


def parse_ttg_odds(ttg: dict) -> Optional[dict]:
    """解析总进球赔率"""
    if not ttg:
        return None
    result = {}
    for i in range(8):
        v = safe_float(ttg.get(f"s{i}"))
        if v is not None:
            result[str(i)] = v
    if not result:
        return None
    return result


def parse_hafu_odds(hafu: dict) -> Optional[dict]:
    """解析半全场赔率
    键: hh=胜胜, hd=胜平, ha=胜负, dh=平胜, dd=平平, da=平负, ah=负胜, ad=负平, aa=负负
    """
    if not hafu:
        return None
    result = {}
    keys = ["hh", "hd", "ha", "dh", "dd", "da", "ah", "ad", "aa"]
    for k in keys:
        v = safe_float(hafu.get(k))
        if v is not None:
            result[k] = v
    if not result:
        return None
    return result


def extract_pool_info(pool_list: list) -> dict:
    """从poolList提取每玩法的单关/串关标识"""
    info = {}
    if not pool_list:
        return info
    for p in pool_list:
        code = p.get("poolCode", "")
        if not code:
            continue
        info[code.upper()] = {
            "bettingSingle": bool(p.get("bettingSingle", 0)),
            "bettingAllup": bool(p.get("bettingAllup", 0)),
            "poolStatus": p.get("poolStatus", ""),
        }
    return info


def fetch_sporttery_odds() -> Optional[dict]:
    """从竞彩官方API获取在售场次及5类赔率"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.sporttery.cn/",
    }
    params = {"poolCode": POOL_CODES, "channel": "c"}
    try:
        resp = requests.get(SPORTTERY_API, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success") or data.get("errorCode") != "0":
            print(f"[ERROR] API返回错误: {data.get('errorMessage')}")
            return None
        return data.get("value")
    except Exception as e:
        print(f"[ERROR] 请求sporttery API失败: {e}")
        return None


def transform_matches(value: dict) -> dict:
    """将API返回的matchInfoList转换为按日期分组的结构化数据"""
    result = {
        "generated_at": now_cst().isoformat(timespec="seconds"),
        "source": "sporttery_webapi",
        "play_types": list(PLAY_TYPE_MAP.keys()),
        "dates": [],
        "total_matches": 0,
        "matches_by_date": {},
    }

    mil = value.get("matchInfoList", [])
    total = 0

    for bd in mil:
        date_str = bd.get("businessDate", "")
        if not date_str:
            continue
        date_key = date_str.replace("-", "")
        sub_list = bd.get("subMatchList", [])
        matches = []

        for m in sub_list:
            match_num = m.get("matchNum")  # 数字编号，如4001
            match_num_str = m.get("matchNumStr", "")  # 如"周四001"
            match_id = m.get("matchId")
            home = m.get("homeTeamAbbName", "")
            away = m.get("awayTeamAbbName", "")
            home_all = m.get("homeTeamAllName", "")
            away_all = m.get("awayTeamAllName", "")
            league = m.get("leagueAbbName", "")
            league_all = m.get("leagueAllName", "")
            match_time = m.get("matchTime", "")  # 如"19:30"
            match_date = m.get("matchDate", "")  # 如"2026-09-10"
            sell_status = m.get("sellStatus", 0)

            # 完整开赛时间
            kickoff = ""
            if match_date and match_time:
                kickoff = f"{match_date}T{match_time}:00+08:00"

            pool_info = extract_pool_info(m.get("poolList", []))

            match_entry = {
                "matchNum": match_num,
                "matchNumStr": match_num_str,
                "matchId": match_id,
                "home": home,
                "away": away,
                "homeFull": home_all,
                "awayFull": away_all,
                "league": league,
                "leagueFull": league_all,
                "kickoff": kickoff,
                "matchDate": match_date,
                "matchTime": match_time,
                "sellStatus": sell_status,
                "poolInfo": pool_info,
                "odds": {
                    "had": parse_had_odds(m.get("had")),
                    "hhad": parse_hhad_odds(m.get("hhad")),
                    "crs": parse_crs_odds(m.get("crs")),
                    "ttg": parse_ttg_odds(m.get("ttg")),
                    "hafu": parse_hafu_odds(m.get("hafu")),
                },
            }
            matches.append(match_entry)
            total += 1

        if matches:
            result["dates"].append(date_key)
            result["matches_by_date"][date_key] = matches

    result["total_matches"] = total
    return result


def save_odds_to_repo(data: dict, repo_dir: str) -> list[str]:
    """保存赔率数据到仓库，按日期分文件保存"""
    odds_dir = os.path.join(repo_dir, "data", "sporttery_odds")
    os.makedirs(odds_dir, exist_ok=True)

    saved_files = []
    for date_key in data["dates"]:
        matches = data["matches_by_date"].get(date_key, [])
        day_data = {
            "generated_at": data["generated_at"],
            "source": data["source"],
            "date": date_key,
            "match_count": len(matches),
            "matches": matches,
        }
        filepath = os.path.join(odds_dir, f"{date_key}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(day_data, f, ensure_ascii=False, indent=2)
        saved_files.append(filepath)

    # 额外保存latest聚合
    latest_path = os.path.join(odds_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    saved_files.append(latest_path)

    return saved_files


def get_github_token(repo_dir: str) -> str:
    """获取 GitHub Token"""
    for path in [os.path.expanduser("~/.github_token"),
                 os.path.join(repo_dir, ".github_token")]:
        if os.path.exists(path):
            with open(path) as f:
                token = f.read().strip()
            if token:
                return token
    return os.environ.get("GITHUB_TOKEN", "")


def push_file_to_github(token: str, local_path: str, repo_rel_path: str, message: str) -> bool:
    """通过 GitHub Contents API 推送单个文件"""
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_rel_path}"
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

    with open(local_path, "r", encoding="utf-8") as f:
        content = f.read()

    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha

    try:
        resp = requests.put(api_url, headers=headers, json=body, timeout=30)
        if resp.status_code in (200, 201):
            commit_sha = resp.json().get("commit", {}).get("sha", "ok")
            print(f"[GitHub] ✅ 推送成功: {repo_rel_path} → {commit_sha[:8]}")
            return True
        else:
            print(f"[GitHub] ❌ 推送失败 ({resp.status_code}): {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"[GitHub] ❌ 推送异常: {e}")
        return False


def push_to_github(repo_dir: str, saved_files: list) -> int:
    """将所有保存的文件推送到 GitHub"""
    token = get_github_token(repo_dir)
    if not token:
        print("[GitHub] ⚠️ 未找到 GitHub Token，跳过推送")
        return 0

    pushed = 0
    commit_msg = f"更新竞彩赔率数据 {now_cst().strftime('%Y-%m-%d %H:%M')}"
    for filepath in saved_files:
        # 计算相对于仓库根目录的路径
        rel_path = os.path.relpath(filepath, repo_dir)
        if push_file_to_github(token, filepath, rel_path, commit_msg):
            pushed += 1

    print(f"[GitHub] 共推送 {pushed}/{len(saved_files)} 个文件")
    return pushed


async def main():
    result_mode = sys.argv[1] if len(sys.argv) > 1 else "display_only"
    repo_dir = sys.argv[2] if len(sys.argv) > 2 else "/Coze/Drive/私人助理小策/所有对话/主对话/fp-repo"

    print(f"[参数] result_mode={result_mode}, repo_dir={repo_dir}")
    sdk = CodeActSDK()

    try:
        # 1. 抓取竞彩官方赔率
        print("[抓取] 请求竞彩官方API...")
        raw_value = fetch_sporttery_odds()
        if raw_value is None:
            raise RuntimeError("竞彩官方API抓取失败")

        # 2. 转换为结构化数据
        data = transform_matches(raw_value)
        print(f"[解析] 共 {data['total_matches']} 场比赛，覆盖 {len(data['dates'])} 个比赛日")

        for d in data["dates"]:
            ms = data["matches_by_date"][d]
            had_count = sum(1 for m in ms if m["odds"].get("had"))
            hhad_count = sum(1 for m in ms if m["odds"].get("hhad"))
            crs_count = sum(1 for m in ms if m["odds"].get("crs"))
            ttg_count = sum(1 for m in ms if m["odds"].get("ttg"))
            hafu_count = sum(1 for m in ms if m["odds"].get("hafu"))
            single_count = sum(
                1 for m in ms
                for p, info in m.get("poolInfo", {}).items()
                if info.get("bettingSingle")
            )
            print(f"  {d}: {len(ms)}场 (胜平负{had_count} 让球{hhad_count} 比分{crs_count} 总进球{ttg_count} 半全场{hafu_count}) 单关玩法{single_count}个")

        # 3. 保存到仓库
        saved = save_odds_to_repo(data, repo_dir)
        print(f"[保存] 已保存 {len(saved)} 个文件到 {os.path.join(repo_dir, 'data', 'sporttery_odds')}/")

        # 4. 推送到 GitHub
        pushed = push_to_github(repo_dir, saved)
        print(f"[推送] GitHub 推送完成: {pushed}/{len(saved)} 个文件")

        # 5. 提交结果
        actual_mode = result_mode if result_mode != "auto" else "display_only"
        summary = (
            f"竞彩官方赔率抓取完成：共 {data['total_matches']} 场，覆盖 {len(data['dates'])} 个比赛日\n"
            f"玩法：胜平负/让球胜平负/比分/总进球/半全场\n"
            f"保存路径：data/sporttery_odds/"
        )

        await sdk.submit_result(
            result_mode=actual_mode,
            status="success",
            message=summary,
            data={
                "total_matches": data["total_matches"],
                "dates": data["dates"],
                "saved_files": [os.path.basename(f) for f in saved],
            },
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        await sdk.submit_result(
            result_mode="notify",
            status="error",
            message=f"竞彩赔率抓取失败: {e}",
            data={"error_type": type(e).__name__},
        )


if __name__ == "__main__":
    asyncio.run(main())
