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
        # 让球赔率：优先 odds_minus1，其次 odds_-1，再次 odds_+1
        handicap_odds = odds.get("odds_minus1") or odds.get("odds_-1") or odds.get("odds_+1")
        source = odds.get("source", "竞彩")
    elif "w" in odds:
        # 简单格式
        w = odds.get("w", 0)
        d = odds.get("d", 0)
        l = odds.get("l", 0)
        source = odds.get("source", "足彩网")
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


# ===== 凯利七场景检测引擎 v5 =====
# 核心庄家：Bet365 + 韦德（betvictor）
# The Odds API key -> 内部标识
_KEY_BOOKMAKERS = {
    "bet365": "bet365",
    "betvictor": "betvictor",  # 韦德
    "ladbrokes_uk": "ladbrokes",
    "williamhill": "williamhill",
    "coral": "coral",
    "betway": "betway",
    "pinnacle": "pinnacle",
}

# 七场景引擎参数
_K_TOL = 0.005          # Kelly判断容差
_K_DIRS = ['h', 'd', 'a']
_K_DN = {'h': '主胜', 'd': '平局', 'a': '客胜'}
_K_DK = {'h': 'hf', 'd': 'df', 'a': 'af'}
_DIR_EN_TO_CN = {'h': '胜', 'd': '平', 'a': '负'}
_DIR_CN_TO_EN = {'胜': 'h', '平': 'd', '负': 'a'}
_DIR_CN_TO_HD = {'h': '主胜', 'd': '平局', 'a': '客胜'}

# 500com公司名称 → 核心庄家key映射
_500COM_CORE_COMPANIES = {
    "Bet365": "bet365",
    "韦德": "weide",
}



# ===== 七场景引擎辅助函数 =====

def _k_judge_kelly(kelly_val: float, payout: float) -> str:
    """Kelly判断：favor/ok/bad"""
    diff = payout - kelly_val
    if diff > _K_TOL:
        return 'favor'
    if diff >= -_K_TOL:
        return 'ok'
    return 'bad'


def _k_favored(company: dict) -> list:
    """获取庄家看好的方向列表"""
    return [d for d in _K_DIRS if _k_judge_kelly(company[f'kelly_{d}'], company['payout']) == 'favor']


def _k_bad_dirs(company: dict) -> list:
    """获取庄家不看好的方向列表"""
    return [d for d in _K_DIRS if _k_judge_kelly(company[f'kelly_{d}'], company['payout']) == 'bad']


def _k_is_safe(c365: dict, cw: dict, d: str) -> bool:
    """判断方向d是否安全（两家都不bad）"""
    return (_k_judge_kelly(c365[f'kelly_{d}'], c365['payout']) != 'bad' and
            _k_judge_kelly(cw[f'kelly_{d}'], cw['payout']) != 'bad')


def _k_lowest(company: dict) -> dict:
    """获取Kelly最低的方向"""
    min_dir = 'h'
    min_val = company['kelly_h']
    for d in ['d', 'a']:
        v = company[f'kelly_{d}']
        if v < min_val:
            min_dir = d
            min_val = v
    return {'dir': min_dir, 'val': min_val}


def _k_dispersion(c365: dict, cw: dict) -> dict:
    """计算两家Kelly离散度"""
    ds = []
    for d in _K_DIRS:
        ds.append({'dir': d, 'v': abs(c365[f'kelly_{d}'] - cw[f'kelly_{d}'])})
    ds.sort(key=lambda x: x['v'])
    avg = sum(x['v'] for x in ds) / 3.0
    return {'minDir': ds[0]['dir'], 'min': ds[0]['v'], 'avg': avg}


def _k_norm_adj(base: dict, adj: dict) -> dict:
    """归一化调整后的概率"""
    hf = max(0.01, base.get('hf', 0.33) + adj.get('hf', 0))
    df = max(0.01, base.get('df', 0.33) + adj.get('df', 0))
    af = max(0.01, base.get('af', 0.33) + adj.get('af', 0))
    t = hf + df + af
    return {'hf': hf / t, 'df': df / t, 'af': af / t}


