#!/usr/bin/env python3
"""
每日足球预测脚本 - 凯利策略 + Elo降级
- 有赔率时100%基于赔率隐含概率（凯利策略）
- 无赔率时降级为Elo模型
- 凯利离散度调节置信度
- 置信度分级（星级）
- 让球辅助判断
- 保留已验证旧预测，只新增/更新未验证的
- 只预测90分钟+补时结果
"""

import asyncio
import sys
import json
import math
import os
from datetime import datetime, timezone, timedelta
from codeact_sdk import CodeActSDK
import requests

# ===== 工具 Schema 版本 =====
TOOL_SCHEMA_VERSIONS = {
    "codeact_fetch_web": "v1_2c8d0580b3f93a58",
    "codeact_search_web": "v1_5ac1b0eba8c26f2a",
}

# ===== 球队实力数据库（从 index.html _db 解析） =====
# 格式：名称|英文名|实力分|联赛代码
_TEAM_DB_RAW = (
    "法国|France|94|05~德国|Germany|92|02~巴西|Brazil|91|14~英格兰|England|91|01"
    "~阿根廷|Argentina|90|15~西班牙|Spain|90|03~葡萄牙|Portugal|89|06~荷兰|Netherlands|88|07"
    "~比利时|Belgium|87|08~克罗地亚|Croatia|86|01~摩洛哥|Morocco|83|05~意大利|Italy|87|04"
    "~乌拉圭|Uruguay|84|14~哥伦比亚|Colombia|83|14~塞内加尔|Senegal|82|05~日本|Japan|80|11"
    "~韩国|South Korea|79|12~美国|USA|78|13~墨西哥|Mexico|79|13~瑞士|Switzerland|81|05"
    "~丹麦|Denmark|80|01~奥地利|Austria|79|02~土耳其|Turkey|79|09~波兰|Poland|78|01"
    "~塞尔维亚|Serbia|78|01~瑞典|Sweden|77|01~加纳|Ghana|76|05~伊朗|Iran|76|01"
    "~澳大利亚|Australia|75|01~沙特|Saudi Arabia|73|01~卡塔尔|Qatar|71|01~俄罗斯|Russia|78|09"
    "~挪威|Norway|81|01~曼城|Manchester City|92|01~阿森纳|Arsenal|90|01~利物浦|Liverpool|89|01"
    "~切尔西|Chelsea|86|01~曼联|Manchester United|84|01~热刺|Tottenham|82|01~纽卡斯尔|Newcastle|81|01"
    "~阿斯顿维拉|Aston Villa|80|01~布莱顿|Brighton|79|01~西汉姆|West Ham|77|01"
    "~拜仁|Bayern Munich|92|02~多特蒙德|Borussia Dortmund|86|02~莱比锡|RB Leipzig|84|02"
    "~勒沃库森|Bayer Leverkusen|85|02~法兰克福|Eintracht Frankfurt|80|02~沃尔夫斯堡|VfL Wolfsburg|77|02"
    "~皇马|Real Madrid|93|03~巴塞罗那|Barcelona|91|03~马竞|Atletico Madrid|86|03"
    "~皇家社会|Real Sociedad|81|03~毕尔巴鄂|Athletic Bilbao|80|03~比利亚雷亚尔|Villarreal|80|03"
    "~贝蒂斯|Real Betis|78|03~国米|Inter Milan|89|04~AC米兰|AC Milan|85|04~尤文|Juventus|85|04"
    "~那不勒斯|Napoli|86|04~罗马|AS Roma|81|04~拉齐奥|Lazio|80|04~亚特兰大|Atalanta|83|04"
    "~佛罗伦萨|Fiorentina|79|04~巴黎圣日耳曼|Paris SG|90|05~马赛|Marseille|80|05~里昂|Lyon|79|05"
    "~摩纳哥|Monaco|79|05~里尔|Lille|78|05~尼斯|Nice|76|05~雷恩|Rennes|77|05"
    "~本菲卡|Benfica|82|06~波尔图|Porto|81|06~阿贾克斯|Ajax|79|07~布鲁日|Club Brugge|77|08"
    "~加拉塔萨雷|Galatasaray|78|09~费内巴切|Fenerbahce|77|09"
    "~上海海港|Shanghai Port|72|10~上海申花|Shanghai Shenhua|71|10~山东泰山|Shandong Taishan|70|10"
    "~北京国安|Beijing Guoan|70|10~武汉三镇|Wuhan Three Towns|69|10"
    "~川崎前锋|Kawasaki Frontale|74|11~横滨水手|Yokohama F Marinos|73|11~浦和红钻|Urawa Red Diamonds|72|11"
    "~FC首尔|FC Seoul|74|12~全北现代|Jeonbuk Hyundai|73|12~江原FC|Gangwon FC|71|12~浦项制铁|Pohang Steelers|71|12~蔚山HD|Ulsan HD|71|12~安养FC|FC Anyang|69|12~仁川联|Incheon United|69|12~济州SK|Jeju SK FC|68|12~富川FC|Bucheon FC|68|12~大田市民|Daejeon Hana Citizen|67|12~金泉尚武|Gimcheon Sangmu|67|12~光州FC|Gwangju FC|66|12"
    "~洛杉矶FC|LAFC|74|13~迈阿密国际|Inter Miami|73|13"
    "~弗拉门戈|Flamengo|80|14~帕尔梅拉斯|Palmeiras|79|14~河床|River Plate|79|15~博卡青年|Boca Juniors|78|15"
    "~河南|Henan|66|10~辽宁铁人|Liaoning Tieren|65|10~大连英博|Dalian Yingbo|64|10"
    "~深圳新鹏城|Shenzhen Xinpengcheng|65|10~青岛西海岸|Qingdao West Coast|66|10"
    "~重庆铜梁龙|Chongqing Tonglianglong|63|10~浙江职业|Zhejiang Professional FC|67|10"
    "~青岛海牛|Qingdao Hainiu|65|10~云南玉昆|Yunnan Yukun|64|10"
    "~罗森博格|Rosenborg|72|09~布兰|SK Brann|71|09~特罗姆瑟|Tromso|68|09~奥勒松|Aalesund|67|09"
    "~维京|Viking FK|70|09~桑德菲杰|Sandefjord|67|09~汉坎|Hamarkameratene|66|09"
    "~克里斯蒂安松|Kristiansund BK|66|09~斯塔贝克|IK Start|64|09~萨尔普斯堡|Sarpsborg FK|67|09"
    "~腓特烈斯塔|Fredrikstad|69|09~利勒斯特罗姆|Lillestrom|69|09~KFUM奥斯陆|KFUM Oslo|68|09"
    "~博德闪耀|Bodo/Glimt|76|09~瓦勒伦加|Vålerenga|70|09~莫尔德|Molde|73|09"
    "~马尔默|Malmö FF|74|08~埃尔夫斯堡|IF Elfsborg|72|08~哈马比|Hammarby IF|71|08"
    "~AIK|AIK|70|08~哥德堡|IFK Göteborg|68|08~卡尔马|Kalmar FF|65|08"
    "~代格福什|Degerfors IF|62|08~天狼星|IK Sirius|67|08~布鲁马波卡纳|IF Brommapojkarna|65|08"
    "~厄尔格里特|Örgryte IS|66|08~BK海肯|BK Häcken|71|08~哈尔姆斯塔德|Halmstads BK|65|08"
    "~尤尔加登|Djurgården|70|08~韦斯特罗斯|Västerås SK|66|08~米耶尔比|Mjällby AIF|67|08"
    "~盖斯|GAIS|68|08"
    "~古比斯|KuPS|70|16~图尔库国际|FC Inter|69|16~VPS瓦萨|VPS|68|16~奥卢|AC Oulu|67|16~赫尔辛基|HJK|67|16~格尼斯坦|IF Gnistan|66|16~TPS图尔库|TPS|66|16~拉赫蒂|FC Lahti|65|16~埃尔维斯|Ilves|65|16~塞那乔其|SJK|64|16~雅罗|FF Jaro|63|16~玛丽港|IFK Mariehamn|62|16"
    "~博塔弗戈|Botafogo|76|14~桑托斯|Santos|72|14~维多利亚|Vitória|68|14~瓦斯科达伽马|Vasco da Game|70|14"
)


def parse_team_db(db_string: str) -> dict:
    """解析 _db 字符串为球队实力字典 {名称: {strength, english, league}}"""
    teams = {}
    for entry in db_string.split("~"):
        parts = entry.strip().split("|")
        if len(parts) >= 4:
            name = parts[0].strip()
            if name:
                teams[name] = {
                    "name": name,
                    "english": parts[1].strip(),
                    "strength": int(parts[2]),
                    "league": parts[3].strip(),
                }
    return teams


def get_team_strength(teams: dict, name: str) -> int:
    """获取球队实力分，默认70"""
    if name in teams:
        return teams[name]["strength"]
    return 70


def calc_elo_probs(home_strength: int, away_strength: int) -> dict:
    """计算 Elo 概率（前端 _run 函数逻辑）"""
    d = home_strength - away_strength
    hf = 0.5 / (1 + 10 ** (-d / 14))
    df = 0.28 * math.exp(-abs(d) / 18)
    af = 1 - hf - df
    t = hf + df + af
    hf /= t
    df /= t
    af /= t
    return {"胜": hf, "平": df, "负": af}


def calc_kelly_probs(w: float, d: float, l: float) -> dict:
    """计算赔率隐含概率（凯利策略核心）"""
    total = 1 / w + 1 / d + 1 / l
    R = 1 / total  # 返还率
    pw = R / w
    pd = R / d
    pl = R / l
    return {"胜": pw, "平": pd, "负": pl}