def calc_kelly_scenario(kelly_companies: dict, base_probs: dict = None, odds_conf: float = None) -> dict:
    """
    凯利七场景检测引擎 v5（替换旧版ABCD四场景）

    核心庄家：Bet365 + 韦德
    Kelly判断标准：
      Kelly < payout - 0.005 → favor（庄家看好/保护该方向）
      Kelly > payout + 0.005 → bad（庄家不看好/不保护该方向）
      其他 → ok

    kelly_companies: {
        "bet365": {"kelly_h": float, "kelly_d": float, "kelly_a": float, "payout": float},
        "weide":  {"kelly_h": float, "kelly_d": float, "kelly_a": float, "payout": float},
    }
    base_probs: {"hf": float, "df": float, "af": float} 基础概率（来自赔率隐含或Elo）
    odds_conf: float 赔率置信度（用于场景六的条件分支）

    Returns: 包含 scenarios, label, adjustments, confidence_mod, skip, pick, cover, finalProbs 等字段
    """
    _empty = {
        'scenarios': [], 'label': '', 'adjustments': {'hf': 0, 'df': 0, 'af': 0},
        'confidence_mod': 0, 'skip': False, 'skipReason': '',
        'pick': None, 'cover': None, 'finalProbs': None,
        'bet365_kelly': None, 'weide_kelly': None,
        'bet365_payout': None, 'weide_payout': None,
        'dispersion': 0, 'scenario': None, 'signal': None,
    }

    c365 = kelly_companies.get('bet365')
    cw = kelly_companies.get('weide')

    if not c365 or not cw:
        return dict(_empty)

    if base_probs is None:
        base_probs = {'hf': 0.4, 'df': 0.27, 'af': 0.33}

    r = {
        'scenarios': [],
        'adjustments': {'hf': 0, 'df': 0, 'af': 0},
        'label': '', 'confidence_mod': 0,
        'skip': False, 'skipReason': '',
        'pick': None, 'cover': None, 'finalProbs': None,
        'bet365_kelly': {d: round(c365[f'kelly_{d}'], 4) for d in _K_DIRS},
        'weide_kelly': {d: round(cw[f'kelly_{d}'], 4) for d in _K_DIRS},
        'bet365_payout': round(c365.get('payout', 0), 4),
        'weide_payout': round(cw.get('payout', 0), 4),
        'dispersion': 0, 'scenario': None, 'signal': None,
    }

    f365 = _k_favored(c365)
    fW = _k_favored(cw)
    b365 = _k_bad_dirs(c365)
    bW = _k_bad_dirs(cw)
    l365 = _k_lowest(c365)
    lW = _k_lowest(cw)
    disp = _k_dispersion(c365, cw)
    safe = [d for d in _K_DIRS if _k_is_safe(c365, cw, d)]
    dropped = [d for d in _K_DIRS if not _k_is_safe(c365, cw, d)]

    r['dispersion'] = round(disp['avg'], 4)

    # ===== 场景七：离散度过高 → skip =====
    if disp['avg'] > 0.10:
        r['scenarios'].append('7_skip')
        r['skip'] = True
        r['skipReason'] = '凯利离散度>0.10'
        r['label'] = '场景七-离散度过高,建议放弃'
        r['scenario'] = '7'
        r['signal'] = r['label']
        return r

    # ===== 场景零：共同看好 =====
    common_favor = [d for d in f365 if d in fW]
    if common_favor:
        for d in common_favor:
            r['scenarios'].append('0')
            r['adjustments'][_K_DK[d]] += 0.15
            r['pick'] = d
            r['label'] = f'共同看好{_K_DN[d]}'
        if len(common_favor) == 1:
            main_dir = common_favor[0]
            if main_dir != 'd':
                draw_ok = _k_is_safe(c365, cw, 'd')
                draw_favored_by_one = ('d' in f365 or 'd' in fW)
                if draw_ok or draw_favored_by_one:
                    r['cover'] = 'd'
                    r['adjustments']['df'] += 0.05
                    r['label'] += '，防平'
        r['scenario'] = '0'
        r['signal'] = r['label']
        r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
        return r

    # ===== 场景一（提前检测）：两家同时不看好同一方向 =====
    common_bad = [d for d in b365 if d in bW]
    if common_bad:
        remain_dirs = [d for d in _K_DIRS if d not in common_bad]
        remain_favor_365 = [d for d in f365 if d in remain_dirs]
        remain_favor_w = [d for d in fW if d in remain_dirs]
        remain_common_favor = [d for d in remain_favor_365 if d in remain_favor_w]

        if len(remain_common_favor) == 1:
            # 排除共同bad后，剩余方向中有唯一共同看好
            r['scenarios'].append('1')
            r['pick'] = remain_common_favor[0]
            r['adjustments'][_K_DK[remain_common_favor[0]]] += 0.15
            bad_label = ''.join(_K_DN[d] for d in common_bad)
            r['label'] = f'场景一-两家不看好{bad_label}，看好{_K_DN[remain_common_favor[0]]}'
            # 防覆盖：另一个剩余方向如果有一家看好，加cover
            other_remain = [d for d in remain_dirs if d != remain_common_favor[0]]
            if len(other_remain) == 1:
                o_dir = other_remain[0]
                if o_dir in f365 or o_dir in fW:
                    r['cover'] = o_dir
                    r['adjustments'][_K_DK[o_dir]] += 0.05
                    r['label'] += f'，防{_K_DN[o_dir]}'
            r['scenario'] = '1'
            r['signal'] = r['label']
            r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
            return r

        elif remain_favor_365 and remain_favor_w:
            # 排除commonBad后仍有分歧（各看好不同方向）
            r['scenarios'].append('1+5')
            for d in remain_dirs:
                if d in remain_favor_365 or d in remain_favor_w:
                    r['adjustments'][_K_DK[d]] += 0.05
            r['adjustments']['df'] += 0.03
            r['confidence_mod'] -= 10
            bad_label = ''.join(_K_DN[d] for d in common_bad)
            remain_label = '/'.join(_K_DN[d] for d in remain_dirs)
            r['label'] = f'场景一-两家不看好{bad_label}({remain_label}仍有分歧)'
            r['scenario'] = '1'
            r['signal'] = r['label']
            r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
            return r

        # commonBad但没有明确剩余共同看好方向
        if l365['dir'] == 'd' and lW['dir'] == 'd':
            r['scenarios'].append('1D')
            r['adjustments']['df'] += 0.15
            r['label'] = '场景一D-两家平Kelly都最低'
            r['scenario'] = '1'
        elif l365['dir'] == 'd' or lW['dir'] == 'd':
            r['scenarios'].append('1C')
            r['adjustments']['df'] += 0.08
            r['label'] = '场景一C-一家平Kelly最低'
            r['scenario'] = '1'
        else:
            r['scenarios'].append('1')
            r['label'] = f'场景一-两家不看好{"".join(_K_DN[d] for d in common_bad)}'
            r['scenario'] = '1'
        r['signal'] = r['label']
        r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
        return r

    # ===== 场景三：去平局（仅当平局被dropped且主客都没被drop时） =====
    if 'd' in dropped and 'h' not in dropped and 'a' not in dropped:
        r['scenarios'].append('3')
        r['adjustments']['df'] = -(base_probs.get('df', 0.27) * 0.7)
        r['label'] = '场景三-去平局'
        r['scenario'] = '3'
        r['signal'] = r['label']
        r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
        return r

    # ===== 场景五：信号矛盾（无共同bad时触发） =====
    o365 = [d for d in f365 if d not in fW]
    oW = [d for d in fW if d not in f365]
    if len(o365) >= 1 and len(oW) >= 1:
        r['scenarios'].append('5')
        for d in safe:
            r['adjustments'][_K_DK[d]] += 0.05
        r['adjustments']['df'] += 0.03
        r['confidence_mod'] -= 10
        dropped_label = ''
        if 0 < len(dropped) < 3:
            dropped_label = '(' + ','.join(_K_DN[d] for d in dropped) + '不看好)'
        r['label'] = f'场景五-信号矛盾{dropped_label}'
        r['scenario'] = '5'
        r['signal'] = r['label']
        r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
        return r

    # ===== 场景二：各不看好不同方向 =====
    if b365 and bW:
        dA = [d for d in b365 if d not in bW]
        dB = [d for d in bW if d not in b365]
        if dA and dB:
            r['scenarios'].append('2')
            r['adjustments']['df'] += 0.12
            if not r['label']:
                r['label'] = '场景二-各不看好不同队-平局高发'
            r['scenario'] = '2'
            r['signal'] = r['label']
            r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
            return r

    # ===== 场景六：两家都不看好某队+平Kelly最低 =====
    for d in ['h', 'a']:
        if d not in b365 or d not in bW:
            continue
        if l365['dir'] != 'd' and lW['dir'] != 'd':
            continue
        r['scenarios'].append('6')
        if odds_conf and odds_conf > 0.70:
            r['adjustments'][_K_DK[d]] += 0.10
            r['adjustments']['df'] += 0.05
            r['label'] = f'场景六-置信度高→{_K_DN[d]}+平'
        else:
            oth = 'a' if d == 'h' else 'h'
            r['adjustments'][_K_DK[oth]] += 0.10
            r['adjustments']['df'] += 0.05
            r['label'] = f'场景六-置信度不高→{_K_DN[oth]}+平'
        r['scenario'] = '6'
        r['signal'] = r['label']
        r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
        return r

    # 兜底：如果有场景标签但没返回
    if r['scenarios']:
        r['signal'] = r['label']
        r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])

    return r