def normalize_odds(odds: dict) -> tuple:
    """
    标准化赔率格式，返回 (w, d, l, handicap_odds, odds_source)
    支持两种格式:
    1. 简单格式: {"w": 2.3, "d": 3.0, "l": 2.8}
    2. 竞彩格式: {"source":"竞彩", "odds_0":{"胜":1.82,...}, "odds_minus1":{...}}
    """
    if not odds:
        return None, None, None, None, None

    handicap_odds = None
    source = None

    if "odds_0" in odds:
        # 竞彩格式
        o0 = odds["odds_0"]
        w = o0.get("胜", 0)
        d = o0.get("平", 0)
        l = o0.get("负", 0)
        handicap_odds = odds.get("odds_minus1")
        source = odds.get("source", "竞彩")
    elif "w" in odds:
        # 简单格式
        w = odds.get("w", 0)
        d = odds.get("d", 0)
        l = odds.get("l", 0)
        source = "足彩网"
    else:
        return None, None, None, None, None

    # 验证赔率有效性
    if not w or not d or not l or w <= 1 or d <= 1 or l <= 1:
        return None, None, None, None, None

    return w, d, l, handicap_odds, source


def get_handicap_direction(handicap_odds: dict) -> str:
    """从让球赔率推断让球方向"""
    if not handicap_odds:
        return None
    h_win = handicap_odds.get("胜", 99)
    h_draw = handicap_odds.get("平", 99)
    h_lose = handicap_odds.get("负", 99)
    min_h = min(h_win, h_draw, h_lose)
    if min_h >= 99:
        return None
    if min_h == h_win:
        return "胜"
    elif min_h == h_lose:
        return "负"
    else:
        return "平"


# ===== 凯利场景分析 =====
# 核心bookmaker key映射（The Odds API key -> 内部标识）
# B365+BV覆盖率97.4%，远高于Pinnacle的39.8%
_KEY_BOOKMAKERS = {
    "bet365": "bet365",
    "betvictor": "betvictor",
    "ladbrokes_uk": "ladbrokes",
    "williamhill": "williamhill",
    "coral": "coral",
    "betway": "betway",
}

# 立博平局Kelly阈值：低于返还率=立博对平局比市场更保守
# 全量回测：0.9393阈值触发0场（立博实际返还率均值≈0.93），故修正为1.0
LADBROKES_DRAW_KELLY_MEDIAN = 1.0
# Kelly异常过滤阈值
KELLY_MIN_FILTER_THRESHOLD = 0.87


def calc_kelly_scenario(bookmaker_odds: dict, home_team: str, away_team: str) -> dict:
    """
    计算凯利场景分析

    bookmaker_odds: {bookmaker_key: {home: odds, draw: odds, away: odds}}
                    赔率为欧赔(decimal)格式
    home_team: 主队英文名（用于从API outcomes中匹配）
    away_team: 客队英文名

    返回:
    {
        scenario: "A"/"B"/"C"/"D" 或 None,
        kelly_min_filter_pass: bool (True=通过, 即无异常),
        ladbrokes_draw_kelly: float 或 None,
        bet365_kelly: {"胜": k, "平": k, "负": k} 或 None,
        betvictor_kelly: {"胜": k, "平": k, "负": k} 或 None,
        bet365_payout: float 或 None (Bet365实际返还率),
        betvictor_payout: float 或 None (BetVictor实际返还率),
        signal: str 或 None (信号描述),
        kellyUniqueSignal: str 或 None (唯独低于返还率信号),
        kellyUniqueDirection: "H"/"D"/"A" 或 None (唯独方向),
        kellyUniqueConfidence: int 或 None (置信度提升值),
    }
    """
    _empty = {"scenario": None, "kelly_min_filter_pass": True,
              "ladbrokes_draw_kelly": None, "bet365_kelly": None,
              "betvictor_kelly": None, "bet365_payout": None,
              "betvictor_payout": None, "signal": None,
              "kellyUniqueSignal": None, "kellyUniqueDirection": None,
              "kellyUniqueConfidence": None,
              "kellyReverseDirection": None, "kellyReverseSignal": None}

    if not bookmaker_odds or len(bookmaker_odds) < 2:
        return _empty

    # --- 1. 计算市场平均隐含概率 ---
    all_probs = {"胜": [], "平": [], "负": []}
    for bk_key, odds in bookmaker_odds.items():
        h_odds = odds.get("home", 0)
        d_odds = odds.get("draw", 0)
        a_odds = odds.get("away", 0)
        if h_odds <= 1 or d_odds <= 1 or a_odds <= 1:
            continue
        kp = calc_kelly_probs(h_odds, d_odds, a_odds)
        all_probs["胜"].append(kp["胜"])
        all_probs["平"].append(kp["平"])
        all_probs["负"].append(kp["负"])

    if not all_probs["胜"]:
        return _empty

    # 市场平均概率
    market_avg = {
        "胜": sum(all_probs["胜"]) / len(all_probs["胜"]),
        "平": sum(all_probs["平"]) / len(all_probs["平"]),
        "负": sum(all_probs["负"]) / len(all_probs["负"]),
    }

    # --- 2. 计算每家公司每个方向的 Kelly = odds × market_prob ---
    def _calc_direction_kelly(odds_dict):
        """返回 {"胜": kelly, "平": kelly, "负": kelly}"""
        return {
            "胜": odds_dict.get("home", 0) * market_avg["胜"],
            "平": odds_dict.get("draw", 0) * market_avg["平"],
            "负": odds_dict.get("away", 0) * market_avg["负"],
        }

    kelly_by_bookmaker = {}
    for bk_key, odds in bookmaker_odds.items():
        kelly_by_bookmaker[bk_key] = _calc_direction_kelly(odds)

    # --- 3. 获取 Bet365 和 BetVictor 的 Kelly 和返还率 ---
    bet365_kelly = kelly_by_bookmaker.get("bet365")
    betvictor_kelly = kelly_by_bookmaker.get("betvictor")
    bet365_payout = None
    betvictor_payout = None

    # 计算每家公司的实际返还率
    bet365_odds = bookmaker_odds.get("bet365", {})
    if bet365_odds.get("home", 0) > 1 and bet365_odds.get("draw", 0) > 1 and bet365_odds.get("away", 0) > 1:
        bet365_payout = 1 / (1/bet365_odds["home"] + 1/bet365_odds["draw"] + 1/bet365_odds["away"])
        bet365_payout = round(bet365_payout, 4)

    betvictor_odds = bookmaker_odds.get("betvictor", {})
    if betvictor_odds.get("home", 0) > 1 and betvictor_odds.get("draw", 0) > 1 and betvictor_odds.get("away", 0) > 1:
        betvictor_payout = 1 / (1/betvictor_odds["home"] + 1/betvictor_odds["draw"] + 1/betvictor_odds["away"])
        betvictor_payout = round(betvictor_payout, 4)

    if not bet365_kelly or not betvictor_kelly:
        return {**_empty,
                "bet365_kelly": bet365_kelly,
                "betvictor_kelly": betvictor_kelly,
                "bet365_payout": bet365_payout,
                "betvictor_payout": betvictor_payout}

    # --- 4. "唯独低于返还率"信号检测 ---
    kellyUniqueSignal = None
    kellyUniqueDirection = None
    kellyUniqueConfidence = None

    def _check_unique_below_payout(kelly_dict, payout_rate):
        """
        检查是否"唯独1个方向Kelly < 返还率"
        返回: (is_unique, below_direction_or_None)
        direction: "胜"/"平"/"负"
        """
        below_dirs = [d for d in ["胜", "平", "负"] if kelly_dict[d] < payout_rate]
        if len(below_dirs) == 1:
            return True, below_dirs[0]
        return False, None

    b365_unique, b365_unique_dir = _check_unique_below_payout(bet365_kelly, bet365_payout) if bet365_payout else (False, None)
    bv_unique, bv_unique_dir = _check_unique_below_payout(betvictor_kelly, betvictor_payout) if betvictor_payout else (False, None)

    # 两家一致：都满足"唯独"且方向相同
    if b365_unique and bv_unique and b365_unique_dir == bv_unique_dir:
        dir_map = {"胜": "H", "平": "D", "负": "A"}
        dir_cn = {"胜": "主胜", "平": "平局", "负": "客胜"}
        kellyUniqueDirection = dir_map[b365_unique_dir]
        kellyUniqueSignal = f"唯独低于返还率·{dir_cn[b365_unique_dir]}"
        # 平局方向不显著，不加提升
        if b365_unique_dir != "平":
            kellyUniqueConfidence = 15
        else:
            kellyUniqueConfidence = 0

    # --- 5. 找各公司最低 Kelly 方向（保留场景D逻辑作为备用） ---
    def _min_direction(kelly_dict):
        """返回 (最低方向, 最低值)"""
        items = list(kelly_dict.items())
        items.sort(key=lambda x: x[1])
        return items[0]

    b365_min_dir, b365_min_val = _min_direction(bet365_kelly)
    bv_min_dir, bv_min_val = _min_direction(betvictor_kelly)

    # --- 6. 分类场景 A/B/C/D ---
    # A: 两家最低Kelly均为平局
    # B: 两家最低Kelly相反（一胜一负）
    # C: 两家最低不同+至少一家平局
    # D: 两家最低相同且非平局
    scenario = None
    if b365_min_dir == "平" and bv_min_dir == "平":
        scenario = "A"
    elif (b365_min_dir == "胜" and bv_min_dir == "负") or (b365_min_dir == "负" and bv_min_dir == "胜"):
        scenario = "B"
    elif b365_min_dir == bv_min_dir and b365_min_dir != "平":
        scenario = "D"
    elif b365_min_dir != bv_min_dir and (b365_min_dir == "平" or bv_min_dir == "平"):
        scenario = "C"
    else:
        # 其他情况（如两家最低不同但都不是平局且不是严格相反）
        scenario = "C"

    # --- 7. 立博平局 Kelly ---
    ladbrokes_kelly = kelly_by_bookmaker.get("ladbrokes")
    ladbrokes_draw_kelly = ladbrokes_kelly.get("平") if ladbrokes_kelly else None

    # --- 8. Kelly < 0.87 异常过滤 ---
    all_kelly_values = []
    for bk_key, kelly_dict in kelly_by_bookmaker.items():
        for direction, k_val in kelly_dict.items():
            all_kelly_values.append(k_val)

    kelly_min_filter_pass = all(k >= KELLY_MIN_FILTER_THRESHOLD for k in all_kelly_values) if all_kelly_values else True

    # --- 9. 反向信号检测：两家最高Kelly方向一致 → 该方向出现率显著偏低 ---
    # 最高Kelly方向 = 庄家最不保护/最激进的方向
    kellyReverseDirection = None
    kellyReverseSignal = None

    def _max_direction(kelly_dict):
        """返回 (最高方向, 最高值)"""
        items = list(kelly_dict.items())
        items.sort(key=lambda x: -x[1])
        return items[0]

    b365_max_dir, b365_max_val = _max_direction(bet365_kelly)
    bv_max_dir, bv_max_val = _max_direction(betvictor_kelly)

    # 两家最高Kelly方向一致 → 反向信号
    if b365_max_dir == bv_max_dir:
        dir_map_rev = {"胜": "H", "平": "D", "负": "A"}
        dir_cn_rev = {"胜": "主胜", "平": "平局", "负": "客胜"}
        kellyReverseDirection = dir_map_rev[b365_max_dir]
        kellyReverseSignal = f"反向信号·排除{dir_cn_rev[b365_max_dir]}"

    # --- 10. 生成信号描述（保留场景D信号作为备用） ---
    signal = None
    if scenario == "D":
        min_dir = b365_min_dir  # D场景两家相同
        if min_dir == "负" and ladbrokes_draw_kelly is not None and ladbrokes_draw_kelly <= LADBROKES_DRAW_KELLY_MEDIAN:
            signal = "凯利D客胜+立博平局保护"
        elif min_dir == "胜" and ladbrokes_draw_kelly is not None and ladbrokes_draw_kelly <= LADBROKES_DRAW_KELLY_MEDIAN:
            signal = "凯利D主胜+立博平局保护"
    elif scenario == "B":
        if ladbrokes_draw_kelly is not None and ladbrokes_draw_kelly > LADBROKES_DRAW_KELLY_MEDIAN:
            signal = "立博不看好平局"

    if not kelly_min_filter_pass:
        signal = (signal + " · " if signal else "") + "凯利异常"

    return {
        "scenario": scenario,
        "kelly_min_filter_pass": kelly_min_filter_pass,
        "ladbrokes_draw_kelly": round(ladbrokes_draw_kelly, 4) if ladbrokes_draw_kelly else None,
        "bet365_kelly": {k: round(v, 4) for k, v in bet365_kelly.items()},
        "betvictor_kelly": {k: round(v, 4) for k, v in betvictor_kelly.items()},
        "bet365_payout": bet365_payout,
        "betvictor_payout": betvictor_payout,
        "signal": signal,
        "kellyUniqueSignal": kellyUniqueSignal,
        "kellyUniqueDirection": kellyUniqueDirection,
        "kellyUniqueConfidence": kellyUniqueConfidence,
        "kellyReverseDirection": kellyReverseDirection,
        "kellyReverseSignal": kellyReverseSignal,
    }