def _extract_kelly_companies_500com(companies: dict) -> dict:
    """
    从500com公司数据中提取Bet365和韦德的Kelly数据
    输入: {"Bet365": [{"kelly_h": x, "kelly_d": y, "kelly_a": z, "payout": p, ...}], "韦德": [...]}
    输出: {"bet365": {"kelly_h": x, ...}, "weide": {"kelly_h": x, ...}}
    如果没有Kelly字段，从odds计算
    """
    result = {}
    for company_name, core_key in _500COM_CORE_COMPANIES.items():
        records = companies.get(company_name)
        if not records:
            continue
        rec = records[0] if isinstance(records, list) else records
        entry = {}
        # 优先使用预计算的Kelly值
        if 'kelly_h' in rec and 'payout' in rec:
            entry = {
                'kelly_h': float(rec['kelly_h']),
                'kelly_d': float(rec['kelly_d']),
                'kelly_a': float(rec['kelly_a']),
                'payout': float(rec['payout']),
            }
        elif 'odds_h' in rec:
            # 从赔率计算Kelly（需要市场平均概率，此处简化处理）
            odds_h = float(rec.get('odds_h', 0))
            odds_d = float(rec.get('odds_d', 0))
            odds_a = float(rec.get('odds_a', 0))
            if odds_h > 1 and odds_d > 1 and odds_a > 1:
                payout = 1.0 / (1.0/odds_h + 1.0/odds_d + 1.0/odds_a)
                entry = {
                    'kelly_h': odds_h * payout,  # 简化：无市场平均时用自身返还率
                    'kelly_d': odds_d * payout,
                    'kelly_a': odds_a * payout,
                    'payout': round(payout, 4),
                }
        if entry:
            result[core_key] = entry
    return result


def _compute_kelly_from_odds_api(bookmaker_odds: dict) -> dict:
    """
    从Odds API原始赔率数据计算Bet365和韦德(betvictor)的Kelly值
    输入: {"bet365": {"home": x, "draw": y, "away": z}, "betvictor": {...}, ...}
    输出: {"bet365": {"kelly_h": x, ...}, "weide": {"kelly_h": x, ...}}
    """
    # Step 1: 计算市场平均隐含概率（从所有可用公司）
    all_probs = {'h': [], 'd': [], 'a': []}
    for bk_key, odds in bookmaker_odds.items():
        h_odds = odds.get('home', 0)
        d_odds = odds.get('draw', 0)
        a_odds = odds.get('away', 0)
        if h_odds <= 1 or d_odds <= 1 or a_odds <= 1:
            continue
        total = 1/h_odds + 1/d_odds + 1/a_odds
        R = 1.0 / total
        all_probs['h'].append(R / h_odds)
        all_probs['d'].append(R / d_odds)
        all_probs['a'].append(R / a_odds)

    if not all_probs['h']:
        return {}

    market_avg = {
        'h': sum(all_probs['h']) / len(all_probs['h']),
        'd': sum(all_probs['d']) / len(all_probs['d']),
        'a': sum(all_probs['a']) / len(all_probs['a']),
    }

    # Step 2: 为bet365和betvictor计算Kelly
    result = {}
    api_to_core = {'bet365': 'bet365', 'betvictor': 'weide'}
    for api_key, core_key in api_to_core.items():
        odds = bookmaker_odds.get(api_key)
        if not odds:
            continue
        h_odds = odds.get('home', 0)
        d_odds = odds.get('draw', 0)
        a_odds = odds.get('away', 0)
        if h_odds <= 1 or d_odds <= 1 or a_odds <= 1:
            continue
        payout = 1.0 / (1.0/h_odds + 1.0/d_odds + 1.0/a_odds)
        result[core_key] = {
            'kelly_h': round(h_odds * market_avg['h'], 4),
            'kelly_d': round(d_odds * market_avg['d'], 4),
            'kelly_a': round(a_odds * market_avg['a'], 4),
            'payout': round(payout, 4),
        }
    return result