def predict_match(match: dict, teams: dict, kelly_data: dict = None) -> dict:
    """
    对单场比赛生成预测
    kelly_data: 可选的凯利场景分析数据，来自 calc_kelly_scenario()
    返回预测结果字典
    """
    home = match.get("home", "")
    away = match.get("away", "")

    # 获取球队实力
    hw = get_team_strength(teams, home)
    aw = get_team_strength(teams, away)

    # 计算 Elo 概率
    elo_probs = calc_elo_probs(hw, aw)

    # 解析赔率
    w, d, l, handicap_odds, odds_source = normalize_odds(match.get("odds", {}))
    has_odds = w is not None

    # 确定最终概率
    if has_odds:
        # 凯利策略：100% 基于赔率隐含概率
        probs = calc_kelly_probs(w, d, l)
    else:
        # Elo 降级
        probs = elo_probs

    # 按概率排序
    sorted_probs = sorted(probs.items(), key=lambda x: -x[1])
    max_prob = sorted_probs[0][1]
    second_prob = sorted_probs[1][1]

    # 概率差（sp = 凯利离散度）
    sp = max_prob - second_prob

    # 让球方向
    handicap_dir = get_handicap_direction(handicap_odds)
    handicapBonus = 0

    # ===== 置信度计算 =====
    # 基础置信度：ct = round((0.4 + sp*0.6 + handicapBonus*0.08) * 100)
    ct = round((0.4 + sp * 0.6 + handicapBonus * 0.08) * 100)

    # 凯利离散度调节
    if sp < 0.05:
        ct += 15
    elif sp < 0.10:
        ct += 5
    elif sp > 0.15:
        ct -= 15

    # 确保在合理范围
    ct = max(0, min(100, ct))

    # ===== 星级评定 =====
    if has_odds:
        if sp > 0.35:
            stars = 5
        elif sp > 0.25:
            stars = 4
        elif sp > 0.15:
            stars = 3
        elif sp > 0.08:
            stars = 2
        else:
            stars = 1
    else:
        if sp > 0.5:
            stars = 5
        elif sp > 0.4:
            stars = 4
        elif sp > 0.28:
            stars = 3
        elif sp > 0.15:
            stars = 2
        else:
            stars = 1

    # ===== 让球辅助判断：盘口方向与预测方向一致时 +1 星 =====
    if handicap_dir and handicap_dir == sorted_probs[0][0]:
        stars = min(5, stars + 1)
        handicapBonus = 1  # 用于置信度重算

    # 重算含让球加成的置信度
    ct = round((0.4 + sp * 0.6 + handicapBonus * 0.08) * 100)
    if sp < 0.05:
        ct += 15
    elif sp < 0.10:
        ct += 5
    elif sp > 0.15:
        ct -= 15
    ct = max(0, min(100, ct))

    # ===== Skip 判断 =====
    skip = False
    skip_reason = ""
    min_odds_val = min(w, d, l) if has_odds else max(1.30, 1 / max_prob)

    if min_odds_val <= 1.25:
        skip = True
        skip_reason = f"赔率过低（约{min_odds_val:.2f}），投注价值极低"
    if sp < 0.08:
        if not skip:
            skip = True
            skip_reason = "结果太不确定，各方向概率接近"

    # ===== 单/双选判断 =====
    prediction = ""
    pred_type = ""
    reason = ""
    double_pick = None

    if max_prob >= 0.60 and sp >= 0.20 and min_odds_val >= 1.40:
        # 单选
        pred_type = "single"
        prediction = sorted_probs[0][0]
        double_pick = None
        if has_odds:
            if prediction == "胜":
                reason = f"赔率看好主队({round(max_prob * 100)}%)"
            elif prediction == "负":
                reason = f"赔率看好客队({round(max_prob * 100)}%)"
            else:
                reason = f"赔率倾向平局({round(max_prob * 100)}%)"
            reason += f" · {odds_source}赔率"
        else:
            if prediction == "胜":
                reason = f"模型预测主胜概率{round(max_prob * 100)}%"
            elif prediction == "负":
                reason = f"模型预测客胜概率{round(max_prob * 100)}%"
            else:
                reason = f"模型预测平局概率{round(max_prob * 100)}%"
    else:
        # 双选
        pred_type = "double"
        main_pick = sorted_probs[0][0]

        # 确定第二选择（排除平局的赔率最高方向）
        if has_odds:
            odds_map = {"胜": w, "平": d, "负": l}
            remaining = [(r, odds_map.get(r, 1)) for r, p in sorted_probs[1:]]
            remaining.sort(key=lambda x: -x[1])  # 赔率从高到低
            upset = remaining[0][0]
        else:
            # Elo 模式：默认排除平局
            if main_pick == "胜":
                upset = "负"
            elif main_pick == "负":
                upset = "胜"
            else:
                upset = "胜"

        prediction = f"{main_pick}+{upset}"
        double_pick = [main_pick, upset]

        if max_prob >= 0.50 and sp >= 0.10:
            reason = f"方向偏{main_pick}({round(max_prob * 100)}%)，双选防冷"
        else:
            reason = "方向不够明确，双选覆盖"
        if has_odds:
            reason += f" · {odds_source}赔率"

    # ===== 凯利场景增强（基于多公司赔率的场景分析） =====
    kelly_scenario = None
    kelly_signal = None
    ladbrokes_draw_kelly = None
    kelly_unique_direction = None
    kelly_unique_signal = None
    kelly_reverse_direction = None
    kelly_reverse_signal = None

    if kelly_data and kelly_data.get("scenario"):
        kelly_scenario = kelly_data["scenario"]
        kelly_signal = kelly_data.get("signal")
        ladbrokes_draw_kelly = kelly_data.get("ladbrokes_draw_kelly")
        kelly_unique_direction = kelly_data.get("kellyUniqueDirection")
        kelly_unique_signal = kelly_data.get("kellyUniqueSignal")
        kelly_reverse_direction = kelly_data.get("kellyReverseDirection")
        kelly_reverse_signal = kelly_data.get("kellyReverseSignal")

        # --- Kelly异常过滤：任一方向Kelly<0.87 ---
        if not kelly_data.get("kelly_min_filter_pass", True):
            ct = max(0, ct - 10)
            if "凯利异常" not in reason:
                reason += " · 凯利异常"

        # --- "唯独低于返还率"信号增强（优先级高于场景D） ---
        if kelly_unique_direction and kelly_unique_direction != "D":
            # 非平局方向（H/A）增强，平局方向不增强
            if kelly_unique_direction == "H":
                # 唯独低于返还率·主胜：回测53.5%(基线42.8%)，最强单一信号之一
                # 置信度+20%，星级+1
                ct = min(100, ct + 20)
                stars = min(5, stars + 1)
                if kelly_unique_signal and kelly_unique_signal not in reason:
                    reason += f" · {kelly_unique_signal}"
            elif kelly_unique_direction == "A":
                # 唯独低于返还率·客胜：回测46.2%(基线30.7%)，置信度+15%，星级+1
                ct = min(100, ct + 15)
                stars = min(5, stars + 1)
                if kelly_unique_signal and kelly_unique_signal not in reason:
                    reason += f" · {kelly_unique_signal}"
            # D（平局方向）不增强

        # --- 场景D增强（作为备用信号） ---
        if kelly_scenario == "D":
            b365_kelly = kelly_data.get("bet365_kelly", {})
            # D场景：两家最低相同方向
            min_dir = min(b365_kelly, key=b365_kelly.get) if b365_kelly else None
            ldk = ladbrokes_draw_kelly

            # 仅当"唯独"信号未触发时才应用场景D增强
            if not kelly_unique_direction:
                if min_dir == "负" and ldk is not None and ldk <= LADBROKES_DRAW_KELLY_MEDIAN:
                    # 场景D客胜+立博平局保护：B365+BV覆盖率高，客胜加成调回+8%
                    ct = min(100, ct + 8)
                    if "凯利D客胜+立博平局保护" not in reason:
                        reason += " · 凯利D客胜+立博平局保护"
                elif min_dir == "胜" and ldk is not None and ldk <= LADBROKES_DRAW_KELLY_MEDIAN:
                    # 场景D主胜+立博平局保护：置信度+8%
                    ct = min(100, ct + 8)
                    if "凯利D主胜+立博平局保护" not in reason:
                        reason += " · 凯利D主胜+立博平局保护"

        # --- 场景B平局排除 ---
        elif kelly_scenario == "B":
            ldk = ladbrokes_draw_kelly
            if ldk is not None and ldk > LADBROKES_DRAW_KELLY_MEDIAN:
                # 立博不看好平局：如果是双选且包含平局，移除平局选项
                if pred_type == "double" and double_pick and "平" in double_pick:
                    # 移除平局，只保留另一选项（变单选）
                    remaining = [x for x in double_pick if x != "平"]
                    if remaining:
                        double_pick = remaining
                        prediction = remaining[0]
                        pred_type = "single"
                        if "立博不看好平局" not in reason:
                            reason += " · 立博不看好平局"

        # --- 反向信号处理 ---
        # 两家最高Kelly方向一致 → 该方向出现率显著偏低 → 排除该方向
        if kelly_reverse_direction:
            reverse_dir_map = {"H": "胜", "D": "平", "A": "负"}
            reverse_cn = {"H": "主胜", "D": "平局", "A": "客胜"}
            reverse_dir_cn = reverse_cn.get(kelly_reverse_direction, "")
            reverse_dir_zh = reverse_dir_map.get(kelly_reverse_direction, "")

            if pred_type == "double" and double_pick:
                # 双选：如果某个选择方向与反向信号冲突，排除该方向
                if reverse_dir_zh in double_pick:
                    remaining = [x for x in double_pick if x != reverse_dir_zh]
                    if remaining:
                        double_pick = remaining
                        if len(double_pick) == 1:
                            # 排除后只剩一个方向 → 变单选
                            prediction = double_pick[0]
                            pred_type = "single"
                        else:
                            prediction = "+".join(double_pick)
                        if kelly_reverse_signal and kelly_reverse_signal not in reason:
                            reason += f" · {kelly_reverse_signal}"
            elif pred_type == "single":
                # 单选：反向信号升级为置信度-10%惩罚（回测：反向信号排除命中率72.4%，排除正确率很高）
                if kelly_reverse_direction:
                    ct = max(0, ct - 10)
                    if kelly_reverse_signal and kelly_reverse_signal not in reason:
                        reason += f" · {kelly_reverse_signal}(置信度-10%)"

    return {
        "prediction": prediction,
        "type": pred_type,
        "skip": skip,
        "skipReason": skip_reason,
        "confidence": ct,
        "reason": reason,
        "doublePick": double_pick,
        "stars": stars,
        "hasOdds": has_odds,
        "spread": round(sp, 4),
        "probs": {r: round(p, 4) for r, p in sorted_probs},
        "handicapDir": handicap_dir,
        "kellyScenario": kelly_scenario,
        "kellySignal": kelly_signal,
        "ladbrokesDrawKelly": ladbrokes_draw_kelly,
        "kellyUniqueDirection": kelly_unique_direction,
        "kellyUniqueSignal": kelly_unique_signal,
        "kellyReverseDirection": kelly_reverse_direction,
        "kellyReverseSignal": kelly_reverse_signal,
    }


def fetch_github_file(token: str, repo: str, path: str, branch: str = "main") -> tuple:
    """
    从 GitHub 获取文件内容和 SHA
    返回 (content_dict_or_str, sha) 或 (None, None)
    """
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    params = {"ref": branch}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            import base64
            content = base64.b64decode(data["content"]).decode("utf-8")
            sha = data["sha"]
            return content, sha
        else:
            print(f"[WARN] 获取 {path} 失败: HTTP {resp.status_code}")
            return None, None
    except Exception as e:
        print(f"[ERROR] 获取 {path} 异常: {e}")
        return None, None


def push_github_file(token: str, repo: str, path: str, content: str, sha: str, branch: str = "main") -> bool:
    """推送文件到 GitHub"""
    import base64
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {
        "message": f"🤖 自动更新预测 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "sha": sha,
        "branch": branch,
    }
    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=30)
        if resp.status_code in (200, 201):
            print(f"[OK] 已推送 {path} 到 GitHub")
            return True
        else:
            print(f"[ERROR] 推送 {path} 失败: HTTP {resp.status_code} - {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"[ERROR] 推送 {path} 异常: {e}")
        return False


def convert_date_to_iso(date_str: str) -> str:
    """
    将日期转为 YYYYMMDD 格式
    输入可能是:
    - "2026-07-16T01:00:00+08:00" (ISO 8601)
    - "20260716" (已有格式)
    """
    if not date_str:
        return ""
    if len(date_str) == 8 and date_str.isdigit():
        return date_str
    try:
        # 尝试解析 ISO 格式
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%Y%m%d")
    except Exception:
        return date_str[:8] if len(date_str) >= 8 else date_str


def weekday_cn(date_str: str) -> str:
    """从 YYYYMMDD 或 ISO 日期获取中文星期"""
    try:
        if len(date_str) == 8 and date_str.isdigit():
            dt = datetime.strptime(date_str, "%Y%m%d")
        else:
            dt = datetime.fromisoformat(date_str)
        days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return days[dt.weekday()]
    except Exception:
        return ""


def format_match_time(match: dict) -> str:
    """格式化比赛时间显示（与前端一致: "07/16 周四 01:00"）"""
    date_iso = match.get("date", "")
    status = match.get("status", "")
    if status and "/" in status:
        # 已有格式 "7/16 周四 01:00" → 补零为 "07/16 周四 01:00"
        parts = status.split(" ", 1)
        if len(parts) == 2 and "/" in parts[0]:
            md = parts[0]
            m, d = md.split("/", 1)
            return f"{int(m):02d}/{int(d):02d} {parts[1]}"
        return status
    # 从 date 字段构造
    try:
        dt = datetime.fromisoformat(date_iso)
        mm = dt.strftime("%m")
        dd = dt.strftime("%d")
        wd = weekday_cn(date_iso)
        hh = dt.strftime("%H:%M")
        return f"{mm}/{dd} {wd} {hh}"
    except Exception:
        return date_iso


# ===== 联赛代码 -> Odds API 运动键名映射 =====
_ODDS_API_LEAGUE_MAP = {
    "fifa.world": "soccer_fifa_world_cup",
    "uefa.champions": "soccer_uefa_champs_league",
    "uefa.champions.qual": "soccer_uefa_champs_league_qualification",
    "uefa.europa": "soccer_uefa_europa_league",
    "eng.1": "soccer_epl",
    "esp.1": "soccer_spain_la_liga",
    "ger.1": "soccer_germany_bundesliga",
    "ita.1": "soccer_italy_ser_a",
    "fra.1": "soccer_france_ligue_one",
    "ned.1": "soccer_netherlands_eredivisie",
    "bel.1": "soccer_belgium_first_div",
    "por.1": "soccer_portugal_primeira_liga",
    "tur.1": "soccer_turkey_super_lig",
    "usa.1": "soccer_usa_mls",
    "mls": "soccer_usa_mls",
    "mex.1": "soccer_mexico_ligamx",
    "bra.1": "soccer_brazil_campeonato",
    "jpn.1": "soccer_japan_j_league",
    "kor.1": "soccer_korea_kleague1",
    "swe.1": "soccer_sweden_allsvenskan",
    "nor.1": "soccer_norway_eliteserien",
    "fin.1": "soccer_finland_veikkausliiga",
    "arg.1": "soccer_argentina_primera_division",
    "aut.1": "soccer_austria_bundesliga",
}

ODDS_API_KEY = "0b8808a6d42b077c4f4016737004f22b"

# 竞彩/北单支持的联赛代码（不含中超）
# 只对这些联赛生成预测，并纳入命中率统计
ACTIVE_LEAGUE_CODES = {
    # ===== 五大联赛（竞彩核心场次） =====
    "eng.1",           # 英超
    "esp.1",           # 西甲
    "ger.1",           # 德甲
    "ita.1",           # 意甲
    "fra.1",           # 法甲
    # ===== 欧洲其他联赛 =====
    "ned.1",           # 荷甲
    "bel.1",           # 比甲
    "por.1",           # 葡超
    "tur.1",           # 土超
    "aut.1",           # 奥超
    "nor.1",           # 挪超
    "swe.1",           # 瑞典超
    "fin.1",           # 芬超
    # ===== 亚洲联赛 =====
    "jpn.1",           # 日职
    "kor.1",           # 韩职
    # ===== 美洲联赛 =====
    "mls", "usa.1",    # 美职
    "bra.1",           # 巴甲
    "arg.1",           # 阿甲
    # ===== 国际赛事 =====
    "uefa.champions",  # 欧冠
    "uefa.champions.qual",  # 欧冠资格赛
    "uefa.europa",     # 欧联
    "fifa.world",      # 世界杯
}


def _build_en_to_cn(teams_db: dict) -> dict:
    """从球队数据库构建 英文名->中文名 的反向映射"""
    en_to_cn = {}
    for en_name, info in teams_db.items():
        cn_name = info.get("name_cn", "")
        if cn_name:
            en_to_cn[en_name.lower()] = cn_name
    # 补充常见世界杯球队映射（可能不在 _TEAM_DB_RAW 中）
    extra = {
        "france": "法国", "germany": "德国", "brazil": "巴西", "england": "英格兰",
        "argentina": "阿根廷", "spain": "西班牙", "portugal": "葡萄牙", "netherlands": "荷兰",
        "belgium": "比利时", "croatia": "克罗地亚", "morocco": "摩洛哥", "italy": "意大利",
        "uruguay": "乌拉圭", "colombia": "哥伦比亚", "senegal": "塞内加尔", "japan": "日本",
        "south korea": "韩国", "usa": "美国", "mexico": "墨西哥", "switzerland": "瑞士",
        "denmark": "丹麦", "austria": "奥地利", "turkey": "土耳其", "poland": "波兰",
        "serbia": "塞尔维亚", "sweden": "瑞典", "ghana": "加纳", "iran": "伊朗",
        "australia": "澳大利亚", "saudi arabia": "沙特", "qatar": "卡塔尔", "russia": "俄罗斯",
        "norway": "挪威", "canada": "加拿大", "ecuador": "厄瓜多尔", "wales": "威尔士",
        "tunisia": "突尼斯", "cameroon": "喀麦隆", "nigeria": "尼日利亚", "south africa": "南非",
        "ghana": "加纳", "costa rica": "哥斯达黎加", "panama": "巴拿马", "peru": "秘鲁",
        "uruguay": "乌拉圭", "paraguay": "巴拉圭", "chile": "智利", "bolivia": "玻利维亚",
    }
    for en, cn in extra.items():
        if en not in en_to_cn:
            en_to_cn[en] = cn
    return en_to_cn


def _build_schedule_en_map(all_matches: list) -> dict:
    """从赛程构建 matchId -> {homeEN, awayEN} 映射"""
    m = {}
    for match in all_matches:
        mid = match.get("id", "")
        home_en = match.get("homeEN", "")
        away_en = match.get("awayEN", "")
        if mid and (home_en or away_en):
            m[mid] = {"homeEN": home_en, "awayEN": away_en}
    return m


def _build_schedule_name_map(all_matches: list) -> dict:
    """从赛程构建 英文名->中文名 的直接映射（利用赛程中已有的中英对照）"""
    m = {}
    for match in all_matches:
        home_cn = match.get("home", "")
        away_cn = match.get("away", "")
        home_en = match.get("homeEN", "")
        away_en = match.get("awayEN", "")
        if home_en and home_cn:
            m[_normalize_name(home_en)] = home_cn
        if away_en and away_cn:
            m[_normalize_name(away_en)] = away_cn
    return m


def _normalize_name(name: str) -> str:
    """标准化球队名称用于模糊匹配（去重音、特殊字符）"""
    if not name:
        return ""
    import unicodedata
    # 先做 Unicode 规范化（去重音符号：ö→o, ã→a, í→i 等）
    name = unicodedata.normalize('NFKD', name)
    name = ''.join(c for c in name if not unicodedata.combining(c))
    name = name.lower().strip()
    for ch in ['-', '.', '_', "'", '(', ')', '/', '&']:
        name = name.replace(ch, ' ')
    while '  ' in name:
        name = name.replace('  ', ' ')
    return name.strip()


def _fuzzy_en_match(name_a: str, name_b: str) -> bool:
    """模糊匹配两个已标准化的英文队名"""
    if not name_a or not name_b:
        return False
    if name_a == name_b:
        return True
    
    # 去掉常见后缀/缩写在比较
    suffixes_to_remove = [' fc', ' sc', ' cf', ' sk', ' bk', ' if', ' fk']
    a_clean = name_a
    b_clean = name_b
    for s in suffixes_to_remove:
        a_clean = a_clean.replace(s, '')
        b_clean = b_clean.replace(s, '')
    a_clean = a_clean.strip()
    b_clean = b_clean.strip()
    
    if a_clean == b_clean:
        return True
    # 一个包含另一个
    if a_clean in b_clean or b_clean in a_clean:
        return True
    
    # 拆分单词，检查核心词是否重叠超过50%
    words_a = set(a_clean.split())
    words_b = set(b_clean.split())
    if words_a and words_b:
        common = words_a & words_b
        # 去掉太常见的词
        common -= {'of', 'the', 'de', 'la', 'le', 'el', 'en'}
        # 至少有一个核心共同词，且共同词占较短集合的50%以上
        if common and len(common) >= min(len(words_a), len(words_b)) * 0.5:
            return True
    
    return False


def _match_team(api_name: str, pred_name: str, en_to_cn: dict, schedule_en: str = "", schedule_name_map: dict = None) -> bool:
    """判断 API 返回的队名与预测中的中文名是否匹配"""
    if not api_name or not pred_name:
        return False

    api_norm = _normalize_name(api_name)
    pred_norm = _normalize_name(pred_name)
    if schedule_name_map is None:
        schedule_name_map = {}

    # 方法1: 通过 schedule_name_map 直接匹配（最可靠，来自赛程中英对照）
    cn_from_sched_map = schedule_name_map.get(api_norm, "")
    if cn_from_sched_map and _normalize_name(cn_from_sched_map) == pred_norm:
        return True

    # 方法2: 通过英文反向映射（球队数据库）
    cn_from_db = en_to_cn.get(api_norm, "")
    if cn_from_db and _normalize_name(cn_from_db) == pred_norm:
        return True

    # 方法3: 通过 schedule_en 参数（旧的兼容方式）
    if schedule_en:
        sched_norm = _normalize_name(schedule_en)
        cn_from_sched = en_to_cn.get(sched_norm, "")
        if cn_from_sched and _normalize_name(cn_from_sched) == pred_norm:
            return True
        # 也尝试 schedule_name_map
        cn2 = schedule_name_map.get(sched_norm, "")
        if cn2 and _normalize_name(cn2) == pred_norm:
            return True

    # 方法4: 模糊匹配 - 中文名包含关系
    candidates = set()
    if cn_from_sched_map:
        candidates.add(cn_from_sched_map)
    if cn_from_db:
        candidates.add(cn_from_db)
    for candidate in candidates:
        c_norm = _normalize_name(candidate)
        if c_norm == pred_norm:
            return True
        # 去掉 FC 等后缀
        c1 = c_norm.replace("fc", "").replace("cf", "").strip()
        c2 = pred_norm.replace("fc", "").replace("cf", "").strip()
        if c1 and c2 and (c1 in c2 or c2 in c1):
            return True

    # 方法5: 英文名标准化后直接包含匹配（处理API名称与schedule名称略有差异的情况）
    if schedule_en:
        se_norm = _normalize_name(schedule_en)
        if se_norm and api_norm and (se_norm in api_norm or api_norm in se_norm):
            # 英文名高度相似，认为是同一支球队
            # 再验证中文名是否也有关联
            cn_via_se = schedule_name_map.get(se_norm, "")
            if cn_via_se:
                cn_se_norm = _normalize_name(cn_via_se)
                if cn_se_norm and pred_norm and (cn_se_norm in pred_norm or pred_norm in cn_se_norm):
                    return True

    return False


async def _fetch_odds_api_scores(league_code: str) -> list:
    """通过 The Odds API 获取比赛结果"""
    sport_key = _ODDS_API_LEAGUE_MAP.get(league_code)
    if not sport_key:
        return []

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/"
    params = {"apiKey": ODDS_API_KEY, "daysFrom": 3}  # 免费版只支持1-3
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            events = resp.json()
            results = []
            for evt in events:
                scores = evt.get("scores") or []
                if not scores or len(scores) < 2:
                    continue
                home_team = evt.get("home_team", "")
                away_team = evt.get("away_team", "")
                home_score = next((int(s["score"]) for s in scores if s.get("name") == home_team), None)
                away_score = next((int(s["score"]) for s in scores if s.get("name") == away_team), None)
                if home_score is not None and away_score is not None:
                    results.append({
                        "homeEN": home_team,
                        "awayEN": away_team,
                        "homeScore": home_score,
                        "awayScore": away_score,
                        "commence_time": evt.get("commence_time", ""),
                    })
            return results
        else:
            print(f"[WARN] Odds API {league_code} 返回 HTTP {resp.status_code}")
    except Exception as e:
        print(f"[WARN] Odds API {league_code} 异常: {e}")
    return []


async def _fetch_odds_api_odds(league_code: str) -> list:
    """
    通过 The Odds API /odds/ 端点获取多公司赔率数据
    用于凯利场景分析（需要多家公司的赔率对比）

    返回: [{homeEN, awayEN, commence_time, bookmakers: {key: {home, draw, away}, ...}}]
    """
    sport_key = _ODDS_API_LEAGUE_MAP.get(league_code)
    if not sport_key:
        return []

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,uk",
        "markets": "h2h",
    }
    try:
        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code == 200:
            events = resp.json()
            results = []
            for evt in events:
                home_team = evt.get("home_team", "")
                away_team = evt.get("away_team", "")
                commence_time = evt.get("commence_time", "")
                bookmakers_data = evt.get("bookmakers", [])

                # 提取关键公司的赔率
                bookmakers = {}
                for bm in bookmakers_data:
                    bm_key = bm.get("key", "")
                    # 只提取核心博彩公司的赔率
                    internal_key = _KEY_BOOKMAKERS.get(bm_key)
                    if not internal_key:
                        continue
                    # 跳过交易所（betfair_ex 等）
                    if "ex_" in bm_key:
                        continue
                    markets = bm.get("markets", [])
                    h2h_market = None
                    for mkt in markets:
                        if mkt.get("key") == "h2h":
                            h2h_market = mkt
                            break
                    if not h2h_market:
                        continue
                    outcomes = h2h_market.get("outcomes", [])
                    home_odds = None
                    draw_odds = None
                    away_odds = None
                    for oc in outcomes:
                        name = oc.get("name", "")
                        price = oc.get("price", 0)
                        if name == home_team:
                            home_odds = price
                        elif name == away_team:
                            away_odds = price
                        elif name == "Draw":
                            draw_odds = price
                    if home_odds and draw_odds and away_odds:
                        bookmakers[internal_key] = {
                            "home": home_odds,
                            "draw": draw_odds,
                            "away": away_odds,
                        }

                # 至少需要 bet365 + betvictor 才有场景分析价值
                if "bet365" in bookmakers and "betvictor" in bookmakers:
                    results.append({
                        "homeEN": home_team,
                        "awayEN": away_team,
                        "commence_time": commence_time,
                        "bookmakers": bookmakers,
                    })
            if results:
                print(f"[OK] Odds API {league_code}: {len(results)} 场含多公司赔率")
            return results
        else:
            print(f"[WARN] Odds API /odds/ {league_code} 返回 HTTP {resp.status_code}")
    except Exception as e:
        print(f"[WARN] Odds API /odds/ {league_code} 异常: {e}")
    return []