def predict_match(match: dict, teams: dict, kelly_data: dict = None) -> dict:
    """
    对单场比赛生成预测（融合凯利七场景引擎）
    kelly_data: 来自 calc_kelly_scenario() 的七场景分析数据
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

    # 确定基础概率
    if has_odds:
        # 凯利策略：100% 基于赔率隐含概率
        probs = calc_kelly_probs(w, d, l)
    else:
        # Elo 降级
        probs = elo_probs

    # ===== 场景调整后的概率（七场景引擎） =====
    base_probs_hd = {'hf': probs['胜'], 'df': probs['平'], 'af': probs['负']}
    kelly_adjusted = False
    scenario_final_probs = None

    if kelly_data and kelly_data.get('finalProbs'):
        fp = kelly_data['finalProbs']
        scenario_final_probs = {
            '胜': fp.get('hf', probs['胜']),
            '平': fp.get('df', probs['平']),
            '负': fp.get('af', probs['负']),
        }
        kelly_adjusted = True

    # 使用场景调整后的概率进行排序（如果有），否则使用基础概率
    working_probs = scenario_final_probs if kelly_adjusted else probs

    # 按概率排序
    sorted_probs = sorted(working_probs.items(), key=lambda x: -x[1])
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

    # ===== 场景 confidence_mod 叠加 =====
    if kelly_data and kelly_data.get('confidence_mod'):
        ct = max(0, min(100, ct + kelly_data['confidence_mod']))

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

    # 再次叠加场景 confidence_mod
    if kelly_data and kelly_data.get('confidence_mod'):
        ct = max(0, min(100, ct + kelly_data['confidence_mod']))

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
    if ct < 35:
        if not skip:
            skip = True
            skip_reason = f"置信度过低({ct}%)"

    # 场景七 skip（凯利离散度过高）
    if kelly_data and kelly_data.get('skip'):
        if not skip:
            skip = True
            skip_reason = kelly_data.get('skipReason', '凯利场景建议放弃')

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

        if has_odds:
            odds_map = {"胜": w, "平": d, "负": l}
            remaining = [(r, odds_map.get(r, 1)) for r, p in sorted_probs[1:]]
            remaining.sort(key=lambda x: -x[1])
            upset = remaining[0][0]
        else:
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

    # ===== 凯利场景 pick/cover 影响单双选 =====
    kelly_scenario = None
    kelly_signal = None
    kelly_pick = None
    kelly_cover = None
    kelly_dispersion = None

    if kelly_data and kelly_data.get('scenario') and not skip:
        kelly_scenario = kelly_data['scenario']
        kelly_signal = kelly_data.get('signal')
        kelly_pick = kelly_data.get('pick')
        kelly_cover = kelly_data.get('cover')
        kelly_dispersion = kelly_data.get('dispersion')

        # 场景给出 pick+cover → 覆盖单双选
        if kelly_pick and kelly_cover:
            pick_cn = _DIR_EN_TO_CN.get(kelly_pick, kelly_pick)
            cover_cn = _DIR_EN_TO_CN.get(kelly_cover, kelly_cover)
            pred_type = 'double'
            prediction = f'{pick_cn}+{cover_cn}'
            double_pick = [pick_cn, cover_cn]
            reason = f'凯利场景{kelly_scenario}: {_K_DN.get(kelly_pick,"")}/{_K_DN.get(kelly_cover,"")} · {kelly_signal}'
            if has_odds:
                reason += f' · {odds_source}赔率'
        elif kelly_pick and not kelly_cover:
            pick_cn = _DIR_EN_TO_CN.get(kelly_pick, kelly_pick)
            # 场景给出单选方向，如果概率优势足够，强化为单选
            if pred_type == 'double' and max_prob >= 0.45:
                pred_type = 'single'
                prediction = pick_cn
                double_pick = None
                reason = f'凯利场景{kelly_scenario}: 看好{_DIR_CN_TO_HD.get(kelly_pick,"")} · {kelly_signal}'
                if has_odds:
                    reason += f' · {odds_source}赔率'

    # 构建场景相关reason后缀
    if kelly_scenario and kelly_signal and '凯利场景' not in reason:
        reason += f' · [凯利{kelly_scenario}]{kelly_signal}'

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
        "kellyPick": kelly_pick,
        "kellyCover": kelly_cover,
        "kellyDispersion": kelly_dispersion,
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

                # 至少需要2家核心公司赔率才有场景分析价值
                # 核心：bet365 + betvictor(韦德)，备选 pinnacle+betvictor
                key_count = len(bookmakers)
                has_b365_bv = "bet365" in bookmakers and "betvictor" in bookmakers
                has_pin_bv = "pinnacle" in bookmakers and "betvictor" in bookmakers
                has_b365_pin = "bet365" in bookmakers and "pinnacle" in bookmakers
                if key_count >= 2 and (has_b365_bv or has_pin_bv or has_b365_pin):
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


# ===== 竞彩网赔率备选数据源 =====

def _parse_sporttery_content(content: str) -> dict:
    """
    解析竞彩网(sporttery.cn)赔率页面内容，提取胜平负赔率
    
    页面内容可能是:
    1. JSON 格式: {"data":{"content":"...表格内容..."}}
    2. 纯文本/HTML: 包含 markdown 表格
    
    返回: { (home_cn_norm, away_cn_norm): {"w": float, "d": float, "l": float,
                                             "hcp_w": float, "hcp_d": float, "hcp_l": float,
                                             "handicap": str, "home_cn": str, "away_cn": str} }
    """
    import re as _re
    
    if not content:
        return {}
    
    # Step 1: 尝试解析为 JSON（sporttery.cn 可能返回 JSON 响应）
    actual_content = content
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            # JSON API 格式: {"data": {"content": "..."}}
            actual_content = data.get("data", {}).get("content", "")
            if not actual_content:
                # 也可能是直接的数据格式: {"data": {"match_id": {"h_cn": ..., ...}}}
                raw_data = data.get("data", {})
                if isinstance(raw_data, dict) and not isinstance(
                    next(iter(raw_data.values()), None), str
                ):
                    # 这是 JSON API 格式，直接解析
                    return _parse_sporttery_api_data(raw_data)
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    
    if not actual_content:
        return {}
    
    # Step 2: 清理 HTML/Markdown 标记
    # 注意：竞彩网页面是单行 markdown 表格，<br> 在单元格内，不能转为换行（否则拆行）
    text = _re.sub(r'<br\s*/?>', ' ', actual_content)
    # 移除 markdown 图片: ![alt](url)
    text = _re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    # 清理竞彩网嵌套括号链接格式:
    #   [[联赛+排名]队名](url) → 队名   如 [[芬超11]雅罗](url) → 雅罗
    #   [队名[联赛+排名]](url) → 队名   如 [国际图尔[芬超2]](url) → 国际图尔
    # 先去掉 URL 部分: ](url) → ]
    text = _re.sub(r'\]\([^)]*\)', ']', text)
    # 处理 [[x]y] → y (嵌套左括号: [[联赛+排名]队名])
    text = _re.sub(r'\[\[[^\]]*\]([^\[\]]*)\]', r'\1', text)
    # 处理 [x[y]] → x (嵌套右括号: [队名[联赛+排名]])
    text = _re.sub(r'\[([^\[\]]*)\[[^\]]*\]\]', r'\1', text)
    # 移除剩余的简单 [xxx] 标记
    text = _re.sub(r'\[[^\]]*\]', '', text)
    
    # Step 3: 按表格行解析赔率
    # 竞彩网页面是 markdown 表格，每行用 | 分隔，格式：
    # | 编号 | 联赛 | 时间 | 主队VS客队 | 让球 | 标准赔率\n让球赔率 | 同奖 | 支持率 | ...
    results = {}
    
    # 按行分割表格（每行以 | 开头）
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if 'VS' not in line:
            continue
        # 跳过表头行
        if '主队' in line and '客队' in line:
            continue
        
        # 用 | 分割列
        cols = [c.strip() for c in line.split('|')]
        # 过滤空列
        cols = [c for c in cols if c]
        
        # 至少需要 6 列（编号、联赛、时间、队名VS、让球、赔率）
        if len(cols) < 6:
            continue
        
        # 查找包含 VS 的列
        vs_col_idx = -1
        for i, c in enumerate(cols):
            if 'VS' in c:
                vs_col_idx = i
                break
        
        if vs_col_idx < 0:
            continue
        
        # 提取队名
        vs_text = cols[vs_col_idx]
        vs_parts = vs_text.split('VS')
        if len(vs_parts) != 2:
            continue
        
        home_cn = vs_parts[0].strip()
        away_cn = vs_parts[1].strip()
        
        # 清理队名中的非队名字符（数字、百分号等）
        home_cn = _re.sub(r'^[\d\s%]+', '', home_cn).strip()
        away_cn = _re.sub(r'[\d\s%]+$', '', away_cn).strip()
        
        if not home_cn or not away_cn:
            continue
        
        # 在 VS 列之后的列中查找赔率（标准赔率+让球赔率共6个数字）
        # 赔率列可能在 vs_col_idx+1 或 vs_col_idx+2 位置
        odds_text = ""
        for i in range(vs_col_idx + 1, min(len(cols), vs_col_idx + 4)):
            odds_text += " " + cols[i]
        
        all_odds = _re.findall(r'\d+\.\d{2}', odds_text)
        if len(all_odds) < 6:
            # 尝试从整行提取（某些格式赔率不在独立列中）
            all_odds = _re.findall(r'\d+\.\d{2}', line)
            # 找到 VS 之后的赔率
            vs_pos_in_line = line.find('VS')
            if vs_pos_in_line >= 0:
                after_vs_text = line[vs_pos_in_line:]
                all_odds_after = _re.findall(r'\d+\.\d{2}', after_vs_text)
                if len(all_odds_after) >= 6:
                    all_odds = all_odds_after
        
        if len(all_odds) < 6:
            continue
        
        try:
            std_w = float(all_odds[0])
            std_d = float(all_odds[1])
            std_l = float(all_odds[2])
            hcp_w = float(all_odds[3])
            hcp_d = float(all_odds[4])
            hcp_l = float(all_odds[5])
        except (ValueError, IndexError):
            continue
        
        # 验证赔率有效性（标准赔率必须 > 1.0）
        if std_w <= 1.0 or std_d <= 1.0 or std_l <= 1.0:
            continue
        
        # 提取让球数（在 VS 列和赔率列之间）
        # 竞彩网格式: "0 +1" 或 "0 -2"，第一个0是默认让球，后面是实际让球
        handicap = ""
        for i in range(vs_col_idx + 1, min(len(cols), vs_col_idx + 3)):
            # 找所有 [+-]N 格式的让球数
            hcp_matches = _re.findall(r'([+-]\d+)', cols[i])
            if hcp_matches:
                handicap = hcp_matches[-1]  # 取最后一个（实际让球）
        
        # 存储结果
        key = (_normalize_name(home_cn), _normalize_name(away_cn))
        results[key] = {
            "w": std_w, "d": std_d, "l": std_l,
            "hcp_w": hcp_w, "hcp_d": hcp_d, "hcp_l": hcp_l,
            "handicap": handicap,
            "home_cn": home_cn,
            "away_cn": away_cn,
        }
    
    return results


def _parse_sporttery_api_data(raw_data: dict) -> dict:
    """
    解析 i.sporttery.cn JSON API 返回的赔率数据
    数据格式: {match_id: {"h_cn": "西班牙", "a_cn": "阿根廷", "had": {"h": "2.11", ...}, ...}}
    
    返回: 同 _parse_sporttery_content 格式
    """
    results = {}
    
    for match_id, match_data in raw_data.items():
        if not isinstance(match_data, dict):
            continue
        
        home_cn = match_data.get("h_cn", "").strip()
        away_cn = match_data.get("a_cn", "").strip()
        if not home_cn or not away_cn:
            continue
        
        # 胜平负赔率
        had = match_data.get("had", {})
        std_w = float(had.get("h", "0"))
        std_d = float(had.get("d", "0"))
        std_l = float(had.get("a", "0"))
        
        if std_w <= 1.0 or std_d <= 1.0 or std_l <= 1.0:
            continue
        
        # 让球胜平负赔率
        hhad = match_data.get("hhad", {})
        hcp_w = float(hhad.get("h", "0")) if hhad else 0
        hcp_d = float(hhad.get("d", "0")) if hhad else 0
        hcp_l = float(hhad.get("a", "0")) if hhad else 0
        
        handicap = had.get("hgd", hhad.get("hgd", "")) if isinstance(had, dict) else ""
        
        key = (_normalize_name(home_cn), _normalize_name(away_cn))
        results[key] = {
            "w": std_w, "d": std_d, "l": std_l,
            "hcp_w": hcp_w, "hcp_d": hcp_d, "hcp_l": hcp_l,
            "handicap": str(handicap),
            "home_cn": home_cn,
            "away_cn": away_cn,
        }
    
    return results


async def _fetch_sporttery_odds(sdk) -> dict:
    """
    从竞彩网(sporttery.cn)获取胜平负赔率作为备选数据源
    
    优先尝试 i.sporttery.cn JSON API（数据结构化），回退到 www.sporttery.cn 页面解析
    
    返回: { (home_cn_norm, away_cn_norm): odds_dict }
    """
    # 方法1: 尝试 i.sporttery.cn JSON API
    api_url = "https://i.sporttery.cn/odds_calculator/get_odds?i_format=json&poolcode[]=had&poolcode[]=hhad"
    try:
        fetch_result = await sdk.call_tool(
            "codeact_fetch_web",
            {"url": api_url},
            schema_version=TOOL_SCHEMA_VERSIONS["codeact_fetch_web"],
        )
        if fetch_result.get("is_success"):
            content = fetch_result.get("content", "")
            if content:
                # JSONP 响应格式: callback({...}); 去掉回调包装
                try:
                    # 尝试直接解析
                    data = json.loads(content)
                    raw_data = data.get("data", {})
                    if raw_data:
                        parsed = _parse_sporttery_api_data(raw_data)
                        if parsed:
                            print(f"[OK] 竞彩网 API 赔率: {len(parsed)} 场比赛")
                            return parsed
                except json.JSONDecodeError:
                    # 可能是 JSONP 格式，尝试去掉回调包装
                    try:
                        # JSONP: callback({...}) → 取 {...}
                        json_start = content.index('(')
                        json_end = content.rindex(')')
                        inner = content[json_start + 1:json_end]
                        data = json.loads(inner)
                        raw_data = data.get("data", {})
                        if raw_data:
                            parsed = _parse_sporttery_api_data(raw_data)
                            if parsed:
                                print(f"[OK] 竞彩网 API(JSONP) 赔率: {len(parsed)} 场比赛")
                                return parsed
                    except (ValueError, json.JSONDecodeError):
                        pass
    except Exception as e:
        print(f"[WARN] 竞彩网 API 获取异常: {e}")
    
    # 方法2: 解析 www.sporttery.cn 页面
    page_url = "https://www.sporttery.cn/jc/jsq/zqspf/"
    try:
        fetch_result = await sdk.call_tool(
            "codeact_fetch_web",
            {"url": page_url},
            schema_version=TOOL_SCHEMA_VERSIONS["codeact_fetch_web"],
        )
        if fetch_result.get("is_success"):
            content = fetch_result.get("content", "")
            if content:
                parsed = _parse_sporttery_content(content)
                if parsed:
                    print(f"[OK] 竞彩网页面赔率: {len(parsed)} 场比赛")
                    return parsed
                else:
                    print(f"[WARN] 竞彩网页面解析无结果 (内容长度: {len(content)})")
        else:
            print(f"[WARN] 竞彩网页面获取失败: {fetch_result.get('error', '')}")
    except Exception as e:
        print(f"[WARN] 竞彩网页面获取异常: {e}")
    
    print("[WARN] 竞彩网赔率获取失败，将使用 Elo 降级")
    return {}


def _match_sporttery_odds(home_cn: str, away_cn: str, sporttery_odds: dict) -> dict:
    """
    在竞彩网赔率数据中查找匹配的比赛赔率
    支持精确匹配和模糊匹配（子串包含）
    
    返回: odds_dict 或 None
    """
    if not sporttery_odds:
        return None
    
    # 竞彩网常用缩写/别名 → 预测中的标准名称 映射
    _NAME_ALIASES = {
        "埃夫斯堡": "埃尔夫斯堡",
        "哈尔姆斯": "哈尔姆斯塔德",
        "赫根": "哈根",
        "厄格里特": "厄尔格里特",
        "佐加顿斯": "尤尔加登",
        "坦山猫": "坦佩雷山猫",
        "国际图尔": "国际图尔库",
        "天狼星": "西里乌斯",
        "马尔默": "马尔默",
    }
    
    def _apply_aliases(name: str) -> list:
        """返回名称的所有可能变体（原名 + 别名映射）"""
        variants = [name]
        # 如果名称是别名键，添加映射值
        if name in _NAME_ALIASES:
            variants.append(_NAME_ALIASES[name])
        # 如果名称是别名值，添加映射键
        for k, v in _NAME_ALIASES.items():
            if v == name:
                variants.append(k)
        return variants
    
    # 方法1: 精确标准化名称匹配（含别名变体）
    home_variants = _apply_aliases(home_cn)
    away_variants = _apply_aliases(away_cn)
    
    for hv in home_variants:
        for av in away_variants:
            key = (_normalize_name(hv), _normalize_name(av))
            if key in sporttery_odds:
                return sporttery_odds[key]
            # 主客颠倒匹配
            key_rev = (_normalize_name(av), _normalize_name(hv))
            if key_rev in sporttery_odds:
                odds = sporttery_odds[key_rev]
                return {
                    "w": odds["l"], "d": odds["d"], "l": odds["w"],
                    "hcp_w": odds.get("hcp_l", 0), "hcp_d": odds.get("hcp_d", 0), "hcp_l": odds.get("hcp_w", 0),
                    "handicap": odds.get("handicap", ""),
                    "home_cn": odds.get("away_cn", away_cn),
                    "away_cn": odds.get("home_cn", home_cn),
                }
    
    # 方法2: 模糊匹配（子串包含，含别名变体）
    for hv in home_variants:
        for av in away_variants:
            hv_norm = _normalize_name(hv)
            av_norm = _normalize_name(av)
            for (s_home, s_away), odds in sporttery_odds.items():
                # 检查是否一方包含另一方
                home_match = (hv_norm in s_home or s_home in hv_norm)
                away_match = (av_norm in s_away or s_away in av_norm)
                if home_match and away_match:
                    return odds
                # 也尝试交叉匹配
                home_match_x = (hv_norm in s_away or s_away in hv_norm)
                away_match_x = (av_norm in s_home or s_home in av_norm)
                if home_match_x and away_match_x:
                    return {
                        "w": odds["l"], "d": odds["d"], "l": odds["w"],
                        "hcp_w": odds.get("hcp_l", 0), "hcp_d": odds.get("hcp_d", 0), "hcp_l": odds.get("hcp_w", 0),
                        "handicap": odds.get("handicap", ""),
                        "home_cn": odds.get("away_cn", away_cn),
                        "away_cn": odds.get("home_cn", home_cn),
                    }
    
    return None


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



# 500.com公司名称 → Odds API bookmaker key 映射
_500COM_TO_API_KEY = {
    "Pinnacle": "pinnacle",
    "韦德": "betvictor",
    "Ladbrokes": "ladbrokes",
    "Bet365": "bet365",
    "威廉希尔": "williamhill",
    "Interwetten": "interwetten",
    "Interwetten2": "interwetten2",
    "澳门": "macau",
    "皇冠": "crown",
    "易胜博": "easybets",
    "Bwin": "bwin",
    "Coral": "coral",
    "必发": "betfair",
    "Unibet": "unibet",
    "Unibet2": "unibet2",
    "SkyBet": "skybet",
    "Dafabet": "dafabet",
    "Mansion88": "mansion88",
    "香港马会": "hkjc",
    "立博": "ladbrokes_cn",
}

def _load_kelly_500com_data() -> dict:
    """加载500.com凯利数据（由scrape_500com_kelly_full.py生成）"""
    today = datetime.now().strftime("%Y%m%d")
    # 也检查明天的数据（跨天比赛）
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)  # football-predictions/

    for date_str in [today, tomorrow]:
        path = os.path.join(base_dir, "data", "500com_daily", date_str, "kelly_data_full.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"[500COM] 加载{date_str}凯利数据: {data.get('total_matches',0)}场比赛, {data.get('total_companies',0)}条公司记录")
            return data
    print("[500COM] 未找到今日凯利数据")
    return {}

def _load_kelly_zgzcw_data() -> dict:
    """加载中国足彩网凯利数据（当前不可用，zgzcw.com有反爬限制）"""
    return {}

def _convert_500com_to_bookmaker_odds(companies: dict) -> dict:
    """将500.com公司数据转换为calc_kelly_scenario期望的格式
    输入: {"威廉希尔": [{"odds_h": x, "odds_d": y, "odds_a": z, ...}], ...}
    输出: {"williamhill": {"home": x, "draw": y, "away": z}, ...}
    """
    result = {}
    for company_name, records in companies.items():
        api_key = _500COM_TO_API_KEY.get(company_name)
        if not api_key:
            continue
        rec = records[0] if isinstance(records, list) else records
        result[api_key] = {
            "home": rec["odds_h"],
            "draw": rec["odds_d"],
            "away": rec["odds_a"],
        }
    return result

def _match_500com_match(home_cn: str, away_cn: str, league: str, kelly_500com: dict) -> dict:
    """在500com数据中模糊匹配比赛（通过中文名）"""
    if not kelly_500com:
        return None
    matches = kelly_500com.get("matches", [])
    if not matches:
        return None

    # 已知队名别名映射（500com中文名 → schedule中文名）
    _TEAM_ALIAS = {
        "巴西国际": "国际体育", "沙佩科": "沙佩科恩斯",
        "巴拉纳竞技": "帕拉纳竞技", "帕尔梅拉斯": "帕尔梅拉斯",
        "哈马坎": "哈马坎",
    }
    def _alias(name: str) -> str:
        return _TEAM_ALIAS.get(name, name)

    def _name_similarity(a: str, b: str) -> float:
        """综合名称相似度：别名 + 子串匹配 + 字符集重合度"""
        if not a or not b:
            return 0.0
        a2 = _alias(a)
        b2 = _alias(b)
        if a2 == b2:
            return 1.0
        # 子串匹配：一个包含另一个
        if a2 in b2 or b2 in a2:
            return max(len(a2), len(b2)) / min(len(a2), len(b2)) * 0.5 + 0.3
        # 字符集重合度
        set_a = set(a2)
        set_b = set(b2)
        common = len(set_a & set_b)
        total = len(set_a | set_b)
        return common / total if total > 0 else 0.0

    best_match = None
    best_score = 0

    for m500 in matches:
        h500 = m500.get("home", "")
        a500 = m500.get("away", "")
        # 主客正序匹配
        h_sim = _name_similarity(home_cn, h500)
        a_sim = _name_similarity(away_cn, a500)
        score_fwd = (h_sim + a_sim) / 2
        # 主客颠倒
        h_sim_rev = _name_similarity(home_cn, a500)
        a_sim_rev = _name_similarity(away_cn, h500)
        score_rev = (h_sim_rev + a_sim_rev) / 2
        score = max(score_fwd, score_rev)
        if score > best_score:
            best_score = score
            best_match = m500

    # 阈值：50%相似度
    if best_score >= 0.5 and best_match:
        print(f"[500COM] 匹配成功: {home_cn} vs {away_cn} → {best_match['home']} vs {best_match['away']} (相似度{best_score:.0%})")
        return best_match
    return None


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

        # ===== 2.5 补充 schedule.json 中缺失的联赛赛程（从 Odds API 获取） =====
        # ESPN API 可能不覆盖某些联赛（如 fin.1 芬超），导致 schedule.json 无该联赛数据
        # 此处从 The Odds API /scores/ 端点获取缺失联赛的赛程并注入
        schedule_leagues = set(m.get("league", "") for m in all_matches)
        missing_leagues = [lc for lc in ACTIVE_LEAGUE_CODES
                           if lc not in schedule_leagues and lc in _ODDS_API_LEAGUE_MAP]
        if missing_leagues:
            print(f"[INFO] schedule.json 缺失联赛: {missing_leagues}，尝试从 Odds API 补充...")
            # 芬超等小联赛球队中文映射
            _ODDS_TEAM_ZH = {
                # 芬超
                "HJK Helsinki": "赫尔辛基", "HJK": "赫尔辛基",
                "KuPS Kuopio": "古比斯", "KuPS": "古比斯",
                "FC Inter Turku": "国际图尔库", "FC Inter": "国际图尔库", "Inter Turku": "国际图尔库",
                "VPS Vaasa": "VPS瓦萨", "VPS": "VPS瓦萨",
                "AC Oulu": "奥卢",
                "IF Gnistan": "格尼斯坦", "Gnistan": "格尼斯坦",
                "TPS Turku": "TPS图尔库", "TPS": "TPS图尔库",
                "FC Lahti": "拉赫蒂", "Lahti": "拉赫蒂",
                "Ilves Tampere": "埃尔维斯", "Ilves": "埃尔维斯",
                "SJK Seinäjoki": "塞那乔其", "SJK": "塞那乔其",
                "Jaro": "雅罗", "FF Jaro": "雅罗",
                "IFK Mariehamn": "玛丽港", "Mariehamn": "玛丽港",
                # 奥超
                "SK Sturm Graz": "格拉茨风暴", "Sturm Graz": "格拉茨风暴",
                "Red Bull Salzburg": "萨尔茨堡", "RB Salzburg": "萨尔茨堡",
                "Rapid Wien": "维也纳快速", "Rapid Vienna": "维也纳快速",
                "Austria Wien": "维也纳奥地利", "Austria Vienna": "维也纳奥地利",
                "LASK": "林茨", "Wolfsberger AC": "沃尔夫斯贝格",
                "Hartberg": "哈特贝格", "TSV Hartberg": "哈特贝格",
                "WSG Tirol": "蒂罗尔", "Altach": "阿尔塔赫",
                "SCR Altach": "阿尔塔赫", "Blau-Weiß Linz": "蓝白林茨",
                "Austria Klagenfurt": "克拉根福",
            }
            # 联赛中文信息
            _LEAGUE_ZH = {
                "fin.1": ("芬超", "芬超", 3),
                "aut.1": ("奥甲", "奥甲", 3),
            }
            injected_count = 0
            for lc in missing_leagues:
                sport_key = _ODDS_API_LEAGUE_MAP.get(lc)
                if not sport_key:
                    continue
                url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/"
                params = {"apiKey": ODDS_API_KEY, "daysFrom": 3}
                try:
                    resp = requests.get(url, params=params, timeout=15)
                    if resp.status_code != 200:
                        print(f"[WARN] Odds API scores {lc}: HTTP {resp.status_code}")
                        continue
                    events = resp.json()
                    league_info = _LEAGUE_ZH.get(lc, (lc, lc, 3))
                    for evt in events:
                        if evt.get("completed"):
                            continue
                        home_en = evt.get("home_team", "")
                        away_en = evt.get("away_team", "")
                        raw_date = evt.get("commence_time", "")
                        # 转换为北京时间
                        try:
                            dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                            dt_beijing = dt.astimezone(timezone(timedelta(hours=8)))
                            beijing_date = dt_beijing.strftime("%Y-%m-%dT%H:%M:%S") + "+08:00"
                            weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
                            wd = weekdays[dt_beijing.weekday()]
                            status_str = f"{dt_beijing.month}/{dt_beijing.day} {wd} {dt_beijing.hour:02d}:{dt_beijing.minute:02d}"
                        except Exception:
                            beijing_date = raw_date
                            status_str = raw_date
                        # 中文名查找
                        home_cn = _ODDS_TEAM_ZH.get(home_en, home_en)
                        away_cn = _ODDS_TEAM_ZH.get(away_en, away_en)
                        match_entry = {
                            "id": f"oddsapi_{evt.get('id', '')}",
                            "home": home_cn,
                            "away": away_cn,
                            "homeEN": home_en,
                            "awayEN": away_en,
                            "date": beijing_date,
                            "league": lc,
                            "leagueName": league_info[0],
                            "leagueShort": league_info[1],
                            "status": status_str,
                            "statusClass": "scheduled",
                            "completed": False,
                            "homeScore": 0,
                            "awayScore": 0,
                            "weight": league_info[2],
                        }
                        all_matches.append(match_entry)
                        injected_count += 1
                        print(f"[INJECT] {lc} {home_cn} vs {away_cn} | {beijing_date}")
                except Exception as e:
                    print(f"[WARN] Odds API scores {lc} 异常: {e}")
                await asyncio.sleep(0.5)
            if injected_count:
                print(f"[OK] Odds API 补充赛程: {injected_count} 场比赛注入")

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
        yesterday_str = (today - timedelta(days=1)).strftime("%Y%m%d")
        tomorrow_str = (today + timedelta(days=1)).strftime("%Y%m%d")
        print(f"[INFO] 今日日期: {today_str}")

        upcoming = []
        skipped_leagues = set()
        # 只预测今天和明天的比赛，不过早预测更远日期
        allowed_predict_dates = {today_str, tomorrow_str}
        skipped_future = 0
        for m in all_matches:
            if m.get("statusClass") != "scheduled":
                continue
            if m.get("completed"):
                continue
            league_code = m.get("league", "")
            if league_code not in ACTIVE_LEAGUE_CODES:
                skipped_leagues.add(league_code)
                continue
            # 日期过滤：只保留今天和明天的比赛
            match_date_raw = m.get("date", "")
            if len(match_date_raw) >= 8:
                match_date_str = match_date_raw[:8].replace("-", "")
                if match_date_str not in allowed_predict_dates:
                    skipped_future += 1
                    continue
            upcoming.append(m)
        
        if skipped_future > 0:
            print(f"[INFO] 跳过远期比赛: {skipped_future} 场（只预测{today_str}~{tomorrow_str}）")

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
        
        # ===== 6.5.1 从500com_daily加载凯利数据（补充数据源） =====
        print("[INFO] 从500com_daily加载凯利数据...")
        kelly_500com_data = _load_kelly_500com_data()
        if kelly_500com_data:
            print(f"[OK] 500com凯利数据: {len(kelly_500com_data.get('matches', []))} 场比赛")
        
        # ===== 6.5.2 从zgzcw_kelly加载凯利数据（补充数据源） =====
        print("[INFO] 从zgzcw_kelly加载凯利数据...")
        kelly_zgzcw_data = _load_kelly_zgzcw_data()
        if kelly_zgzcw_data:
            print(f"[OK] zgzcw凯利数据: {len(kelly_zgzcw_data.get('matches', []))} 场比赛")

        # 构建比赛匹配索引：(homeEN_norm, awayEN_norm) -> odds_event
        odds_match_index = {}
        for lc, events in odds_api_data.items():
            for evt in events:
                key = (_normalize_name(evt["homeEN"]), _normalize_name(evt["awayEN"]))
                odds_match_index[key] = evt

        # 构建 schedule 英文名映射，用于匹配 The Odds API 队名
        schedule_en_map_for_odds = _build_schedule_en_map(all_matches)

        # ===== 6.6 获取竞彩网赔率（备选数据源 fallback） =====
        print("[INFO] 获取竞彩网赔率（备选数据源）...")
        sporttery_odds = await _fetch_sporttery_odds(sdk)
        print(f"[OK] 竞彩网赔率: {len(sporttery_odds)} 场比赛可用")

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
                # 从Odds API赔率计算Kelly值（Bet365+韦德）
                _odds_kelly = _compute_kelly_from_odds_api(matched_odds_evt["bookmakers"])
                if _odds_kelly.get('bet365') and _odds_kelly.get('weide'):
                    # 计算基础概率用于场景分析
                    _w2, _d2, _l2, _, _ = normalize_odds(m.get("odds", {}))
                    if _w2 and _d2 and _l2:
                        _bp = calc_kelly_probs(_w2, _d2, _l2)
                        _base_p = {'hf': _bp['胜'], 'df': _bp['平'], 'af': _bp['负']}
                    else:
                        _ep = calc_elo_probs(get_team_strength(teams, _home), get_team_strength(teams, _away))
                        _base_p = {'hf': _ep['胜'], 'df': _ep['平'], 'af': _ep['负']}
                    kelly_data = calc_kelly_scenario(_odds_kelly, _base_p)
                if kelly_data and kelly_data.get("scenario"):
                    disp_tag = f" 离散度{round(kelly_data.get('dispersion',0),3)}" if kelly_data.get('dispersion') else ""
                    skip_tag_k = " [SKIP]" if kelly_data.get('skip') else ""
                    print(f"[KELLY] {_home} vs {_away}: 场景{kelly_data['scenario']} {kelly_data.get('signal', '')}{disp_tag}{skip_tag_k}")

            # ===== 500.com 凯利数据 fallback =====
            # 当 Odds API 无数据时，使用500.com抓取的凯利数据
            if not kelly_data and kelly_500com_data:
                matched_500com = _match_500com_match(_home, _away, match_league, kelly_500com_data)
                if matched_500com:
                    # 提取Bet365和韦德的Kelly数据（新版七场景引擎）
                    _kelly_companies = _extract_kelly_companies_500com(matched_500com.get("companies", {}))
                    if _kelly_companies.get('bet365') and _kelly_companies.get('weide'):
                        # 计算基础概率
                        _w3, _d3, _l3, _, _ = normalize_odds(m.get("odds", {}))
                        if _w3 and _d3 and _l3:
                            _bp3 = calc_kelly_probs(_w3, _d3, _l3)
                            _base_p3 = {'hf': _bp3['胜'], 'df': _bp3['平'], 'af': _bp3['负']}
                        else:
                            _ep3 = calc_elo_probs(get_team_strength(teams, _home), get_team_strength(teams, _away))
                            _base_p3 = {'hf': _ep3['胜'], 'df': _ep3['平'], 'af': _ep3['负']}
                        kelly_data = calc_kelly_scenario(_kelly_companies, _base_p3)
                        if kelly_data and kelly_data.get("scenario"):
                            disp_tag = f" 离散度{round(kelly_data.get('dispersion',0),3)}" if kelly_data.get('dispersion') else ""
                            skip_tag_k = " [SKIP]" if kelly_data.get('skip') else ""
                            print(f"[KELLY-500COM] {_home} vs {_away}: 场景{kelly_data['scenario']} {kelly_data.get('signal', '')}{disp_tag}{skip_tag_k}")

            # ===== 竞彩网赔率 fallback =====
            # 当 schedule.json 无赔率且 The Odds API 无多公司数据时，
            # 从竞彩网获取胜平负赔率作为备选数据源
            if not m.get("odds") and not kelly_data:
                sporttery_match = _match_sporttery_odds(_home, _away, sporttery_odds)
                if sporttery_match:
                    # 构建赔率数据（兼容 normalize_odds 的简单格式）
                    odds_data = {
                        "source": "竞彩网",
                        "w": sporttery_match["w"],
                        "d": sporttery_match["d"],
                        "l": sporttery_match["l"],
                    }
                    # 如果有让球赔率，也添加进来
                    hcp_w = sporttery_match.get("hcp_w", 0)
                    hcp_d = sporttery_match.get("hcp_d", 0)
                    hcp_l = sporttery_match.get("hcp_l", 0)
                    handicap = sporttery_match.get("handicap", "")
                    if hcp_w > 1.0 and hcp_d > 1.0 and hcp_l > 1.0 and handicap:
                        # 将让球赔率存储为竞彩格式（normalize_odds 已支持）
                        hcp_key = f"odds_{handicap}"  # e.g., "odds_-1" or "odds_+1"
                        odds_data["odds_0"] = {"胜": sporttery_match["w"], "平": sporttery_match["d"], "负": sporttery_match["l"]}
                        odds_data[hcp_key] = {"胜": hcp_w, "平": hcp_d, "负": hcp_l}
                    m["odds"] = odds_data
                    print(f"[FALLBACK] {_home} vs {_away}: 竞彩网赔率 {sporttery_match['w']:.2f}/{sporttery_match['d']:.2f}/{sporttery_match['l']:.2f}")

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
                "kellyPick": pred.get("kellyPick"),
                "kellyCover": pred.get("kellyCover"),
                "kellyDispersion": pred.get("kellyDispersion"),
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

            # 保存赔率数据到 record（竞彩网 fallback 或已有赔率）
            if m.get("odds"):
                pred_map[match_id]["odds"] = m["odds"]
                pred_map[match_id]["odds_source"] = m["odds"].get("source", "unknown")

        # ===== 8. 组装最终预测列表 =====
        # 只保留昨天、今天、明天的预测（不提前预测太远，不保留太久）
        allowed_display_dates = {yesterday_str, today_str, tomorrow_str}
        final_predictions = []

        # 先添加已验证的（按日期排序），只保留3天内
        verified_preds = [p for p in existing_predictions if p.get("verified")]
        verified_before_filter = len(verified_preds)
        verified_preds = [p for p in verified_preds if p.get("date", "")[:8].replace("-", "") in allowed_display_dates]
        filtered_old_verified = verified_before_filter - len(verified_preds)
        verified_preds.sort(key=lambda x: x.get("date", ""))
        final_predictions.extend(verified_preds)
        print(f"[DEBUG] 已验证旧预测: {len(verified_preds)} 条（清理{filtered_old_verified}条过期）")

        # 再添加未验证的（新的和更新的），只保留3天内
        unverified_preds = [p for mid, p in pred_map.items() if not p.get("verified")]
        unverified_before_filter = len(unverified_preds)
        unverified_preds = [p for p in unverified_preds if p.get("date", "")[:8].replace("-", "") in allowed_display_dates]
        filtered_old_unverified = unverified_before_filter - len(unverified_preds)
        unverified_preds.sort(key=lambda x: x.get("date", ""))
        final_predictions.extend(unverified_preds)
        if filtered_old_unverified > 0:
            print(f"[DEBUG] 清理过期未验证预测: {filtered_old_unverified} 条")
        print(f"[DEBUG] 未验证预测: {len(unverified_preds)} 条 (新增{new_count}+更新{update_count})")

        print(f"[INFO] 预测统计: 保留已验证 {keep_count}, 更新 {update_count}, 新增 {new_count}")

        # Debug: 检查有多少预测包含赔率
        _preds_with_odds = [p for p in final_predictions if p.get("odds")]
        _preds_with_jc = [p for p in final_predictions if p.get("odds_source") == "竞彩网"]
        print(f"[DEBUG] final_predictions 中有赔率: {len(_preds_with_odds)} 场, 竞彩网: {len(_preds_with_jc)} 场")

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
                    # 离散度标签
                    kelly_disp = p.get("kellyDispersion")
                    disp_tag = f" D{round(kelly_disp,3)}" if kelly_disp else ""
                    unique_tag = ""
                    reverse_tag = ""
                    conf = p.get("confidence", 0)
                    pred_text = p.get("prediction", "")
                    pred_type = "单选" if p.get("type") == "single" else "双选"

                    line = (
                        f"  {p.get('home', '')} vs {p.get('away', '')}\n"
                        f"    {pred_type} {pred_text} | 置信度{conf}% | {stars_str}{kelly_tag}{disp_tag}{unique_tag}{reverse_tag}{skip_tag}\n"
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