async def _fetch_world_cup_results() -> list:
    """通过 wcup2026.org 免费 API 获取世界杯比赛结果"""
    url = "https://wcup2026.org/api/data.php?action=results&limit=50"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok") and data.get("matches"):
                results = []
                for m in data["matches"]:
                    if m.get("status") != "finished":
                        continue
                    score = m.get("score") or [None, None]
                    if score[0] is not None and score[1] is not None:
                        results.append({
                            "homeEN": m.get("team1", ""),
                            "awayEN": m.get("team2", ""),
                            "homeScore": int(score[0]),
                            "awayScore": int(score[1]),
                            "commence_time": m.get("datetime", ""),
                        })
                return results
    except Exception as e:
        print(f"[WARN] 世界杯 API 异常: {e}")
    return []


async def verify_predictions(predictions: list, all_matches: list):
    """验证已完赛的预测，更新 verified / actualResult / hit 字段"""
    teams = parse_team_db(_TEAM_DB_RAW)
    en_to_cn = _build_en_to_cn(teams)
    schedule_en_map = _build_schedule_en_map(all_matches)
    schedule_name_map = _build_schedule_name_map(all_matches)
    print(f"[DEBUG] schedule_name_map 大小: {len(schedule_name_map)}")

    today = datetime.now(timezone(timedelta(hours=8)))
    today_str = today.strftime("%Y%m%d")

    # 找出需要验证的预测：日期已过且未验证
    to_verify = []
    for p in predictions:
        if p.get("verified"):
            continue
        pred_date = p.get("date", "")
        if not pred_date:
            continue
        # 比赛日期在今天之前（不含今天，今天的比赛可能还没完）
        if pred_date < today_str:
            to_verify.append(p)

    if not to_verify:
        print("[INFO] 无需验证的预测")
        return

    print(f"[INFO] 待验证预测: {len(to_verify)} 条")

    # 收集需要查询的联赛
    leagues_needed = set()
    has_world_cup = False
    for p in to_verify:
        lc = p.get("leagueCode", "")
        if lc == "fifa.world":
            has_world_cup = True
        elif lc in _ODDS_API_LEAGUE_MAP:
            leagues_needed.add(lc)

    # 获取各来源的比分数据
    results_by_source = {}

    # 世界杯专用 API（免费，不消耗配额）
    if has_world_cup:
        wc_results = await _fetch_world_cup_results()
        results_by_source["fifa.world"] = wc_results
        print(f"[INFO] 世界杯结果: {len(wc_results)} 场")

    # The Odds API（按联赛逐个获取）
    for lc in leagues_needed:
        results = await _fetch_odds_api_scores(lc)
        results_by_source[lc] = results
        if results:
            print(f"[INFO] {lc} 结果: {len(results)} 场")

    # 逐条验证
    verified_count = 0
    hit_count = 0
    for p in to_verify:
        lc = p.get("leagueCode", "")
        results = results_by_source.get(lc, [])
        if not results:
            continue

        pred_home = p.get("home", "")
        pred_away = p.get("away", "")
        mid = p.get("matchId", "")
        sched_en = schedule_en_map.get(mid, {})
        sched_home_en = sched_en.get("homeEN", "")
        sched_away_en = sched_en.get("awayEN", "")

        matched_result = None
        for r in results:
            # 优先使用 matchId 从 schedule 获取英文名，再做模糊匹配
            # 这是最可靠的方式：schedule 已知每场比赛的英文名
            if sched_home_en and sched_away_en:
                sh_norm = _normalize_name(sched_home_en)
                sa_norm = _normalize_name(sched_away_en)
                rh_norm = _normalize_name(r["homeEN"])
                ra_norm = _normalize_name(r["awayEN"])
                
                # 正向匹配：schedule主队==API主队 且 schedule客队==API客队
                if _fuzzy_en_match(sh_norm, rh_norm) and _fuzzy_en_match(sa_norm, ra_norm):
                    matched_result = r
                    break
                # 交叉匹配（主客颠倒）
                if _fuzzy_en_match(sh_norm, ra_norm) and _fuzzy_en_match(sa_norm, rh_norm):
                    matched_result = {
                        "homeEN": pred_home, "awayEN": pred_away,
                        "homeScore": r["awayScore"], "awayScore": r["homeScore"],
                    }
                    break
            
            # 回退：用旧的中文名匹配逻辑
            home_match = _match_team(r["homeEN"], pred_home, en_to_cn, sched_home_en, schedule_name_map)
            away_match = _match_team(r["awayEN"], pred_away, en_to_cn, sched_away_en, schedule_name_map)
            if home_match and away_match:
                matched_result = r
                break
            if home_match and not away_match:
                away_match2 = _match_team(r["awayEN"], pred_home, en_to_cn, sched_home_en, schedule_name_map)
                home_match2 = _match_team(r["homeEN"], pred_away, en_to_cn, sched_away_en, schedule_name_map)
                if away_match2 and home_match2:
                    matched_result = {
                        "homeEN": pred_home, "awayEN": pred_away,
                        "homeScore": r["awayScore"], "awayScore": r["homeScore"],
                    }
                    break

        if not matched_result:
            continue

        hs = matched_result["homeScore"]
        aws = matched_result["awayScore"]

        # 确定实际结果
        if hs > aws:
            actual = "胜"
        elif hs < aws:
            actual = "负"
        else:
            actual = "平"

        # 判断是否命中
        pred_text = p.get("prediction", "")
        pred_type = p.get("type", "")
        double_pick = p.get("doublePick") or []

        if pred_type == "single":
            hit = (pred_text == actual)
        elif pred_type == "double":
            hit = actual in double_pick
        else:
            hit = (actual in pred_text)

        p["verified"] = True
        p["actualResult"] = actual
        p["hit"] = hit
        p["homeScore"] = hs
        p["awayScore"] = aws
        verified_count += 1
        if hit:
            hit_count += 1
        print(f"[VERIFY] {p.get('matchTime','')} {pred_home} {hs}-{aws} {pred_away} | 预测:{pred_text} 实际:{actual} {'✅' if hit else '❌'}")

    print(f"[OK] 验证完成: {verified_count} 场已验证, 命中 {hit_count} 场")


async def main():
    result_mode = sys.argv[1] if len(sys.argv) > 1 else "display_only"
    
    # 读取配置：优先从环境变量/参数获取，其次从配置文件
    _config = {}
    _config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
    if os.path.exists(_config_path):
        try:
            with open(_config_path, "r") as _f:
                _config = json.load(_f)
        except Exception:
            pass
    
    github_token = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "ceshi1986/football-predictions" else _config.get("github_token", os.environ.get("GITHUB_TOKEN", "YOUR_TOKEN_HERE"))
    github_repo = sys.argv[3] if len(sys.argv) > 3 else (sys.argv[2] if len(sys.argv) > 2 and "/" in sys.argv[2] else _config.get("github_repo", "ceshi1986/football-predictions"))

    print(f"[参数] result_mode={result_mode}, repo={github_repo}")

    sdk = CodeActSDK()

    try:
        # ===== 1. 构建球队实力数据库 =====
        teams = parse_team_db(_TEAM_DB_RAW)
        print(f"[OK] 球队实力库: {len(teams)} 支球队")

        # ===== 2. 从 GitHub 获取赛程 =====
        print("[INFO] 获取赛程数据...")
        schedule_content, _ = fetch_github_file(github_token, github_repo, "schedule.json")
        if not schedule_content:
            # 尝试通过 codeact_fetch_web 兜底
            print("[WARN] GitHub API 获取 schedule.json 失败，尝试 fetch_web...")
            fetch_result = await sdk.call_tool(
                "codeact_fetch_web",
                {"url": f"https://raw.githubusercontent.com/{github_repo}/main/schedule.json"},
                schema_version=TOOL_SCHEMA_VERSIONS["codeact_fetch_web"],
            )
            if fetch_result.get("is_success"):
                schedule_content = fetch_result.get("content", "")
            else:
                raise RuntimeError("无法获取赛程数据")

        schedule = json.loads(schedule_content)
        all_matches = schedule.get("matches", [])
        # 队名映射修正：将占位名称替换为真实球队名
        _TEAM_NAME_FIX = {
            "760517": {"home": "西班牙", "away": "阿根廷"},  # 世界杯半决赛
        }
        for m in all_matches:
            mid = m.get("id", "")
            if mid in _TEAM_NAME_FIX:
                fix = _TEAM_NAME_FIX[mid]
                if m.get("home", "") != fix["home"] or m.get("away", "") != fix["away"]:
                    print(f"[FIX] 队名修正: {m.get('home','')} vs {m.get('away','')} -> {fix['home']} vs {fix['away']}")
                    m["home"] = fix["home"]
                    m["away"] = fix["away"]
        print(f"[OK] 赛程: {len(all_matches)} 场比赛")

        # ===== 3. 获取历史预测 =====
        print("[INFO] 获取历史预测...")
        predictions_content, predictions_sha = fetch_github_file(
            github_token, github_repo, "data/ai-predictions.json"
        )
        existing_predictions = []
        if predictions_content:
            pred_data = json.loads(predictions_content)
            existing_predictions = pred_data.get("predictions", [])
            print(f"[OK] 历史预测: {len(existing_predictions)} 条")
        else:
            predictions_sha = None
            print("[WARN] 无历史预测数据，将创建新文件")

        # ===== 4. 验证已完赛但未验证的预测 =====
        await verify_predictions(existing_predictions, all_matches)

        # ===== 5. 构建已有预测索引 =====
        pred_map = {}  # matchId -> prediction
        for p in existing_predictions:
            pred_map[p.get("matchId", "")] = p

        # ===== 6. 过滤未开赛的比赛（仅竞彩/北单联赛） =====
        today = datetime.now(timezone(timedelta(hours=8)))
        today_str = today.strftime("%Y%m%d")
        print(f"[INFO] 今日日期: {today_str}")

        upcoming = []
        skipped_leagues = set()
        for m in all_matches:
            if m.get("statusClass") != "scheduled":
                continue
            if m.get("completed"):
                continue
            league_code = m.get("league", "")
            if league_code not in ACTIVE_LEAGUE_CODES:
                skipped_leagues.add(league_code)
                continue
            upcoming.append(m)

        print(f"[INFO] 未开赛比赛: {len(upcoming)} 场（已过滤非竞彩联赛: {skipped_leagues}）")

        # ===== 6.5 获取多公司赔率（用于凯利场景分析） =====
        print("[INFO] 获取多公司赔率数据（凯利场景分析）...")
        odds_api_data = {}  # league_code -> [odds_event, ...]
        # 收集有未开赛比赛的联赛
        leagues_with_upcoming = set(m.get("league", "") for m in upcoming)
        for lc in leagues_with_upcoming:
            if lc not in _ODDS_API_LEAGUE_MAP:
                continue
            odds_data = await _fetch_odds_api_odds(lc)
            if odds_data:
                odds_api_data[lc] = odds_data
                await asyncio.sleep(0.5)  # API配额保护，间隔0.5秒
        total_odds_events = sum(len(v) for v in odds_api_data.values())
        print(f"[OK] 多公司赔率: {len(odds_api_data)} 个联赛, {total_odds_events} 场比赛")

        # 构建比赛匹配索引：(homeEN_norm, awayEN_norm) -> odds_event
        odds_match_index = {}
        for lc, events in odds_api_data.items():
            for evt in events:
                key = (_normalize_name(evt["homeEN"]), _normalize_name(evt["awayEN"]))
                odds_match_index[key] = evt

        # 构建 schedule 英文名映射，用于匹配 The Odds API 队名
        schedule_en_map_for_odds = _build_schedule_en_map(all_matches)

        # ===== 7. 生成新预测 =====
        new_count = 0
        update_count = 0
        keep_count = 0

        for m in upcoming:
            match_id = m.get("id", "")
            date_iso = convert_date_to_iso(m.get("date", ""))

            existing = pred_map.get(match_id)

            # 保留已验证的旧预测
            if existing and existing.get("verified"):
                keep_count += 1
                continue

            # 队名校验：跳过占位名称（如"决赛"、"半决赛胜者2"等）
            _home = m.get("home", "")
            _away = m.get("away", "")
            _PLACEHOLDER_KEYWORDS = ("决赛", "半决赛胜者", "1/4决赛胜者", "Winner", "TBD", "待定")
            if any(kw in _home or kw in _away for kw in _PLACEHOLDER_KEYWORDS):
                # 尝试从已知的半决赛对阵映射修正队名
                _KNOWN_MAPPINGS = {
                    "760517": {"home": "西班牙", "away": "阿根廷"},  # 世界杯半决赛2
                }
                if match_id in _KNOWN_MAPPINGS:
                    km = _KNOWN_MAPPINGS[match_id]
                    if any(kw in _home for kw in _PLACEHOLDER_KEYWORDS):
                        m["home"] = km["home"]
                        _home = km["home"]
                    if any(kw in _away for kw in _PLACEHOLDER_KEYWORDS):
                        m["away"] = km["away"]
                        _away = km["away"]
                    print(f"[FIX] 占位名称已修正: {_home} vs {_away}")
                else:
                    print(f"[SKIP] 占位球队名: {match_id} {_home} vs {_away}，跳过")
                    continue

            # 匹配 The Odds API 多公司赔率数据
            kelly_data = None
            match_league = m.get("league", "")
            sched_en = schedule_en_map_for_odds.get(match_id, {})
            sched_home_en = sched_en.get("homeEN", "")
            sched_away_en = sched_en.get("awayEN", "")

            # 方法1: 通过 schedule 中的英文名精确匹配
            matched_odds_evt = None
            if sched_home_en and sched_away_en:
                key = (_normalize_name(sched_home_en), _normalize_name(sched_away_en))
                matched_odds_evt = odds_match_index.get(key)
                # 尝试主客颠倒
                if not matched_odds_evt:
                    key_rev = (_normalize_name(sched_away_en), _normalize_name(sched_home_en))
                    matched_odds_evt = odds_match_index.get(key_rev)

            # 方法2: 通过模糊匹配（遍历同联赛的所有赔率事件）
            if not matched_odds_evt and match_league in odds_api_data:
                for evt in odds_api_data[match_league]:
                    if _fuzzy_en_match(_normalize_name(evt["homeEN"]), _normalize_name(sched_home_en or _home)) and \
                       _fuzzy_en_match(_normalize_name(evt["awayEN"]), _normalize_name(sched_away_en or _away)):
                        matched_odds_evt = evt
                        break

            if matched_odds_evt:
                kelly_data = calc_kelly_scenario(
                    matched_odds_evt["bookmakers"],
                    matched_odds_evt["homeEN"],
                    matched_odds_evt["awayEN"],
                )
                if kelly_data.get("scenario"):
                    unique_tag = ""
                    if kelly_data.get("kellyUniqueDirection") and kelly_data.get("kellyUniqueSignal"):
                        dir_label = {"H": "主胜", "D": "平局", "A": "客胜"}.get(kelly_data["kellyUniqueDirection"], kelly_data["kellyUniqueDirection"])
                        unique_tag = f" [唯独{dir_label}]"
                    reverse_tag = ""
                    if kelly_data.get("kellyReverseDirection") and kelly_data.get("kellyReverseSignal"):
                        rev_dir_label = {"H": "排除主胜", "D": "排除平局", "A": "排除客胜"}.get(kelly_data["kellyReverseDirection"], kelly_data["kellyReverseDirection"])
                        reverse_tag = f" [反向{rev_dir_label}]"
                    print(f"[KELLY] {_home} vs {_away}: 场景{kelly_data['scenario']} {kelly_data.get('signal', '')}{unique_tag}{reverse_tag}")

            # 生成新预测
            pred = predict_match(m, teams, kelly_data=kelly_data)

            # 构建预测记录
            record = {
                "matchId": match_id,
                "home": m.get("home", ""),
                "away": m.get("away", ""),
                "league": m.get("leagueShort", m.get("leagueName", "")),
                "leagueCode": m.get("league", ""),
                "date": date_iso,
                "matchTime": format_match_time(m),
                "prediction": pred["prediction"],
                "type": pred["type"],
                "confidence": pred["confidence"],
                "skip": pred["skip"],
                "skipReason": pred["skipReason"],
                "reason": pred["reason"],
                "doublePick": pred["doublePick"],
                "stars": pred["stars"],
                "hasOdds": pred["hasOdds"],
                "spread": pred["spread"],
                "handicapDir": pred.get("handicapDir"),
                "kellyScenario": pred.get("kellyScenario"),
                "kellySignal": pred.get("kellySignal"),
                "ladbrokesDrawKelly": pred.get("ladbrokesDrawKelly"),
                "kellyUniqueDirection": pred.get("kellyUniqueDirection"),
                "kellyUniqueSignal": pred.get("kellyUniqueSignal"),
                "kellyReverseDirection": pred.get("kellyReverseDirection"),
                "kellyReverseSignal": pred.get("kellyReverseSignal"),
                "verified": False,
                "actualResult": None,
                "hit": None,
            }

            if existing and not existing.get("verified"):
                # 更新未验证的预测
                update_count += 1
                pred_map[match_id] = record
            else:
                # 新增预测
                new_count += 1
                pred_map[match_id] = record

        # ===== 8. 组装最终预测列表 =====
        # 保留所有已验证的旧预测 + 新的/更新的未验证预测
        final_predictions = []

        # 先添加已验证的（按日期排序）
        verified_preds = [p for p in existing_predictions if p.get("verified")]
        verified_preds.sort(key=lambda x: x.get("date", ""))
        final_predictions.extend(verified_preds)
        print(f"[DEBUG] 已验证旧预测: {len(verified_preds)} 条")

        # 再添加未验证的（新的和更新的）
        unverified_preds = [p for mid, p in pred_map.items() if not p.get("verified")]
        unverified_preds.sort(key=lambda x: x.get("date", ""))
        final_predictions.extend(unverified_preds)
        print(f"[DEBUG] 未验证预测: {len(unverified_preds)} 条 (新增{new_count}+更新{update_count})")

        print(f"[INFO] 预测统计: 保留已验证 {keep_count}, 更新 {update_count}, 新增 {new_count}")

        # ===== 9. 推送到 GitHub =====
        output_data = {
            "lastUpdated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + 
                           f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
            "predictions": final_predictions,
        }
        output_json = json.dumps(output_data, ensure_ascii=False, indent=2)

        push_success = False
        if predictions_sha:
            push_success = push_github_file(
                github_token, github_repo, "data/ai-predictions.json",
                output_json, predictions_sha,
            )
        else:
            # 文件可能不存在，尝试创建（不需要 SHA）
            print("[INFO] ai-predictions.json SHA 为空，尝试重新获取...")
            _, retry_sha = fetch_github_file(
                github_token, github_repo, "data/ai-predictions.json"
            )
            if retry_sha:
                push_success = push_github_file(
                    github_token, github_repo, "data/ai-predictions.json",
                    output_json, retry_sha,
                )
            else:
                # 创建新文件（PUT 请求不带 SHA）
                print("[INFO] 尝试创建新文件 data/ai-predictions.json...")
                import base64 as _b64
                url = f"https://api.github.com/repos/{github_repo}/contents/data/ai-predictions.json"
                headers = {
                    "Authorization": f"token {github_token}",
                    "Accept": "application/vnd.github.v3+json",
                }
                payload = {
                    "message": f"🤖 初始化预测文件 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    "content": _b64.b64encode(output_json.encode("utf-8")).decode("utf-8"),
                    "branch": "main",
                }
                try:
                    resp = requests.put(url, headers=headers, json=payload, timeout=30)
                    if resp.status_code in (200, 201):
                        print("[OK] 已创建 data/ai-predictions.json")
                        push_success = True
                    else:
                        print(f"[WARN] 创建失败: HTTP {resp.status_code}")
                except Exception as e:
                    print(f"[WARN] 创建异常: {e}")

        # ===== 10. 保存本地备份 =====
        local_path = "./codeact/output/ai-predictions.json"
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"[OK] 本地备份: {local_path}")

        # ===== 11. 生成今日预测摘要 =====
        today_preds = [p for p in final_predictions if p.get("date") == today_str and not p.get("verified")]

        # 按联赛分组
        by_league = {}
        for p in today_preds:
            league = p.get("league", "其他")
            if league not in by_league:
                by_league[league] = []
            by_league[league].append(p)

        summary_lines = []
        star_symbols = {1: "☆", 2: "★☆", 3: "★★", 4: "★★★", 5: "★★★★"}

        if today_preds:
            summary_lines.append(f"📊 今日足球预测 ({today_str})")
            summary_lines.append(f"共 {len(today_preds)} 场未开赛预测\n")

            for league, preds in by_league.items():
                summary_lines.append(f"【{league}】")
                for p in preds:
                    stars_str = star_symbols.get(p.get("stars", 1), "☆")
                    skip_tag = " ⚠️不建议" if p.get("skip") else ""
                    odds_tag = "📈" if p.get("hasOdds") else "📉"
                    kelly_tag = ""
                    ks = p.get("kellyScenario")
                    if ks:
                        kelly_tag = f" [凯利{ks}]"
                    # "唯独低于返还率"信号标签
                    unique_dir = p.get("kellyUniqueDirection")
                    unique_signal = p.get("kellyUniqueSignal")
                    unique_tag = ""
                    if unique_dir and unique_signal:
                        dir_label = {"H": "主胜", "D": "平局", "A": "客胜"}.get(unique_dir, unique_dir)
                        unique_tag = f" [唯独{dir_label}]"
                    # 反向信号标签
                    reverse_dir = p.get("kellyReverseDirection")
                    reverse_signal = p.get("kellyReverseSignal")
                    reverse_tag = ""
                    if reverse_dir and reverse_signal:
                        rev_dir_label = {"H": "H", "D": "D", "A": "A"}.get(reverse_dir, reverse_dir)
                        reverse_tag = f" [反向排除{rev_dir_label}]"
                    conf = p.get("confidence", 0)
                    pred_text = p.get("prediction", "")
                    pred_type = "单选" if p.get("type") == "single" else "双选"

                    line = (
                        f"  {p.get('home', '')} vs {p.get('away', '')}\n"
                        f"    {pred_type} {pred_text} | 置信度{conf}% | {stars_str}{kelly_tag}{unique_tag}{reverse_tag}{skip_tag}\n"
                        f"    {odds_tag} {p.get('reason', '')}"
                    )
                    summary_lines.append(line)
                summary_lines.append("")
        else:
            summary_lines.append(f"📊 今日 ({today_str}) 暂无新的预测")

        summary = "\n".join(summary_lines)
        print("\n" + summary)

        # ===== 11. 统计信息（仅竞彩/北单联赛纳入命中率） =====
        active_verified = [p for p in verified_preds if p.get("leagueCode") in ACTIVE_LEAGUE_CODES]
        verified_total = len(active_verified)
        verified_hits = sum(1 for p in active_verified if p.get("hit"))
        hit_rate = round(verified_hits / verified_total * 100) if verified_total > 0 else 0

        stats_info = (
            f"历史验证: {verified_total} 场 | 命中 {verified_hits} 场 | 命中率 {hit_rate}%\n"
            f"本次新增: {new_count} | 更新: {update_count} | 保留: {keep_count}"
        )
        print(stats_info)

        # ===== 12. 提交结果 =====
        actual_mode = result_mode if result_mode != "auto" else "display_only"

        # 构建用户消息
        if today_preds:
            msg_parts = [f"[主人](at://owner) 📊 今日足球预测 ({today_str})"]
            msg_parts.append(f"共 {len(today_preds)} 场预测")

            # 只展示前10场的关键信息
            shown = 0
            for p in today_preds[:10]:
                stars_str = star_symbols.get(p.get("stars", 1), "☆")
                skip_tag = " ⚠️" if p.get("skip") else ""
                msg_parts.append(
                    f"• {p['home']} vs {p['away']}: {p['prediction']} "
                    f"({p['confidence']}% {stars_str}{skip_tag})"
                )
            if len(today_preds) > 10:
                msg_parts.append(f"...还有 {len(today_preds) - 10} 场")

            # 推荐重点
            recommended = [p for p in today_preds if not p.get("skip") and p.get("stars", 0) >= 3]
            if recommended:
                msg_parts.append(f"\n🎯 重点推荐 ({len(recommended)} 场):")
                for p in recommended[:5]:
                    stars_str = star_symbols.get(p.get("stars", 1), "☆")
                    msg_parts.append(f"  ★ {p['home']} vs {p['away']}: {p['prediction']} ({p['confidence']}% {stars_str})")

            msg_parts.append(f"\n历史命中率: {hit_rate}% | GitHub更新: {'✅' if push_success else '❌'}")
            message = "\n".join(msg_parts)
        else:
            message = f"[主人](at://owner) 今日 ({today_str}) 暂无新的足球预测"

        await sdk.submit_result(
            result_mode=actual_mode,
            status="success",
            message=message,
            data={
                "date": today_str,
                "new_predictions": new_count,
                "updated_predictions": update_count,
                "total_upcoming": len(today_preds),
                "github_push": push_success,
                "verified_total": verified_total,
                "verified_hits": verified_hits,
                "hit_rate": hit_rate,
            },
        )

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        await sdk.submit_result(
            result_mode="notify",
            status="error",
            message=f"足球预测脚本执行失败: {e}",
            data={"error_type": type(e).__name__},
        )


asyncio.run(main())
