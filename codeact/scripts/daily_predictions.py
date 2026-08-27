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

# 回测表辅助模块（步骤①②自动写入回测表）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import backtest_helper
except ImportError:
    backtest_helper = None
    print("[WARN] backtest_helper 模块未找到，回测表写入功能禁用")

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
    "立博": "ladbrokes",
}



# ===== 七场景引擎辅助函数 =====

def _k_judge_kelly(kelly_val: float, payout: float) -> str:
    """Kelly判断：Kelly<=payout就是favor，否则bad"""
    if kelly_val <= payout:
        return 'favor'
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


def _apply_kebo(r: dict, kelly_companies: dict, odds: dict = None) -> None:
    """
    可博单选/博平检测（在七场景逻辑之后追加，不改变现有场景结果）

    规则A - 可博单选胜/负（需同时满足3个条件）：
      1. Bet365和韦德同时favor该队胜（或客胜）
      2. 两家各自只有这一个方向是favor
      3. 该队胜的赔率最低（比平赔率和另一队胜赔率都低）

    规则B - 可博平（需同时满足3个条件）：
      1. Bet365和韦德的平Kelly都是各自最低值且低于赔付率
      2. 立博配合：立博的平Kelly也是最低值且低于赔付率
      3. 立博数据必须存在才触发
    """
    if r.get('skip'):
        return

    c365 = kelly_companies.get('bet365')
    cw = kelly_companies.get('weide')
    if not c365 or not cw:
        return

    f365 = _k_favored(c365)
    fW = _k_favored(cw)

    # ===== 规则A: 可博单选胜/负 =====
    for win_dir, odds_key in [('h', 'w'), ('a', 'l')]:
        # 条件1: Bet365和韦德同时favor该方向
        if win_dir not in f365 or win_dir not in fW:
            continue
        # 条件2: 两家各自只有这一个方向是favor
        if len(f365) != 1 or len(fW) != 1:
            continue
        # 条件3: 该队胜的赔率最低（比平赔率和另一队胜赔率都低）
        if not odds:
            continue
        win_odds_val = odds.get(odds_key)
        draw_odds_val = odds.get('d')
        other_odds_key = 'l' if odds_key == 'w' else 'w'
        other_odds_val = odds.get(other_odds_key)
        if not win_odds_val or not draw_odds_val or not other_odds_val:
            continue
        if win_odds_val < draw_odds_val and win_odds_val < other_odds_val:
            kebo_type = '博单选胜' if win_dir == 'h' else '博单选负'
            r['keBo'] = True
            r['keBoType'] = kebo_type
            r['label'] = r.get('label', '') + f' [可{kebo_type}]'
            return

    # ===== 规则B: 可博平 =====
    clb = kelly_companies.get('ladbrokes')
    if not clb:
        return
    l365 = _k_lowest(c365)
    lW = _k_lowest(cw)
    lLb = _k_lowest(clb)
    # 条件1: Bet365和韦德的平Kelly都是各自最低值且低于赔付率
    if l365['dir'] != 'd' or lW['dir'] != 'd':
        return
    if c365['kelly_d'] > c365['payout'] or cw['kelly_d'] > cw['payout']:
        return
    # 条件2: 立博的平Kelly也是最低值且低于赔付率
    if lLb['dir'] != 'd':
        return
    if clb['kelly_d'] > clb['payout']:
        return
    r['keBo'] = True
    r['keBoType'] = '博平'
    r['label'] = r.get('label', '') + ' [可博平]'


def calc_kelly_scenario(kelly_companies: dict, base_probs: dict = None, odds_conf: float = None, odds: dict = None) -> dict:
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
    odds: {"w": float, "d": float, "l": float} 实际赔率（用于胜vs平赔率比较）

    Returns: 包含 scenarios, label, adjustments, confidence_mod, skip, pick, cover, finalProbs 等字段
    """
    _empty = {
        'scenarios': [], 'label': '', 'adjustments': {'hf': 0, 'df': 0, 'af': 0},
        'confidence_mod': 0, 'skip': False, 'skipReason': '',
        'pick': None, 'cover': None, 'finalProbs': None,
        'bet365_kelly': None, 'weide_kelly': None,
        'bet365_payout': None, 'weide_payout': None,
        'dispersion': 0, 'scenario': None, 'signal': None,
        'keBo': None, 'keBoType': None,
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
        'keBo': None, 'keBoType': None,
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
        _apply_kebo(r, kelly_companies, odds)
        return r

        # ===== 场景零：共同看好（赔率定主方向，Kelly定补防） =====
    common_favor = [d for d in f365 if d in fW]
    if common_favor:
        # 赔率概率最高的方向作为主选(pick)
        _dir_map = {'hf': 'h', 'df': 'd', 'af': 'a'}
        top_key = max(base_probs, key=base_probs.get)
        top_dir = _dir_map.get(top_key, top_key)
        r['scenarios'].append('0')
        r['pick'] = top_dir
        r['label'] = f"共同看好{'/'.join(_K_DN[d] for d in common_favor)}，主选{_K_DN[top_dir]}"
        # 对common_favor方向加+0.15调整
        for d in common_favor:
            r['adjustments'][_K_DK[d]] += 0.15
        # 非主选的common_favor方向作为补防(cover)，额外+0.05
        for d in common_favor:
            if d != top_dir:
                r['cover'] = d
                r['adjustments'][_K_DK[d]] += 0.05
                r['label'] += f"，防{_K_DN[d]}"
        r['scenario'] = '0'
        r['signal'] = r['label']
        r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
        _apply_kebo(r, kelly_companies, odds)
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
            common_pick_dir = remain_common_favor[0]

            # 经验规则：如果共同看好是平，且被看好队的胜也在剩余方向中
            # → 用赔率比较决定pick：赔率低的方向概率更大
            if common_pick_dir == 'd' and odds:
                favored_win_dir = None
                if 'h' in remain_dirs:
                    favored_win_dir = 'h'
                elif 'a' in remain_dirs:
                    favored_win_dir = 'a'

                if favored_win_dir:
                    win_odds_val = odds.get('w') if favored_win_dir == 'h' else odds.get('l')
                    draw_odds_val = odds.get('d')

                    if win_odds_val and draw_odds_val:
                        # 判断两家公司是否都对该队胜Kelly最低
                        if favored_win_dir == 'h':
                            both_win_kelly_lowest = (
                                c365['kelly_h'] <= c365['kelly_d'] and c365['kelly_h'] <= c365['kelly_a'] and
                                cw['kelly_h'] <= cw['kelly_d'] and cw['kelly_h'] <= cw['kelly_a']
                            )
                            both_draw_kelly_lowest = (
                                c365['kelly_d'] <= c365['kelly_h'] and c365['kelly_d'] <= c365['kelly_a'] and
                                cw['kelly_d'] <= cw['kelly_h'] and cw['kelly_d'] <= cw['kelly_a']
                            )
                        else:
                            both_win_kelly_lowest = (
                                c365['kelly_a'] <= c365['kelly_d'] and c365['kelly_a'] <= c365['kelly_h'] and
                                cw['kelly_a'] <= cw['kelly_d'] and cw['kelly_a'] <= cw['kelly_h']
                            )
                            both_draw_kelly_lowest = (
                                c365['kelly_d'] <= c365['kelly_h'] and c365['kelly_d'] <= c365['kelly_a'] and
                                cw['kelly_d'] <= cw['kelly_h'] and cw['kelly_d'] <= cw['kelly_a']
                            )

                        if win_odds_val <= draw_odds_val:
                            # 胜赔率≤平赔率 → 赔率指向胜，直接选胜
                            r['pick'] = favored_win_dir
                            r['adjustments'][_K_DK[favored_win_dir]] += 0.15
                            r['cover'] = 'd'
                            r['adjustments']['df'] += 0.05
                            bad_label = ''.join(_K_DN[d] for d in common_bad)
                            r['label'] = f'场景一-两家不看好{bad_label}，看好胜平且胜赔≤平赔→{_K_DN[favored_win_dir]}+平'
                        else:
                            # 平赔率<胜赔率
                            if both_win_kelly_lowest:
                                # 两家该队胜Kelly都最低 → 胜概率仍略大于平
                                r['pick'] = favored_win_dir
                                r['adjustments'][_K_DK[favored_win_dir]] += 0.15
                                r['cover'] = 'd'
                                r['adjustments']['df'] += 0.05
                                bad_label = ''.join(_K_DN[d] for d in common_bad)
                                r['label'] = f'场景一-两家不看好{bad_label}，看好胜平虽平赔低但两家胜Kelly都最低→{_K_DN[favored_win_dir]}+平'
                            else:
                                # 平赔低且该队胜Kelly不都最低 → 平概率大于胜
                                r['pick'] = 'd'
                                r['adjustments']['df'] += 0.15
                                r['cover'] = favored_win_dir
                                r['adjustments'][_K_DK[favored_win_dir]] += 0.05
                                bad_label = ''.join(_K_DN[d] for d in common_bad)
                                r['label'] = f'场景一-两家不看好{bad_label}，看好胜平且平赔<胜赔→平+{_K_DN[favored_win_dir]}'
                        r['scenarios'].append('1')
                        r['scenario'] = '1'
                        r['signal'] = r['label']
                        r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
                        _apply_kebo(r, kelly_companies, odds)
                        return r

            # 默认：共同看好的方向作为pick
            r['scenarios'].append('1')
            r['pick'] = common_pick_dir
            r['adjustments'][_K_DK[common_pick_dir]] += 0.15
            bad_label = ''.join(_K_DN[d] for d in common_bad)
            r['label'] = f'场景一-两家不看好{bad_label}，看好{_K_DN[common_pick_dir]}'
            # 防覆盖：另一个剩余方向如果有一家看好，加cover
            other_remain = [d for d in remain_dirs if d != common_pick_dir]
            if len(other_remain) == 1:
                o_dir = other_remain[0]
                if o_dir in f365 or o_dir in fW:
                    r['cover'] = o_dir
                    r['adjustments'][_K_DK[o_dir]] += 0.05
                    r['label'] += f'，防{_K_DN[o_dir]}'
            r['scenario'] = '1'
            r['signal'] = r['label']
            r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
            _apply_kebo(r, kelly_companies, odds)
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
            _apply_kebo(r, kelly_companies, odds)
            return r

        # commonBad但没有明确剩余共同看好方向
        # 经验规则：在被看好不败的队内部，比较胜vs平的赔率
        # - 胜赔率 < 平赔率 → 胜概率略大于平
        # - 平赔率 < 胜赔率 → 除非该队胜Kelly也最低，否则平概率略大于胜
        # 找到被看好不败的队（不在common_bad中的方向）
        favored_team_dirs = [d for d in remain_dirs if d in f365 or d in fW]
        if favored_team_dirs and 'd' not in common_bad and odds:
            # 有球队被看好（胜或平Kelly低于赔付率），且平没被排除
            favored_dir = favored_team_dirs[0]  # 'h'或'a'
            # 用实际赔率比较
            if favored_dir == 'h':
                win_odds_val = odds.get('w')
                draw_odds_val = odds.get('d')
            else:
                win_odds_val = odds.get('l')
                draw_odds_val = odds.get('d')

            if win_odds_val and draw_odds_val:
                # 判断两家公司是否都对该队胜Kelly最低（各自三方向中最低）
                if favored_dir == 'h':
                    both_favored_win_kelly_lowest = (
                        c365['kelly_h'] <= c365['kelly_d'] and c365['kelly_h'] <= c365['kelly_a'] and
                        cw['kelly_h'] <= cw['kelly_d'] and cw['kelly_h'] <= cw['kelly_a']
                    )
                    both_draw_kelly_lowest = (
                        c365['kelly_d'] <= c365['kelly_h'] and c365['kelly_d'] <= c365['kelly_a'] and
                        cw['kelly_d'] <= cw['kelly_h'] and cw['kelly_d'] <= cw['kelly_a']
                    )
                else:
                    both_favored_win_kelly_lowest = (
                        c365['kelly_a'] <= c365['kelly_d'] and c365['kelly_a'] <= c365['kelly_h'] and
                        cw['kelly_a'] <= cw['kelly_d'] and cw['kelly_a'] <= cw['kelly_h']
                    )
                    both_draw_kelly_lowest = (
                        c365['kelly_d'] <= c365['kelly_h'] and c365['kelly_d'] <= c365['kelly_a'] and
                        cw['kelly_d'] <= cw['kelly_h'] and cw['kelly_d'] <= cw['kelly_a']
                    )

                if win_odds_val <= draw_odds_val:
                    # 胜赔率低于或等于平赔率 → 通常胜概率略大于平
                    # 例外：两家公司平Kelly都最低 → 平概率可能反超
                    if both_draw_kelly_lowest:
                        # 两家平Kelly都最低 → 平概率反超
                        r['scenarios'].append('1')
                        r['pick'] = 'd'
                        r['cover'] = favored_dir
                        r['adjustments']['df'] += 0.10
                        r['adjustments'][_K_DK[favored_dir]] += 0.05
                        r['label'] = f'场景一-平+{_K_DN[favored_dir]}（胜赔低但两家平Kelly都最低）'
                    else:
                        r['scenarios'].append('1')
                        r['pick'] = favored_dir
                        r['cover'] = 'd'
                        r['adjustments'][_K_DK[favored_dir]] += 0.10
                        r['adjustments']['df'] += 0.05
                        r['label'] = f'场景一-赔率优先{_K_DN[favored_dir]}+平（看好不败，胜赔≤平赔）'
                    r['scenario'] = '1'
                    r['signal'] = r['label']
                    r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
                    _apply_kebo(r, kelly_companies, odds)
                    return r
                else:
                    # 平赔率低于胜赔率
                    # 除非两家公司该队胜Kelly都最低 → 否则平概率大于胜
                    if both_favored_win_kelly_lowest:
                        # 两家该队胜Kelly都最低 → 胜概率仍略大于平
                        r['scenarios'].append('1')
                        r['pick'] = favored_dir
                        r['cover'] = 'd'
                        r['adjustments'][_K_DK[favored_dir]] += 0.10
                        r['adjustments']['df'] += 0.05
                        r['label'] = f'场景一-{_K_DN[favored_dir]}Kelly最低+平（虽平赔低但两家胜Kelly都最低）'
                    else:
                        # 该队胜Kelly不是两家都最低 → 平概率略大于胜
                        r['scenarios'].append('1')
                        r['pick'] = 'd'
                        r['cover'] = favored_dir
                        r['adjustments']['df'] += 0.10
                        r['adjustments'][_K_DK[favored_dir]] += 0.05
                        r['label'] = f'场景一-平+{_K_DN[favored_dir]}（平赔低且该队胜Kelly不都最低）'
                    r['scenario'] = '1'
                    r['signal'] = r['label']
                    r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
                    _apply_kebo(r, kelly_companies, odds)
                    return r

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
        _apply_kebo(r, kelly_companies, odds)
        return r

    # ===== 场景三：去平局（仅当平局被dropped且主客都没被drop时） =====
    if 'd' in dropped and 'h' not in dropped and 'a' not in dropped:
        r['scenarios'].append('3')
        r['adjustments']['df'] = -(base_probs.get('df', 0.27) * 0.7)
        r['label'] = '场景三-去平局'
        r['scenario'] = '3'
        r['signal'] = r['label']
        r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])
        _apply_kebo(r, kelly_companies, odds)
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
        _apply_kebo(r, kelly_companies, odds)
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
            _apply_kebo(r, kelly_companies, odds)
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
        _apply_kebo(r, kelly_companies, odds)
        return r

    # 兜底：如果有场景标签但没返回
    if r['scenarios']:
        r['signal'] = r['label']
        r['finalProbs'] = _k_norm_adj(base_probs, r['adjustments'])

    _apply_kebo(r, kelly_companies, odds)
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
    api_to_core = {'bet365': 'bet365', 'betvictor': 'weide', 'ladbrokes_uk': 'ladbrokes'}
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



def _calc_v2_strategy_tier(w, d, l, kelly_data=None):
    """
    V2策略分层检测（基于258场回测 2026-08-04，融合V5更新于19:47）
    本质发现：博彩公司对"比赛会不会平"的判断是核心指标
    平赔>=4.0 → 平局概率<23% → 冷门率仅10% → 强队不败命中率90%
    S+级：平赔>=4.0 + V5去平场景 → 13场100%，7/7天稳定

    Returns:
        (tier, fav_odds, draw_odds):
        tier: 'S+' | 'S' | 'A' | None
        fav_odds: 强队赔率
        draw_odds: 平赔
    """
    if w is None or d is None or l is None:
        return None, None, None

    fav_odds = min(w, l)  # 强队赔率（赔率低的是强队）
    draw_odds = d

    # S级精选：平赔>=4.0 → 69场89.9%（本质：平局概率<23%，冷门率仅10%）
    if draw_odds >= 4.0:
        # S+融合检测：V5去平场景 → 13场100%
        if kelly_data and kelly_data.get('bet365_kelly') and kelly_data.get('weide_kelly'):
            k365 = kelly_data['bet365_kelly']
            kw = kelly_data['weide_kelly']
            p365 = kelly_data.get('bet365_payout', 0.93)
            pw = kelly_data.get('weide_payout', 0.93)
            # 各方向Kelly信号（<=payout=看好）
            def kelly_sig(k, p):
                sig = []
                for d_key in ['h', 'd', 'a']:
                    if k.get(d_key, 1.0) <= p:
                        sig.append(d_key)
                return set(sig)
            sig365 = kelly_sig(k365, p365)
            sigW = kelly_sig(kw, pw)
            # 去平：看好胜+负，不看好平
            def is_no_draw(sig):
                return sig == {'h', 'a'}
            # 看好不败：H={h,d}/pure_H={h}, A={d,a}
            def is_h_safe(sig):
                return sig in ({'h', 'd'}, {'h'})
            def is_a_safe(sig):
                return sig == {'d', 'a'}
            # 去平场景（V5融合）：
            # 场景⑤：一家去平+另一家看好不败(H或A)
            # 场景③：两家都去平
            is_quping = False
            if is_no_draw(sig365) and (is_h_safe(sigW) or is_a_safe(sigW)):
                is_quping = True
            if is_no_draw(sigW) and (is_h_safe(sig365) or is_a_safe(sig365)):
                is_quping = True
            if is_no_draw(sig365) and is_no_draw(sigW):
                is_quping = True
            if is_quping:
                return 'S+', fav_odds, draw_odds
        return 'S', fav_odds, draw_odds

    # A级常规：平赔>=3.1 且 强赔<2.3（但平赔<4.0） → 125场75.2%
    if draw_odds >= 3.1 and fav_odds < 2.3:
        return 'A', fav_odds, draw_odds

    return None, fav_odds, draw_odds

# ===== V6 36场景Kelly分类体系（2026-08-05定稿） =====
# 强队视角状态字母映射: frozenset(favored_directions) → (当强队是主队, 当强队是客队)
_V6_STATE_MAP = {
    frozenset(['h']): ('A', 'Z'),
    frozenset(['h', 'd']): ('B', 'W'),
    frozenset(['h', 'a']): ('C', 'C'),
    frozenset(['d']): ('Y', 'Y'),
    frozenset(['a']): ('Z', 'A'),
    frozenset(['d', 'a']): ('W', 'B'),
    frozenset(['h', 'd', 'a']): ('D', 'D'),
    frozenset(): ('X', 'X'),
}

# V6 36场景策略表: (365_state, weide_state) → (prediction, hit_rate%)
_V6_SCENARIO_TABLE = {
    # 范畴一（两家都含强队胜方向A/B/C）- V6.2 284场回测 78.8%
    ('A','A'): ('胜平', 81.0), ('A','B'): ('胜平', 90.9), ('A','C'): ('胜平', 88.9),
    ('B','A'): ('胜平', 69.0), ('B','B'): ('胜平', 81.8), ('B','C'): ('胜平', 73.9),
    ('C','A'): ('胜负', 80.0), ('C','B'): ('胜平', 83.3), ('C','C'): ('胜负', 85.7),
    # 范畴二（一家含A/B/C，另一家含W/Y/Z）- V6.2 88.2%
    ('A','W'): ('胜平', 66.7), ('A','Y'): ('胜平', 66.7), ('A','Z'): ('胜负', 100.0),
    ('B','W'): ('胜平', 100.0), ('B','Y'): ('胜平', 100.0), ('B','Z'): ('胜平', 88.9),
    ('C','W'): ('平负', 83.3), ('C','Y'): ('胜平', 100.0), ('C','Z'): ('胜负', 100.0),
    ('W','A'): ('胜平', 89.5), ('W','B'): ('胜平', 83.3), ('W','C'): ('胜负', 72.7),
    ('Y','A'): ('胜负', 100.0), ('Y','B'): ('胜平', 100.0), ('Y','C'): ('胜负', 100.0),
    ('Z','A'): ('胜负', 75.0), ('Z','B'): ('胜平', 100.0), ('Z','C'): ('胜负', 100.0),
    # 范畴三（两家都不含强队胜方向）- V6.2 90.5%
    ('W','W'): ('胜平', 76.9), ('W','Y'): ('胜负', 100.0), ('W','Z'): ('胜负', 90.9),
    ('Y','W'): ('平负', 100.0), ('Y','Y'): ('平胜', 0.0), ('Y','Z'): ('胜负', 100.0),
    ('Z','W'): ('胜负', 100.0), ('Z','Y'): ('平负', 100.0), ('Z','Z'): ('负胜', 100.0),
}

# 范畴一/二/三包含的状态字母（含强队胜方向A/B/C vs 不含Y/Z/W）
_V6_FAV_DIRS = {'A', 'B', 'C'}  # 含强队胜方向
_V6_NON_FAV_DIRS = {'Y', 'Z', 'W'}  # 不含强队胜方向

# 蛙跳盘阈值：澳门亚盘让球盘初盘→终盘跳级≥0.5（跨一个中间盘口）触发
_V6_FROG_JUMP_THRESHOLD = 0.5


def _get_v6_state_letter(favored_dirs: set, is_home_strong: bool) -> str:
    """根据看好方向和强队位置，返回V6状态字母"""
    key = frozenset(favored_dirs)
    mapping = _V6_STATE_MAP.get(key)
    if mapping is None:
        return 'X'
    return mapping[0] if is_home_strong else mapping[1]


def _detect_frog_jump(macau_data: dict, is_home_strong: bool) -> dict:
    """
    检测澳门蛙跳盘（V2：基于完整盘口变化路径，必须连续同向跳两级且不跨让受界限）。

    规则（主人2026-08-23定）：
      1. 必须在盘口变化路径中找到连续同向跳两级（每级0.25，两级=0.5）才算蛙跳
      2. 中间有转向不算；但转向后重新连续同向跳两级可以算
      3. 不跨让受界限：路径中不能从正数跨过0变到负数（或反过来）；平手0作为起止点可以，不能穿越
      4. 方向：盘口值连续增大（升盘）→ up；连续减小（降盘）→ down

    数据来源：macau_data['handicap_path']，由抓取脚本从500万亚指变化接口取得，
             按时间顺序（早→晚）排列，每项 {'val': float, ...}。
             没有path或点数不足时降级为不触发（安全默认）。

    is_home_strong 仅用于返回值上下文，方向判断本身基于盘口值升降。
    Returns: {"jump": bool, "direction": "up"/"down"/None, "path_len": int, "detail": str}
    """
    empty = {"jump": False, "direction": None, "path_len": 0, "detail": ""}
    if not macau_data:
        return empty

    path_raw = macau_data.get("handicap_path")
    # 兼容：没有path时尝试用初盘+即时盘两点（不足3点不触发）
    if not path_raw:
        init_val = macau_data.get("initial_handicap_val")
        latest_val = macau_data.get("latest_handicap_val")
        if init_val is None or latest_val is None:
            return empty
        path_raw = [{"val": init_val}, {"val": latest_val}]

    # 提取数值序列，过滤无效值；相邻相同盘口值保留（不影响方向判断）
    vals = []
    for p in path_raw:
        v = p.get("val") if isinstance(p, dict) else None
        if v is None:
            continue
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            continue

    if len(vals) < 3:
        # 只有初盘+即时盘两点，无法判断是否连续同向跳级，不触发
        return {**empty, "path_len": len(vals),
                "detail": "路径不足3点，无法判断连续跳级"}

    STEP = 0.25  # 一个盘口等级
    TWO_LEVEL = 0.5  # 连续两级

    # 去重相邻完全相同的盘口值（水位变化但盘口没变不算变动）
    compressed = [vals[0]]
    for v in vals[1:]:
        if v != compressed[-1]:
            compressed.append(v)

    if len(compressed) < 3:
        return {**empty, "path_len": len(vals),
                "detail": "盘口值未发生两级变动"}

    # 滑动窗口找连续同向两级跳：a→b→c
    # 要求 (b-a) 与 (c-b) 同号，且 |b-a|≈|c-b|≈0.25，两段合计=0.5
    for i in range(len(compressed) - 2):
        a, b, c = compressed[i], compressed[i + 1], compressed[i + 2]
        d1 = round(b - a, 4)
        d2 = round(c - b, 4)

        # 每级必须恰好一个盘口台阶(±0.25)，两级同向
        if abs(d1 - STEP) > 0.001 and abs(d1 + STEP) > 0.001:
            continue
        if abs(d2 - STEP) > 0.001 and abs(d2 + STEP) > 0.001:
            continue
        if d1 * d2 <= 0:
            continue  # 方向不一致或为0

        total = round(c - a, 4)
        if abs(total) < TWO_LEVEL - 0.001:
            continue

        # 检查是否跨让受界限：a,b,c三个值中同时出现正数和负数（穿越0）
        signs = [1 if x > 0 else (-1 if x < 0 else 0) for x in (a, b, c)]
        has_pos = any(s > 0 for s in signs)
        has_neg = any(s < 0 for s in signs)
        if has_pos and has_neg:
            continue  # 跨了让受界限，不算

        direction = "up" if total > 0 else "down"
        return {
            "jump": True,
            "direction": direction,
            "path_len": len(vals),
            "detail": f"{a}→{b}→{c} 连{'升' if direction=='up' else '降'}两级",
        }

    return {**empty, "path_len": len(vals),
            "detail": "未发现连续同向两级跳"}

def classify_v6_scenario(kelly_data: dict, odds_365: dict = None, macau_data: dict = None) -> dict:
    """
    V6 36场景Kelly分类
    
    Args:
        kelly_data: calc_kelly_scenario返回的数据，含bet365_kelly/weide_kelly/payout
        odds_365: {"w": float, "d": float, "l": float} bet365赔率（判断强队方向）
        macau_data: 澳门亚盘数据（蛙跳检测），含 initial_handicap_val / latest_handicap_val
    
    Returns:
        {
            "scenario": "AB",        # 场景代码
            "category": 1,           # 范畴1/2/3
            "favor_level": "看好",    # 看好等级
            "confidence_level": "强信心",  # 信心等级
            "prediction": "胜平",     # 双选策略
            "hit_rate": 90.0,        # 历史命中率
            "is_frog_jump": False,   # 是否蛙跳盘
            "frog_direction": None,  # 蛙跳方向
            "state_365": "A",        # 365状态字母
            "state_weide": "B",      # 韦德状态字母
        }
        若无法分类（D/X状态或缺数据）返回 None
    """
    if not kelly_data:
        return None
    
    b365_kelly = kelly_data.get('bet365_kelly')
    bw_kelly = kelly_data.get('weide_kelly')
    b365_payout = kelly_data.get('bet365_payout')
    bw_payout = kelly_data.get('weide_payout')
    
    if not b365_kelly or not bw_kelly or not b365_payout or not bw_payout:
        return None
    
    # 判断强队方向（365赔率：胜赔≤负赔→主队强）
    is_home_strong = True
    if odds_365:
        w_odds = odds_365.get('w', 0)
        l_odds = odds_365.get('l', 0)
        if w_odds > 1 and l_odds > 1:
            is_home_strong = w_odds <= l_odds
    
    # 获取各公司看好方向（Kelly <= payout）
    favored_365 = set()
    for d in ['h', 'd', 'a']:
        if b365_kelly.get(d, 1.0) <= b365_payout:
            favored_365.add(d)
    
    favored_weide = set()
    for d in ['h', 'd', 'a']:
        if bw_kelly.get(d, 1.0) <= bw_payout:
            favored_weide.add(d)
    
    # 转为强队视角状态字母
    state_365 = _get_v6_state_letter(favored_365, is_home_strong)
    state_weide = _get_v6_state_letter(favored_weide, is_home_strong)
    
    # D状态处理：某公司三个方向Kelly全部≤payout（全看好）
    # 取Kelly值最高的方向为"不看好"，其余两个为"看好"，映射到A/B/C/W/Y/Z
    has_d_state = False
    
    # 两家同时D → 无法分类
    if state_365 == 'D' and state_weide == 'D':
        return None
    
    # 单家D状态：转换（对齐backtest_v6.py的d_new函数）
    # 核心规则：移除所有Kelly值等于最大值的方向，保留剩余方向
    if state_365 == 'D':
        # 获取365三个方向的Kelly值
        kelly_vals = [b365_kelly.get(d, 0) for d in ['h', 'd', 'a']]
        if all(k == kelly_vals[0] for k in kelly_vals):
            # ①三值相等(h=d=a)：去掉强队负→B/W
            state_365 = 'B'  # V6.2: 三值相等统一B（强队不败，无论主客）
        else:
            # ②③④：移除所有并列最大Kelly值的方向，保留剩余
            max_val = max(kelly_vals)
            favored_365_d = {d for d in ['h', 'd', 'a'] if b365_kelly.get(d, 0) != max_val}
            state_365 = _get_v6_state_letter(favored_365_d, is_home_strong)
        has_d_state = True
    
    if state_weide == 'D':
        # 获取韦德三个方向的Kelly值
        kelly_vals = [bw_kelly.get(d, 0) for d in ['h', 'd', 'a']]
        if all(k == kelly_vals[0] for k in kelly_vals):
            # ①三值相等(h=d=a)：去掉强队负→B/W
            state_weide = 'B'  # V6.2: 三值相等统一B（强队不败，无论主客）
        else:
            # ②③④：移除所有并列最大Kelly值的方向，保留剩余
            max_val = max(kelly_vals)
            favored_weide_d = {d for d in ['h', 'd', 'a'] if bw_kelly.get(d, 0) != max_val}
            state_weide = _get_v6_state_letter(favored_weide_d, is_home_strong)
        has_d_state = True
    
    # X状态排除（X = 三个方向都不看好，无法分类）
    if state_365 == 'X' or state_weide == 'X':
        return None
    
    # 检查蛙跳盘（最高优先级）
    frog_jump = _detect_frog_jump(macau_data, is_home_strong)
    if frog_jump["jump"]:
        # 蛙跳盘：独立推荐上盘/下盘，不转胜平负
        pred = "上盘" if frog_jump["direction"] == "up" else "下盘"
        return {
            "scenario": "蛙跳",
            "category": 0,
            "favor_level": "强看好",
            "confidence_level": "强信心",
            "prediction": pred,
            "hit_rate": 100.0,
            "is_frog_jump": True,
            "frog_direction": frog_jump["direction"],
            "state_365": state_365,
            "state_weide": state_weide,
            "has_d_state": has_d_state,
        }
    
    # 查36场景策略表
    scenario_key = (state_365, state_weide)
    scenario_entry = _V6_SCENARIO_TABLE.get(scenario_key)
    if not scenario_entry:
        return None
    
    prediction, hit_rate = scenario_entry
    scenario_code = f"{state_365}{state_weide}"
    
    # V6.2 AA/WW 主客区分 + 强队视角→主队视角转换
    # 策略表默认存强队=主队时的推荐，强队=客队时需转换
    if scenario_code == 'AA':
        if is_home_strong:
            prediction = '胜平'
        else:
            prediction = '平胜'  # 强队=客, 强队平负→主队平胜
    elif scenario_code == 'WW':
        if is_home_strong:
            prediction = '胜平'
        else:
            prediction = '负胜'  # 强队=客, 强队胜负→主队负胜
    
    # V6.5 手动修正覆盖（16个override，与V6.2策略表不一致的场景）
    # 格式: (scenario_code, is_home_strong) → 竞彩视角prediction（主队视角）
    _V67_STRATEGY = {
        ('AA', True): '胜平',
        ('AA', False): '负平',
        ('AB', True): '平胜',
        ('AB', False): '负平',
        ('AC', True): '胜平',
        ('AC', False): '胜平',
        ('AW', True): '胜负',
        ('AW', False): '胜负',
        ('AY', True): '胜平',
        ('AY', False): '平胜',
        ('AZ', True): '负平',
        ('AZ', False): '负胜',
        ('BA', True): '胜平',
        ('BA', False): '平负',
        ('BB', True): '胜负',
        ('BB', False): '负胜',
        ('BC', True): '胜平',
        ('BC', False): '负胜',
        ('BW', True): '胜平',
        ('BW', False): '负胜',
        ('BY', True): '胜平',
        ('BY', False): '平负',
        ('BZ', True): '胜负',
        ('BZ', False): '胜平',
        ('CA', True): '胜负',
        ('CA', False): '负胜',
        ('CB', True): '胜平',
        ('CB', False): '平负',
        ('CC', True): '胜负',
        ('CC', False): '平负',
        ('CW', True): '胜负',
        ('CW', False): '负平',
        ('CY', True): '胜平',
        ('CY', False): '平负',
        ('CZ', True): '胜负',
        ('CZ', False): '胜负',
        ('WA', True): '胜平',
        ('WA', False): '平负',
        ('WB', True): '胜平',
        ('WB', False): '平负',
        ('WC', True): '胜平',
        ('WC', False): '负胜',
        ('WW', True): '胜平',
        ('WW', False): '平负',
        ('WY', True): '胜平',
        ('WY', False): '负胜',
        ('WZ', True): '胜负',
        ('WZ', False): '胜平',
        ('YA', True): '胜负',
        ('YA', False): '胜负',
        ('YB', True): '胜平',
        ('YB', False): '平负',
        ('YC', True): '胜负',
        ('YC', False): '负平',
        ('YW', True): '胜平',
        ('YW', False): '胜平',
        ('YY', True): '平胜',
        ('YY', False): '平负',
        ('YZ', True): '负胜',
        ('YZ', False): '负平',
        ('ZA', True): '胜平',
        ('ZA', False): '负胜',
        ('ZB', True): '胜平',
        ('ZB', False): '平负',
        ('ZC', True): '胜负',
        ('ZC', False): '胜负',
        ('ZW', True): '胜平',
        ('ZW', False): '胜负',
        ('ZY', True): '平负',
        ('ZY', False): '胜平',
        ('ZZ', True): '胜负',
        ('ZZ', False): '胜负',
    }
    override_key = (scenario_code, is_home_strong)
    if override_key in _V67_STRATEGY:
        prediction = _V67_STRATEGY[override_key]
    
    # 所有72子组策略已由_V67_STRATEGY完整覆盖，无需额外转换
    
    # 范畴判定
    s365_in_fav = state_365 in _V6_FAV_DIRS
    sweide_in_fav = state_weide in _V6_FAV_DIRS
    if s365_in_fav and sweide_in_fav:
        category = 1
        favor_level = "看好"
    elif s365_in_fav or sweide_in_fav:
        category = 2
        favor_level = "分歧"
    else:
        category = 3
        favor_level = "博冷"
    
    # 信心等级
    if hit_rate >= 80.0:
        confidence_level = "强信心"
    elif hit_rate >= 70.0:
        confidence_level = "中等信心"
    else:
        confidence_level = "弱信心待验证"
    
    return {
        "scenario": scenario_code,
        "category": category,
        "favor_level": favor_level,
        "confidence_level": confidence_level,
        "prediction": prediction,
        "hit_rate": hit_rate,
        "is_frog_jump": False,
        "frog_direction": None,
        "state_365": state_365,
        "state_weide": state_weide,
        "has_d_state": has_d_state,
    }


def predict_match(match: dict, teams: dict, kelly_data: dict = None,
                  odds_365: dict = None, macau_data: dict = None) -> dict:
    """
    对单场比赛生成预测（融合V6 36场景Kelly分类 + V5七场景引擎）
    kelly_data: 来自 calc_kelly_scenario() 的七场景分析数据
    odds_365: bet365赔率 {"w": float, "d": float, "l": float}（V6强队判定）
    macau_data: 澳门赔率数据（V6蛙跳检测）{"initial_odds": [w,d,l], "latest_odds": [w,d,l]}
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

        # 场景给出 pick+cover → 覆盖单双选（pick==cover时降为单选，避免"胜+胜"）
        if kelly_pick and kelly_cover and kelly_pick != kelly_cover:
            pick_cn = _DIR_EN_TO_CN.get(kelly_pick, kelly_pick)
            cover_cn = _DIR_EN_TO_CN.get(kelly_cover, kelly_cover)
            pred_type = 'double'
            prediction = f'{pick_cn}+{cover_cn}'
            double_pick = [pick_cn, cover_cn]
            reason = f'凯利场景{kelly_scenario}: {_K_DN.get(kelly_pick,"")}/{_K_DN.get(kelly_cover,"")} · {kelly_signal}'
            if has_odds:
                reason += f' · {odds_source}赔率'
        elif kelly_pick and (not kelly_cover or kelly_pick == kelly_cover):
            pick_cn = _DIR_EN_TO_CN.get(kelly_pick, kelly_pick)
            # 场景给出单选方向，如果概率优势足够，强化为单选
            if pred_type == 'double' and max_prob >= 0.45:
                pred_type = 'single'
                prediction = pick_cn
                double_pick = None
                reason = f'凯利场景{kelly_scenario}: 看好{_DIR_CN_TO_HD.get(kelly_pick,"")} · {kelly_signal}'
                if has_odds:
                    reason += f' · {odds_source}赔率'

    # ===== 矛盾检测：赔率方向与凯利信号冲突 → 不推荐投注 =====
    contradiction = False
    if has_odds and kelly_data and kelly_data.get('bet365_kelly') and kelly_data.get('weide_kelly'):
        # 赔率隐含的最强方向（概率最高的）
        odds_favorite_dir = sorted_probs[0][0]
        odds_favorite_prob = sorted_probs[0][1]
        dir_en = _DIR_CN_TO_EN.get(odds_favorite_dir, '')

        if dir_en and odds_favorite_prob >= 0.45:
            c365_kelly = kelly_data['bet365_kelly']
            cw_kelly = kelly_data['weide_kelly']
            c365_payout = kelly_data.get('bet365_payout', 0.93)
            cw_payout = kelly_data.get('weide_payout', 0.93)

            # 条件1：赔率看好的方向，两家Kelly都明确不看好（Kelly > payout + TOL）
            c365_bad = c365_kelly.get(dir_en, 1.0) > c365_payout + _K_TOL
            cw_bad = cw_kelly.get(dir_en, 1.0) > cw_payout + _K_TOL
            both_bad = c365_bad and cw_bad

            # 条件2：赔率看好某方向，但凯利场景pick是完全不同的方向
            kelly_pick_cn = _DIR_EN_TO_CN.get(kelly_pick, '') if kelly_pick else ''
            kelly_opposite = (kelly_pick and kelly_pick != dir_en and
                              odds_favorite_prob >= 0.50)

            # 条件3：赔率看好的方向，两家Kelly值都高于返还率（即使只高一点点）
            c365_above = c365_kelly.get(dir_en, 1.0) > c365_payout
            cw_above = cw_kelly.get(dir_en, 1.0) > cw_payout
            both_above = c365_above and cw_above

            if both_bad or (both_above and kelly_opposite):
                contradiction = True
                if both_bad:
                    skip_reason = f"赔率与凯利信号矛盾（赔率看好{odds_favorite_dir}但凯利明确不看好）"
                else:
                    skip_reason = f"赔率与凯利方向冲突（赔率看好{odds_favorite_dir}但凯利指向{kelly_pick_cn}）"
                # 如果Kelly选择与赔率偏好方向一致（赔率优先路径），只降星不跳过
                if kelly_pick == dir_en:
                    skip_reason += "（已按赔率优先处理）"
                    stars = max(1, stars - 1)
                else:
                    skip = True
                    stars = max(1, stars - 2)

    # ===== V2策略分层检测（平赔×强赔双条件筛选） =====
    v2_tier = None
    v2_fav_odds = None
    v2_draw_odds = None
    if has_odds:
        v2_tier, v2_fav_odds, v2_draw_odds = _calc_v2_strategy_tier(w, d, l, kelly_data)
        if v2_tier and not skip:
            # V2条件满足 → 强制预测为"强队不败"（回测80.3%命中率）
            fav_odds_val = min(w, l)
            if fav_odds_val == w:  # 主队是强队
                pick_cn = '胜'
            else:  # 客队是强队
                pick_cn = '负'
            pred_type = 'double'
            prediction = f'{pick_cn}+平'
            double_pick = [pick_cn, '平']
            if v2_tier == 'S+':
                reason = f'🔥V2精选(100%): 平赔{d:.1f}≥4.0+凯利去平，强队不败'
            elif v2_tier == 'S':
                reason = f'🏆V2精选(89.9%): 平赔{d:.1f}≥4.0，强队不败'
            else:
                reason = f'✅V2策略(80.3%): 平赔{d:.1f}≥3.1+强赔{fav_odds_val:.2f}<2.3，强队不败'
            if odds_source:
                reason += f' · {odds_source}赔率'
            # V2标记的比赛提升1星
            stars = min(5, stars + 1)

    # ===== V6 36场景Kelly分类（最高优先级） =====
    v6_result = classify_v6_scenario(kelly_data, odds_365=odds_365, macau_data=macau_data)
    v6_scenario = None
    v6_category = None
    favor_level = None
    confidence_level = None
    v6_hit_rate = None
    v6_is_frog_jump = False
    v6_state_365 = None
    v6_state_weide = None
    v6_has_d_state = False

    if v6_result:
        v6_scenario = v6_result['scenario']
        v6_category = v6_result['category']
        favor_level = v6_result['favor_level']
        confidence_level = v6_result['confidence_level']
        v6_hit_rate = v6_result['hit_rate']
        v6_is_frog_jump = v6_result['is_frog_jump']
        v6_state_365 = v6_result.get('state_365')
        v6_state_weide = v6_result.get('state_weide')
        v6_has_d_state = v6_result.get('has_d_state', False)

        # V6双选策略覆盖现有预测
        v6_pred = v6_result['prediction']

        if v6_is_frog_jump:
            # 蛙跳盘：独立推荐上盘/下盘，作为单选处理
            pred_type = 'single'
            prediction = v6_pred
            double_pick = None
            frog_dir = v6_result.get('frog_direction', '')
            frog_label = '上盘跳' if frog_dir == 'up' else '下盘跳'
            reason = f'🐸澳门蛙跳盘({frog_label}) → {prediction} | {favor_level} | {confidence_level}'
            if has_odds and odds_source:
                reason += f' · {odds_source}赔率'
            stars = min(5, max(stars, 4))  # 蛙跳盘至少4星
        else:
            # 常规双选：解析为两个方向
            v6_parts = list(v6_pred)  # e.g., "胜平" → ['胜', '平']
            if len(v6_parts) == 2:
                pred_type = 'double'
                prediction = f'{v6_parts[0]}+{v6_parts[1]}'
                double_pick = v6_parts

                d_tag = '含D ' if v6_has_d_state else ''
                reason = f'V6场景{v6_scenario}({d_tag}{favor_level} | {confidence_level} | 历史{v6_hit_rate}%) → {prediction}'

                if has_odds and odds_source:
                    reason += f' · {odds_source}赔率'

                # V6看好等级影响星级
                if favor_level == '强看好':
                    stars = min(5, max(stars, 4))
                elif favor_level == '看好':
                    stars = min(5, max(stars, 3))

    # ===== Kelly≥1.0 反向指标规则（三条） =====
    # 在V6场景预测之后执行，排除被反向指标标记的方向
    # 蛙跳盘不参与Kelly排除（double_pick是上盘/下盘，不是胜平负）
    if kelly_data and pred_type == 'double' and double_pick and not v6_is_frog_jump:
        b365_k = kelly_data.get('bet365_kelly', {})
        bw_k = kelly_data.get('weide_kelly', {})
        _DIR_EN2CN = {'h': '胜', 'd': '平', 'a': '负'}
        _DIR_CN2EN = {'胜': 'h', '平': 'd', '负': 'a'}
        kelly_rule_applied = False
        
        # 规则一：韦德胜K≥1.0 → 铁排除"胜"
        if bw_k.get('h', 0) >= 1.0 and '胜' in double_pick:
            double_pick.remove('胜')
            kelly_rule_applied = True
        # 规则二：韦德负K≥1.0 → 铁排除"负"
        if bw_k.get('a', 0) >= 1.0 and '负' in double_pick:
            double_pick.remove('负')
            kelly_rule_applied = True
        # 规则三：两家同时≥1.0同方向 → 铁不中
        for d_en, d_cn in _DIR_EN2CN.items():
            if (b365_k.get(d_en, 0) >= 1.0 and bw_k.get(d_en, 0) >= 1.0 
                    and d_cn in double_pick):
                double_pick.remove(d_cn)
                kelly_rule_applied = True
        
        if kelly_rule_applied and len(double_pick) >= 2:
            prediction = f'{double_pick[0]}+{double_pick[1]}'
            reason += ' | Kelly≥1.0反向排除'
        elif kelly_rule_applied and len(double_pick) == 1:
            # 排除后只剩一个方向，保持双选格式（补回概率最高的另一方向）
            pred_type = 'double'
            remaining_dir = double_pick[0]
            # 从prob排序中找第二方向
            other_dirs = [d for d, _ in sorted_probs if d != remaining_dir]
            if other_dirs:
                double_pick.append(other_dirs[0])
                prediction = f'{double_pick[0]}+{double_pick[1]}'
                reason += ' | Kelly≥1.0反向排除'
            else:
                # 降为单选
                pred_type = 'single'
                prediction = double_pick[0]
                double_pick = None
                reason += ' | Kelly≥1.0反向排除→单选'

    # 构建场景相关reason后缀
    if kelly_scenario and kelly_signal and '凯利场景' not in reason and 'V6场景' not in reason:
        reason += f' · [凯利{kelly_scenario}]{kelly_signal}'
    if contradiction:
        reason += ' · ⚠️赔率与凯利矛盾'

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
        "contradiction": contradiction,
        "keBo": kelly_data.get('keBo') if kelly_data else None,
        "keBoType": kelly_data.get('keBoType') if kelly_data else None,
        "v2Tier": v2_tier,
        "v2FavOdds": round(v2_fav_odds, 2) if v2_fav_odds else None,
        "v2DrawOdds": round(v2_draw_odds, 2) if v2_draw_odds else None,
        # V6新增字段
        "v6Scenario": v6_scenario,
        "v6Category": v6_category,
        "favorLevel": favor_level,
        "confidenceLevel": confidence_level,
        "v6HitRate": v6_hit_rate,
        "v6IsFrogJump": v6_is_frog_jump,
        "v6State365": v6_state_365,
        "v6StateWeide": v6_state_weide,
        "v6HasDState": v6_has_d_state,
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
    "nor.2",           # 挪乙
    "swe.1",           # 瑞典超
    "fin.1",           # 芬超
    "fin.2",           # 芬乙
    "den.1",           # 丹甲
    "den.2",           # 丹乙
    "pol.1",           # 波兰甲
    "rou.1",           # 罗甲
    "sui.1",           # 瑞士超
    "sui.2",           # 瑞士挑
    "isl.1",           # 冰岛超
    "irl.1",           # 爱尔兰超
    # ===== 亚洲联赛 =====
    "jpn.1",           # 日职
    "kor.1",           # 韩职
    "kor.2",           # 韩K2联
    # ===== 美洲联赛 =====
    "mls", "usa.1",    # 美职
    "bra.1",           # 巴甲
    "bra.2",           # 巴乙
    "arg.1",           # 阿甲
    # ===== 国际赛事 =====
    "uefa.champions",  # 欧冠
    "uefa.champions.qual",  # 欧冠资格赛
    "uefa.europa",     # 欧联
    "fifa.world",      # 世界杯
    # ===== 其他联赛（北单覆盖） =====
    "other",           # 其他联赛（爱甲、智利甲、墨西超、苏联杯、捷甲等）
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


async def _fetch_espn_scores_for_dates(date_strs: list) -> dict:
    """
    通过 ESPN 公开 API 获取多场比赛结果（免费，无需API Key）
    返回: {league_code: [results]}  按联赛码分组
    每个result: {homeEN, awayEN, homeScore, awayScore, date}
    """
    # ESPN 联赛映射（中文联赛名 → ESPN league slug）
    _ESPN_LEAGUE_MAP = {
        "swe.1": "swe.1",
        "nor.1": "nor.1",
        "bra.1": "bra.1",
        "fin.1": "fin.1",
        "den.1": "den.1",
        "aut.1": "aut.1",
        "ned.1": "ned.1",
        "por.1": "por.1",
        "tur.1": "tur.1",
        "bel.1": "bel.1",
        "gre.1": "gre.1",
        "eng.1": "eng.1",
        "eng.2": "eng.2",
        "esp.1": "esp.1",
        "esp.2": "esp.2",
        "ger.1": "ger.1",
        "ger.2": "ger.2",
        "fra.1": "fra.1",
        "fra.2": "fra.2",
        "ita.1": "ita.1",
        "ita.2": "ita.2",
    }

    results_by_league = {}
    all_results = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; FootballBot/1.0)"}

    for date_str in date_strs:
        # date_str 格式: YYYYMMDD → 转为 YYYY-MM-DD for ESPN? 不，ESPN用YYYYMMDD
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={date_str}"
        try:
            resp = requests.get(url, timeout=15, headers=headers)
            if resp.status_code != 200:
                print(f"[WARN] ESPN {date_str} 返回 HTTP {resp.status_code}")
                continue
            data = resp.json()
            events = data.get("events", [])
            for evt in events:
                comp = evt.get("competitions", [{}])[0]
                competitors = comp.get("competitors", [])
                if len(competitors) < 2:
                    continue
                home = [c for c in competitors if c.get("homeAway") == "home"]
                away = [c for c in competitors if c.get("homeAway") == "away"]
                if not home or not away:
                    continue
                home = home[0]
                away = away[0]
                status_type = comp.get("status", {}).get("type", {})
                status_desc = status_type.get("description", "")
                # 只取已完赛的
                if status_desc not in ("Full Time", "FT", "AET", "AET (FT)"):
                    continue
                h_name = home.get("team", {}).get("displayName", "")
                a_name = away.get("team", {}).get("displayName", "")
                try:
                    h_score = int(home.get("score", 0))
                    a_score = int(away.get("score", 0))
                except (ValueError, TypeError):
                    continue
                if not h_name or not a_name:
                    continue
                result = {
                    "homeEN": h_name,
                    "awayEN": a_name,
                    "homeScore": h_score,
                    "awayScore": a_score,
                    "date": date_str,
                    "source": "espn",
                }
                all_results.append(result)
                # 也按联赛分组
                league_name = evt.get("season", {}).get("type", {}).get("name", "")
                # 尝试映射到 leagueCode
                for lc, eslug in _ESPN_LEAGUE_MAP.items():
                    if eslug.lower() in league_name.lower() or _espn_name_match(league_name, lc):
                        results_by_league.setdefault(lc, []).append(result)
                        break
                else:
                    results_by_league.setdefault("_unmatched", []).append(result)

        except Exception as e:
            print(f"[WARN] ESPN {date_str} 异常: {e}")

    print(f"[INFO] ESPN 获取到 {len(all_results)} 场已完赛结果")
    return results_by_league


def _espn_name_match(espn_league_name: str, league_code: str) -> bool:
    """ESPN联赛名与内部联赛码的模糊匹配"""
    _name_map = {
        "sweden": "swe", "allsvenskan": "swe",
        "norway": "nor", "eliteserien": "nor",
        "brazil": "bra", "serie a": "bra", "serie a brazil": "bra",
        "finland": "fin", "veikkausliiga": "fin",
        "denmark": "den", "superliga": "den",
        "austria": "aut", "bundesliga": "aut",
        "netherlands": "ned", "eredivisie": "ned",
        "portugal": "por", "primeira liga": "por",
        "turkey": "tur", "super lig": "tur",
        "belgium": "bel", "pro league": "bel",
        "greece": "gre", "super league": "gre",
        "england": "eng", "premier league": "eng",
        "spain": "esp", "la liga": "esp",
        "germany": "ger", "bundesliga": "ger",
        "france": "fra", "ligue 1": "fra",
        "italy": "ita", "serie a": "ita",
    }
    name_lower = espn_league_name.lower()
    code_prefix = league_code.split(".")[0]
    for key, prefix in _name_map.items():
        if prefix == code_prefix and key in name_lower:
            return True
    return False


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
    unmapped_leagues = set()  # 不在 Odds API 映射中的联赛，需要 ESPN 覆盖
    for p in to_verify:
        lc = p.get("leagueCode", "")
        if lc == "fifa.world":
            has_world_cup = True
        elif lc in _ODDS_API_LEAGUE_MAP:
            leagues_needed.add(lc)
        elif lc:
            unmapped_leagues.add(lc)

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

    # ESPN 备选方案：对于 Odds API 未覆盖或返回为空的联赛，使用 ESPN 免费 API
    leagues_missing = [lc for lc in leagues_needed if not results_by_source.get(lc)]
    # 也包含不在 Odds API 映射中的联赛（完全由 ESPN 覆盖）
    leagues_missing.extend(unmapped_leagues)
    if leagues_missing:
        # 收集需要查询的日期范围（前后各1天，覆盖跨时区比赛）
        dates_needed = set()
        for p in to_verify:
            pred_date = p.get("date", "")
            if pred_date:
                dates_needed.add(pred_date)
                # 也加上前后一天（跨时区比赛可能在相邻日期）
                try:
                    from datetime import datetime as _dt, timedelta as _td
                    d = _dt.strptime(pred_date[:8], "%Y%m%d")
                    dates_needed.add((d - _td(days=1)).strftime("%Y%m%d"))
                    dates_needed.add((d + _td(days=1)).strftime("%Y%m%d"))
                except:
                    pass

        if dates_needed:
            espn_results = await _fetch_espn_scores_for_dates(sorted(dates_needed))
            # 合并 ESPN 结果到 results_by_source（只补充缺失的联赛）
            for lc in leagues_missing:
                if lc in espn_results:
                    results_by_source[lc] = espn_results[lc]
                    print(f"[INFO] {lc} 结果: {len(espn_results[lc])} 场 (来自ESPN)")
            # 同时收集 _unmatched 到 _unmatched 键，供通配匹配
            if "_unmatched" in espn_results:
                results_by_source.setdefault("_espn_unmatched", []).extend(espn_results["_unmatched"])
                print(f"[INFO] ESPN 未匹配联赛: {len(espn_results['_unmatched'])} 场")

    # 逐条验证
    verified_count = 0
    hit_count = 0
    for p in to_verify:
        lc = p.get("leagueCode", "")
        results = results_by_source.get(lc, [])
        # 如果该联赛没有结果，尝试从 ESPN 未匹配结果中查找
        if not results:
            results = results_by_source.get("_espn_unmatched", [])
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

        # ===== 步骤③：同步赛果到回测表 =====
        if 'backtest_helper' in dir() and backtest_helper:
            try:
                _pdate = p.get("date", "")
                if len(_pdate) >= 8:
                    if "-" in _pdate:
                        _pds = _pdate[:10].replace("-", "")
                    else:
                        _pds = _pdate[:8]
                else:
                    _pds = today_str
                _sdir = os.path.dirname(os.path.abspath(__file__))
                _bdir = os.path.dirname(_sdir)
                backtest_helper.update_match_result(
                    date_str=_pds,
                    home=pred_home,
                    away=pred_away,
                    score_h=hs,
                    score_a=aws,
                    base_dir=_bdir,
                )
            except Exception as _be:
                print(f"[WARN] 回测表赛果同步失败 {pred_home} vs {pred_away}: {_be}")

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
    """加载中国足彩网凯利数据（从zgzcw_kelly_data.json）"""
    today = datetime.now().strftime("%Y%m%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)  # football-predictions/

    # 检查昨天、今天、明天的数据
    all_data = {}
    for date_str in [yesterday, today, tomorrow]:
        path = os.path.join(base_dir, "data", "500com_daily", date_str, "zgzcw_kelly_data.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                matches = data.get("matches", {})
                if isinstance(matches, dict):
                    for mid, mdata in matches.items():
                        all_data[mid] = mdata
                    print(f"[ZGZCW] 加载{date_str}凯利数据: {len(matches)}场比赛")
            except Exception as e:
                print(f"[ZGZCW] 加载{date_str}数据异常: {e}")

    if all_data:
        return {"matches": all_data}
    print("[ZGZCW] 未找到zgzcw凯利数据")
    return {}


def _extract_kelly_companies_zgzcw(companies: dict) -> dict:
    """从zgzcw公司数据中提取Bet365和韦德的Kelly数据
    输入: {"weide": {"kelly": [h,d,a], "payout": p, ...}, "bet365": {...}, ...}
    输出: {"bet365": {"kelly_h": x, "kelly_d": y, "kelly_a": z, "payout": p}, "weide": {...}}
    """
    result = {}
    # zgzcw公司key映射到引擎key
    _ZGZCW_KEY_MAP = {
        "bet365": "bet365",
        "weide": "weide",
        "libo": "ladbrokes",  # 立博
    }
    for zgzcw_key, engine_key in _ZGZCW_KEY_MAP.items():
        rec = companies.get(zgzcw_key)
        if not rec:
            continue
        kelly_arr = rec.get("kelly", [])
        payout = rec.get("payout", 0)
        if len(kelly_arr) >= 3 and payout > 0:
            result[engine_key] = {
                "kelly_h": float(kelly_arr[0]) / 100.0 if kelly_arr[0] > 1 else float(kelly_arr[0]),
                "kelly_d": float(kelly_arr[1]) / 100.0 if kelly_arr[1] > 1 else float(kelly_arr[1]),
                "kelly_a": float(kelly_arr[2]) / 100.0 if kelly_arr[2] > 1 else float(kelly_arr[2]),
                "payout": float(payout),
            }
        # 如果kelly值看起来是百分比形式(>1)，需要除以100
        # 否则已经是小数形式
    return result

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

        schedule = json.loads(schedule_content, strict=False)
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

        # ===== 2.1 步骤①：将赛程写入回测表 =====
        if backtest_helper:
            try:
                _script_dir = os.path.dirname(os.path.abspath(__file__))
                _base_dir = os.path.dirname(_script_dir)
                # 按比赛日期分组写入
                from datetime import datetime as _dt2
                _matches_by_date = {}
                for _m in all_matches:
                    _mdate = _m.get("date", "")
                    if len(_mdate) >= 8:
                        if "-" in _mdate:
                            _ds = _mdate[:10].replace("-", "")
                        else:
                            _ds = _mdate[:8]
                    else:
                        _ds = today_str if 'today_str' in dir() else _dt2.now().strftime("%Y%m%d")
                    if _ds not in _matches_by_date:
                        _matches_by_date[_ds] = []
                    _matches_by_date[_ds].append(_m)
                _total_added = 0
                for _ds, _mlist in _matches_by_date.items():
                    _r = backtest_helper.upsert_schedule_records(_mlist, _ds, base_dir=_base_dir)
                    _total_added += _r["added"]
                if _total_added > 0:
                    print(f"[BACKTEST] 步骤①赛程写入完成，共新增{_total_added}场到回测表")
            except Exception as _e:
                print(f"[WARN] 回测表赛程写入失败(不影响主流程): {_e}")

        # ===== 2.5 补充 schedule.json 中缺失的联赛赛程（从 Odds API 获取） =====
        # [已禁用] Odds API Key过期(401)，ESPN被屏蔽(403)。赛程数据以zgzcw+schedule.json为准。
        schedule_leagues = set(m.get("league", "") for m in all_matches)
        missing_leagues = []  # disabled: Odds API key expired
        if False:  # was: if missing_leagues:
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
                # 支持 YYYYMMDD 和 YYYY-MM-DDTHH:MM 格式
                if "-" in match_date_raw:
                    match_date_str = match_date_raw[:10].replace("-", "")
                else:
                    match_date_str = match_date_raw[:8]
                if match_date_str not in allowed_predict_dates:
                    skipped_future += 1
                    continue
            upcoming.append(m)
        
        if skipped_future > 0:
            print(f"[INFO] 跳过远期比赛: {skipped_future} 场（只预测{today_str}~{tomorrow_str}）")

        print(f"[INFO] 未开赛比赛: {len(upcoming)} 场（已过滤非竞彩联赛: {skipped_leagues}）")

        # ===== 6.5 获取多公司赔率（用于凯利场景分析） =====
        # [已禁用] Odds API Key过期(401)，改用zgzcw_kelly和beidan_odds
        print("[INFO] Odds API已禁用(Key过期)，使用zgzcw/beidan赔率替代")
        odds_api_data = {}  # disabled: Odds API key expired
        total_odds_events = 0
        print(f"[OK] 多公司赔率: 已跳过Odds API")
        
        # ===== 6.5.1 从500com_daily加载凯利数据（补充数据源） =====
        print("[INFO] 从500com_daily加载凯利数据...")
        kelly_500com_data = _load_kelly_500com_data()
        if kelly_500com_data:
            print(f"[OK] 500com凯利数据: {len(kelly_500com_data.get('matches', []))} 场比赛")
        
        # ===== 6.5.2 从zgzcw_kelly加载凯利数据（补充数据源） =====
        print("[INFO] 从zgzcw_kelly加载凯利数据...")
        kelly_zgzcw_data = _load_kelly_zgzcw_data()
        if kelly_zgzcw_data:
            _zgzcw_matches = kelly_zgzcw_data.get('matches', {})
            print(f"[OK] zgzcw凯利数据: {len(_zgzcw_matches)} 场比赛")

        # 构建比赛匹配索引：(homeEN_norm, awayEN_norm) -> odds_event
        odds_match_index = {}
        for lc, events in odds_api_data.items():
            for evt in events:
                key = (_normalize_name(evt["homeEN"]), _normalize_name(evt["awayEN"]))
                odds_match_index[key] = evt

        # 构建 schedule 英文名映射，用于匹配 The Odds API 队名
        schedule_en_map_for_odds = _build_schedule_en_map(all_matches)

        # ===== 6.5.3 加载北单赔率数据（第4级fallback） =====
        print("[INFO] 加载北单赔率数据...")
        beidan_odds = _load_beidan_odds()
        if beidan_odds:
            _beidan_upcoming = [m for m in beidan_odds if m.get('status') == 'upcoming']
            print(f"[OK] 北单赔率: {len(beidan_odds)} 场比赛 ({len(_beidan_upcoming)} 场未开赛)")
            # 按联赛统计
            _beidan_leagues = set(m.get('league', '') for m in beidan_odds)
            print(f"[BEIDAN] 覆盖联赛: {', '.join(sorted(_beidan_leagues))}")

        # ===== 6.5.4 加载zgzcw实时赔率数据（第5级fallback） =====
        print("[INFO] 加载zgzcw实时赔率数据...")
        zgzcw_live_odds = _load_zgzcw_live_odds()
        if zgzcw_live_odds:
            print(f"[OK] zgzcw实时赔率: {len(zgzcw_live_odds)} 场比赛")

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
            match_odds_365 = None   # V6: bet365赔率（强队判定）
            match_macau_data = None # V6: 澳门赔率数据（蛙跳检测）
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
                    kelly_data = calc_kelly_scenario(_odds_kelly, _base_p, odds={'w': _w2, 'd': _d2, 'l': _l2} if _w2 and _d2 and _l2 else None)
                # V6: 提取bet365赔率用于强队判定
                if matched_odds_evt.get("bookmakers", {}).get("bet365"):
                    _b365_odds = matched_odds_evt["bookmakers"]["bet365"]
                    match_odds_365 = {"w": _b365_odds.get("home", 0), "d": _b365_odds.get("draw", 0), "l": _b365_odds.get("away", 0)}
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
                        kelly_data = calc_kelly_scenario(_kelly_companies, _base_p3, odds={'w': _w3, 'd': _d3, 'l': _l3} if _w3 and _d3 and _l3 else None)
                        # V6: 提取bet365赔率
                        if not match_odds_365:
                            _b365_rec = matched_500com.get("companies", {}).get("Bet365", [])
                            if _b365_rec:
                                _b365_r = _b365_rec[0] if isinstance(_b365_rec, list) else _b365_rec
                                _bw = _b365_r.get("odds_h", 0)
                                _bd = _b365_r.get("odds_d", 0)
                                _bl = _b365_r.get("odds_a", 0)
                                if _bw > 1 and _bd > 1 and _bl > 1:
                                    match_odds_365 = {"w": _bw, "d": _bd, "l": _bl}
                        if kelly_data and kelly_data.get("scenario"):
                            disp_tag = f" 离散度{round(kelly_data.get('dispersion',0),3)}" if kelly_data.get('dispersion') else ""
                            skip_tag_k = " [SKIP]" if kelly_data.get('skip') else ""
                            print(f"[KELLY-500COM] {_home} vs {_away}: 场景{kelly_data['scenario']} {kelly_data.get('signal', '')}{disp_tag}{skip_tag_k}")

            # ===== zgzcw 凯利数据 fallback =====
            # 当 Odds API 和500com都无数据时，使用zgzcw抓取的凯利数据
            if not kelly_data and kelly_zgzcw_data:
                zgzcw_matches = kelly_zgzcw_data.get("matches", {})
                # 优先按match_id精确匹配
                matched_zgzcw = zgzcw_matches.get(match_id)
                if not matched_zgzcw:
                    # 模糊匹配：按队名
                    for mid_z, mz in zgzcw_matches.items():
                        mz_name = mz.get("match_name", "")
                        mz_parts = mz_name.split(" vs ")
                        if len(mz_parts) == 2:
                            mz_home, mz_away = mz_parts[0].strip(), mz_parts[1].strip()
                            # 简单匹配：队名包含关系
                            if (_home in mz_home or mz_home in _home) and (_away in mz_away or mz_away in _away):
                                matched_zgzcw = mz
                                break
                            if (_home in mz_away or mz_away in _home) and (_away in mz_home or mz_home in _away):
                                matched_zgzcw = mz
                                break
                if matched_zgzcw:
                    _kelly_companies_z = _extract_kelly_companies_zgzcw(matched_zgzcw.get("companies", {}))
                    if _kelly_companies_z.get('bet365') and _kelly_companies_z.get('weide'):
                        # 计算基础概率
                        _w4, _d4, _l4, _, _ = normalize_odds(m.get("odds", {}))
                        if _w4 and _d4 and _l4:
                            _bp4 = calc_kelly_probs(_w4, _d4, _l4)
                            _base_p4 = {'hf': _bp4['胜'], 'df': _bp4['平'], 'af': _bp4['负']}
                        else:
                            # 尝试从zgzcw赔率计算
                            _z_b365 = matched_zgzcw.get("companies", {}).get("bet365", {})
                            _z_latest = _z_b365.get("latest_odds", [])
                            if len(_z_latest) >= 3 and all(x > 1 for x in _z_latest):
                                _w4, _d4, _l4 = _z_latest[0], _z_latest[1], _z_latest[2]
                                _bp4 = calc_kelly_probs(_w4, _d4, _l4)
                                _base_p4 = {'hf': _bp4['胜'], 'df': _bp4['平'], 'af': _bp4['负']}
                                # 同时把赔率写入match，用于后续预测
                                if not m.get("odds"):
                                    m["odds"] = {"source": "zgzcw", "w": _w4, "d": _d4, "l": _l4}
                            else:
                                _ep4 = calc_elo_probs(get_team_strength(teams, _home), get_team_strength(teams, _away))
                                _base_p4 = {'hf': _ep4['胜'], 'df': _ep4['平'], 'af': _ep4['负']}
                        kelly_data = calc_kelly_scenario(_kelly_companies_z, _base_p4, odds={'w': _w4, 'd': _d4, 'l': _l4} if _w4 and _d4 and _l4 else None)
                        # V6: 从zgzcw提取bet365赔率和澳门赔率
                        if not match_odds_365:
                            _z_b365_odds = matched_zgzcw.get("companies", {}).get("bet365", {})
                            _z_latest_odds = _z_b365_odds.get("latest_odds", [])
                            if len(_z_latest_odds) >= 3 and all(x > 1 for x in _z_latest_odds):
                                match_odds_365 = {"w": _z_latest_odds[0], "d": _z_latest_odds[1], "l": _z_latest_odds[2]}
                        # V6: 提取澳门亚盘数据（蛙跳检测基于亚盘让球盘，不是欧赔）
                        _z_macau = matched_zgzcw.get("companies", {}).get("macau", {})
                        _z_init_val = _z_macau.get("initial_handicap_val")
                        _z_latest_val = _z_macau.get("latest_handicap_val")
                        if _z_init_val is not None and _z_latest_val is not None:
                            match_macau_data = {
                                "initial_handicap_val": _z_init_val,
                                "latest_handicap_val": _z_latest_val,
                                "initial_handicap_str": _z_macau.get("initial_handicap_str", ""),
                                "latest_handicap_str": _z_macau.get("latest_handicap_str", ""),
                                "handicap_path": _z_macau.get("handicap_path"),
                            }
                        if kelly_data and kelly_data.get("scenario"):
                            disp_tag = f" 离散度{round(kelly_data.get('dispersion',0),3)}" if kelly_data.get('dispersion') else ""
                            skip_tag_k = " [SKIP]" if kelly_data.get('skip') else ""
                            print(f"[KELLY-ZGZCW] {_home} vs {_away}: 场景{kelly_data['scenario']} {kelly_data.get('signal', '')}{disp_tag}{skip_tag_k}")

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

            # ===== 北单赔率 fallback（第4级） =====
            # 当 Odds API / 500com / zgzcw / 竞彩网 均无数据时，
            # 从北单投注页面获取欧赔作为最后备选
            # 北单覆盖竞彩以外的联赛（罗甲、波兰甲、丹麦甲/超、瑞士超/挑、
            # 爱甲/爱超、冰岛超、芬甲/超、智利甲、墨西超、巴西甲/乙、阿甲、捷甲等）
            if not m.get("odds") and beidan_odds:
                beidan_match = _match_beidan_odds(_home, _away, beidan_odds)
                if beidan_match:
                    odds_data = {
                        "source": "北单",
                        "w": beidan_match["w"],
                        "d": beidan_match["d"],
                        "l": beidan_match["l"],
                    }
                    m["odds"] = odds_data
                    print(f"[FALLBACK-BEIDAN] {_home} vs {_away}: 北单欧赔 {beidan_match['w']:.2f}/{beidan_match['d']:.2f}/{beidan_match['l']:.2f}")

            # ===== zgzcw实时赔率 fallback（第5级） =====
            if not m.get("odds") and zgzcw_live_odds:
                zlive_match = _match_zgzcw_live_odds(_home, _away, zgzcw_live_odds)
                if zlive_match:
                    odds_data = {
                        "source": "zgzcw_live",
                        "w": zlive_match["w"],
                        "d": zlive_match["d"],
                        "l": zlive_match["l"],
                    }
                    m["odds"] = odds_data
                    print(f"[FALLBACK-ZGZCW] {_home} vs {_away}: zgzcw实时赔率 {zlive_match['w']:.2f}/{zlive_match['d']:.2f}/{zlive_match['l']:.2f}")

            # ===== 实时数据铁律：Kelly数据缺失检查 =====
            _no_kelly = kelly_data is None
            if _no_kelly:
                if existing and not existing.get("verified") and not existing.get("noKellyData"):
                    # 情况A：已有旧预测且无实时Kelly数据 → 沿用上次预测
                    keep_count += 1
                    # 即使沿用旧预测，也要更新赔率数据（如果schedule中有赔率但旧记录没有）
                    if m.get("odds") and not existing.get("odds"):
                        pred_map[match_id]["odds"] = m["odds"]
                        pred_map[match_id]["odds_source"] = m["odds"].get("source", "unknown")
                        pred_map[match_id]["hasOdds"] = True
                    print(f"[KEEP-PREV] {_home} vs {_away}: 无实时Kelly数据，沿用上次预测")
                    continue
                elif existing and existing.get("noKellyData"):
                    # 情况A2：已有占位记录，仍拉不到 → 保持占位不变，持续重试
                    keep_count += 1
                    # 即使保持占位，也要更新赔率数据
                    if m.get("odds") and not existing.get("odds"):
                        pred_map[match_id]["odds"] = m["odds"]
                        pred_map[match_id]["odds_source"] = m["odds"].get("source", "unknown")
                        pred_map[match_id]["hasOdds"] = True
                    print(f"[KEEP-PENDING] {_home} vs {_away}: 仍无Kelly数据，保持等待")
                    continue
                else:
                    # 情况B：首次无Kelly数据 → 创建占位记录，不生成预测
                    print(f"[NO-KELLY] {_home} vs {_away}: 无Kelly数据，创建占位等待")
                    _placeholder = {
                        "matchId": match_id,
                        "home": _home,
                        "away": _away,
                        "league": m.get("leagueShort", m.get("leagueName", "")),
                        "leagueCode": m.get("league", ""),
                        "date": date_iso,
                        "matchTime": format_match_time(m),
                        "prediction": "",
                        "type": "pending",
                        "confidence": 0,
                        "skip": True,
                        "skipReason": "该场比赛预测未获得实时数据，谨慎参考",
                        "reason": "等待实时Kelly数据",
                        "doublePick": [],
                        "stars": 0,
                        "hasOdds": bool(m.get("odds")),
                        "spread": 0,
                        "handicapDir": None,
                        "noKellyData": True,
                        "verified": False,
                        "actualResult": None,
                        "hit": None,
                    }
                    if m.get("odds"):
                        _placeholder["odds"] = m["odds"]
                        _placeholder["odds_source"] = m["odds"].get("source", "unknown")
                    new_count += 1
                    pred_map[match_id] = _placeholder
                    continue

            # 生成新预测（有Kelly数据时才执行）
            pred = predict_match(m, teams, kelly_data=kelly_data, odds_365=match_odds_365, macau_data=match_macau_data)

            # 构建预测记录
            record = {
                "matchId": match_id,
                "home": _home,
                "away": _away,
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
                "keBo": pred.get("keBo"),
                "keBoType": pred.get("keBoType"),
                "v2Tier": pred.get("v2Tier"),
                "v2FavOdds": pred.get("v2FavOdds"),
                "v2DrawOdds": pred.get("v2DrawOdds"),
                "v6Scenario": pred.get("v6Scenario"),
                "v6Category": pred.get("v6Category"),
                "favorLevel": pred.get("favorLevel"),
                "confidenceLevel": pred.get("confidenceLevel"),
                "v6HitRate": pred.get("v6HitRate"),
                "v6IsFrogJump": pred.get("v6IsFrogJump"),
                "v6State365": pred.get("v6State365"),
                "v6StateWeide": pred.get("v6StateWeide"),
                "v6HasDState": pred.get("v6HasDState"),
                "noKellyData": False,
                "verified": False,
                "actualResult": None,
                "hit": None,
            }

            if existing and not existing.get("verified"):
                # 更新未验证的预测（可能从占位升级为正式预测）
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
                pred_map[match_id]["hasOdds"] = True  # 确保hasOdds与实际数据一致

            # ===== 步骤②：将Kelly场景分类和预测回填回测表 =====
            if backtest_helper and not pred.get("skip", False) and pred.get("v6Scenario"):
                try:
                    _script_dir2 = os.path.dirname(os.path.abspath(__file__))
                    _base_dir2 = os.path.dirname(_script_dir2)
                    # 确定比赛日期
                    _mdate2 = m.get("date", "")
                    if len(_mdate2) >= 8:
                        if "-" in _mdate2:
                            _ds2 = _mdate2[:10].replace("-", "")
                        else:
                            _ds2 = _mdate2[:8]
                    else:
                        _ds2 = today_str
                    # 提取Kelly值
                    _k365 = None
                    _kwd = None
                    if kelly_data:
                        _bk = kelly_data.get("bet365_kelly")
                        _wk = kelly_data.get("weide_kelly")
                        if _bk:
                            _k365 = [round(_bk.get("h", 0), 4), round(_bk.get("d", 0), 4), round(_bk.get("a", 0), 4)]
                        if _wk:
                            _kwd = [round(_wk.get("h", 0), 4), round(_wk.get("d", 0), 4), round(_wk.get("a", 0), 4)]
                    # 提取365赔率
                    _o365 = None
                    if match_odds_365:
                        _o365 = [match_odds_365.get("w", 0), match_odds_365.get("d", 0), match_odds_365.get("l", 0)]
                    backtest_helper.update_prediction_record(
                        date_str=_ds2,
                        home=_home,
                        away=_away,
                        scenario=pred.get("v6Scenario"),
                        sig_365=pred.get("v6State365"),
                        sig_weide=pred.get("v6StateWeide"),
                        is_home_strong=(match_odds_365 is not None and match_odds_365.get("w", 0) <= match_odds_365.get("l", 0)) if match_odds_365 else None,
                        prediction=pred.get("prediction"),
                        pred_type=pred.get("type"),
                        kelly_365=_k365,
                        kelly_weide=_kwd,
                        odds_365=_o365,
                        locked_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        base_dir=_base_dir2,
                    )
                except Exception as _e:
                    print(f"[WARN] 回测表预测回填失败 {_home} vs {_away}: {_e}")

        # ===== 8. 组装最终预测列表 =====
        # 只保留昨天、今天、明天的预测（不提前预测太远，不保留太久）
        allowed_display_dates = {yesterday_str, today_str, tomorrow_str}
        final_predictions = []

        # 已验证记录永久保留（不按日期过滤），确保历史战绩可追溯
        verified_preds = [p for p in existing_predictions if p.get("verified")]
        verified_preds.sort(key=lambda x: x.get("date", ""))
        final_predictions.extend(verified_preds)
        print(f"[DEBUG] 已验证旧预测: {len(verified_preds)} 条（永久保留）")

        # 未验证记录保留3天窗口（昨天/今天/明天）
        unverified_preds = [p for mid, p in pred_map.items() if not p.get("verified")]
        unverified_before_filter = len(unverified_preds)
        unverified_preds = [p for p in unverified_preds if (_d:=p.get("date", ""), _d[:10].replace("-","") if "-" in _d else _d[:8])[1] in allowed_display_dates]
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

        # ===== 8.1 赔率覆盖率监控（仅统计今天和明天的预测） =====
        _no_odds_matches = []
        today_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
        tomorrow_str = (datetime.now(timezone(timedelta(hours=8))) + timedelta(days=1)).strftime("%Y%m%d")
        allowed_dates = {today_str, tomorrow_str}
        
        for p in final_predictions:
            if not p.get("hasOdds") and not p.get("verified"):
                # 只统计今天和明天的预测，不算旧数据
                p_date = p.get("date", "")
                if len(p_date) >= 8:
                    if "-" in p_date:
                        p_date_str = p_date[:10].replace("-", "")
                    else:
                        p_date_str = p_date[:8]
                    if p_date_str[:8] in allowed_dates:
                        _no_odds_matches.append(f"{p.get('home','')} vs {p.get('away','')}")
        if _no_odds_matches:
            print(f"\n[WARNING] 赔率缺失！{len(_no_odds_matches)} 场比赛无赔率数据（将退化为纯Elo模型，预测可靠性大幅降低）:")
            for m_name in _no_odds_matches:
                print(f"  ⚠ {m_name}")
            print(f"[HINT] 可能原因: Odds API配额耗尽 / 500com未抓取到 / 竞彩网无数据。请检查赔率数据源。")
        else:
            print(f"[OK] 赔率覆盖率: {len(final_predictions)}/{len(final_predictions)} 场全部有赔率")

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

        # ===== 10.5 数据资产归档 =====
        try:
            import shutil as _shutil
            _archive_dir = os.path.join(base_dir, "data", "archive")
            os.makedirs(_archive_dir, exist_ok=True)
            from datetime import datetime as _dt
            _ts = _dt.now().strftime('%Y%m%d_%H%M%S')
            _snapshot_path = os.path.join(_archive_dir, f"ai-predictions_{_ts}.json")
            _shutil.copy2(local_path, _snapshot_path)
            print(f"  📦 快照归档: ai-predictions_{_ts}.json")
        except Exception as _e:
            print(f"  ⚠️ 快照归档失败(不影响主流程): {_e}")

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
                    # V2策略标签
                    v2_tag = ""
                    v2t = p.get("v2Tier")
                    if v2t == 'S+':
                        v2_tag = " 🔥V2精选"
                    elif v2t == 'S':
                        v2_tag = " 🏆V2精选"
                    elif v2t == 'A':
                        v2_tag = " ✅V2"
                    # V6标签
                    v6_tag = ""
                    v6s = p.get("v6Scenario")
                    v6fl = p.get("favorLevel")
                    v6cl = p.get("confidenceLevel")
                    v6hr = p.get("v6HitRate")
                    v6frog = p.get("v6IsFrogJump")
                    if v6s:
                        if v6frog:
                            v6_tag = f" 🐸蛙跳|{v6fl}|{v6cl}"
                        else:
                            v6_tag = f" 场景{v6s}|{v6fl}|{v6cl}"
                            if v6hr is not None:
                                v6_tag += f"|{v6hr:.0f}%"
                    conf = p.get("confidence", 0)
                    pred_text = p.get("prediction", "")
                    pred_type = "单选" if p.get("type") == "single" else "双选"

                    line = (
                        f"  {p.get('home', '')} vs {p.get('away', '')}\n"
                        f"    {pred_type} {pred_text} | 置信度{conf}% | {stars_str}{v6_tag}{kelly_tag}{disp_tag}{unique_tag}{reverse_tag}{v2_tag}{skip_tag}\n"
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
        # 赔率覆盖率告警
        _no_odds_count = len(_no_odds_matches)
        # 只统计今天和明天的未验证预测
        _today_unverified = []
        for p in final_predictions:
            if not p.get("verified"):
                p_date = p.get("date", "")
                if len(p_date) >= 8:
                    if "-" in p_date:
                        p_date_str = p_date[:10].replace("-", "")
                    else:
                        p_date_str = p_date[:8]
                    if p_date_str[:8] in allowed_dates:
                        _today_unverified.append(p)
        _total_unverified = len(_today_unverified)
        if _no_odds_count > 0:
            stats_info += f"\n⚠️ 赔率缺失: {_no_odds_count}/{_total_unverified} 场（降级为纯Elo，可靠性低）"
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
                # V6标签（看好等级|信心等级|场景|命中率）
                v6_info = ""
                v6s = p.get("v6Scenario")
                v6fl = p.get("favorLevel")
                v6cl = p.get("confidenceLevel")
                v6hr = p.get("v6HitRate")
                v6frog = p.get("v6IsFrogJump")
                v6d = p.get("v6HasDState")
                if v6s:
                    d_tag = "含D " if v6d else ""
                    if v6frog:
                        v6_info = f"（{d_tag}{v6fl} | {v6cl} | 🐸蛙跳）"
                    else:
                        hr_str = f"历史{v6hr:.0f}%" if v6hr is not None else ""
                        v6_info = f"（{d_tag}{v6fl} | {v6cl} | 场景{v6s} | {hr_str}）"
                msg_parts.append(
                    f"• {p['home']} vs {p['away']}: {p['prediction']} "
                    f"{v6_info}"
                    f"({p['confidence']}% {stars_str}{skip_tag})"
                )
            if len(today_preds) > 10:
                msg_parts.append(f"...还有 {len(today_preds) - 10} 场")

            # V2策略统计
            v2_preds = [p for p in today_preds if p.get("v2Tier") and not p.get("skip")]
            v2_sp = [p for p in v2_preds if p.get("v2Tier") == 'S+']
            v2_s = [p for p in v2_preds if p.get("v2Tier") == 'S']
            v2_a = [p for p in v2_preds if p.get("v2Tier") == 'A']
            if v2_preds:
                msg_parts.append(f"\n🎯 V2策略命中 {len(v2_preds)} 场（精选{len(v2_sp)}+{len(v2_s)}+常规{len(v2_a)}）")
                for p in v2_sp[:3]:
                    msg_parts.append(f"  🔥 {p['home']} vs {p['away']}: {p['prediction']} (平赔{p.get('v2DrawOdds','')}/强赔{p.get('v2FavOdds','')})")
                for p in v2_s[:3]:
                    msg_parts.append(f"  🏆 {p['home']} vs {p['away']}: {p['prediction']} (平赔{p.get('v2DrawOdds','')}/强赔{p.get('v2FavOdds','')})")

            # 推荐重点
            recommended = [p for p in today_preds if not p.get("skip") and p.get("stars", 0) >= 3]
            if recommended:
                msg_parts.append(f"\n🎯 重点推荐 ({len(recommended)} 场):")
                for p in recommended[:5]:
                    stars_str = star_symbols.get(p.get("stars", 1), "☆")
                    v6_rec = ""
                    _v6s = p.get("v6Scenario")
                    _v6fl = p.get("favorLevel")
                    if _v6s:
                        v6_rec = f" [{_v6fl}/场景{_v6s}]"
                    msg_parts.append(f"  ★ {p['home']} vs {p['away']}: {p['prediction']} ({p['confidence']}% {stars_str}{v6_rec})")

            msg_parts.append(f"\n历史命中率: {hit_rate}% | GitHub更新: {'✅' if push_success else '❌'}")
            
            # 赔率缺失告警（写入用户消息）
            if _no_odds_count > 0:
                msg_parts.append(f"\n⚠️ {len(_no_odds_matches)} 场无赔率（Elo降级）: {', '.join(_no_odds_matches[:3])}" + ("..." if len(_no_odds_matches) > 3 else ""))
            
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
                "no_odds_count": _no_odds_count,
                "no_odds_matches": _no_odds_matches if _no_odds_count > 0 else [],
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



def _load_zgzcw_live_odds() -> list:
    """加载zgzcw实时赔率数据（由浏览器抓取zgzcw页面生成）
    
    数据格式: [{league, time, status, home, away, score, odds_win, odds_draw, odds_loss}]
    覆盖290场北单比赛，含完整欧赔三值。
    """
    today = datetime.now().strftime("%Y%m%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)

    all_matches = []
    for date_str in [yesterday, today, tomorrow]:
        path = os.path.join(base_dir, "data", "500com_daily", date_str, "zgzcw_live_odds.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    all_matches.extend(data)
                    print(f"[ZGZCW-LIVE] 加载{date_str}实时赔率: {len(data)}场比赛")
            except Exception as e:
                print(f"[ZGZCW-LIVE] 加载{date_str}数据异常: {e}")

    if all_matches:
        seen = set()
        unique = []
        for m in all_matches:
            key = (m.get("home", ""), m.get("away", ""))
            if key not in seen:
                seen.add(key)
                unique.append(m)
        return unique
    print("[ZGZCW-LIVE] 未找到实时赔率数据")
    return []


def _match_zgzcw_live_odds(home_cn: str, away_cn: str, zgzcw_matches: list) -> dict:
    """在zgzcw实时赔率中查找匹配的比赛"""
    if not zgzcw_matches or not home_cn or not away_cn:
        return None
    # 精确匹配
    for m in zgzcw_matches:
        mh = m.get("home", "").strip()
        ma = m.get("away", "").strip()
        if mh == home_cn and ma == away_cn:
            return {"w": m["odds_win"], "d": m["odds_draw"], "l": m["odds_loss"]}
    # 包含匹配
    for m in zgzcw_matches:
        mh = m.get("home", "").strip()
        ma = m.get("away", "").strip()
        if (home_cn in mh or mh in home_cn) and (away_cn in ma or ma in away_cn):
            return {"w": m["odds_win"], "d": m["odds_draw"], "l": m["odds_loss"]}
        if (home_cn in ma or ma in home_cn) and (away_cn in mh or mh in away_cn):
            return {"w": m["odds_win"], "d": m["odds_draw"], "l": m["odds_loss"]}
    return None


def _load_beidan_odds() -> list:
    """加载北单赔率数据（由scrape_beidan_odds.py生成）
    
    北单赔率覆盖竞彩以外的联赛（韩K2联、罗甲、波兰甲、丹麦甲/超、
    瑞士超/挑、爱甲/爱超、冰岛超、芬甲/超、智利甲、墨西超、
    巴西甲/乙、阿甲、捷甲等），作为第4级fallback数据源。
    
    Returns:
        list of dict: [{beidan_id, league, home, away, odds:{w,d,l}, ...}]
    """
    today = datetime.now().strftime("%Y%m%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)  # football-predictions/

    all_matches = []
    for date_str in [yesterday, today, tomorrow]:
        path = os.path.join(base_dir, "data", "500com_daily", date_str, "beidan_odds.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                matches = data.get("matches", [])
                if isinstance(matches, list):
                    all_matches.extend(matches)
                    print(f"[BEIDAN] 加载{date_str}北单赔率: {len(matches)}场比赛")
            except Exception as e:
                print(f"[BEIDAN] 加载{date_str}数据异常: {e}")

    if all_matches:
        # 去重：同一场比赛可能出现在多个日期文件中
        seen = set()
        unique = []
        for m in all_matches:
            key = (m.get("home", ""), m.get("away", ""), m.get("match_time", ""))
            if key not in seen:
                seen.add(key)
                unique.append(m)
        if len(unique) < len(all_matches):
            print(f"[BEIDAN] 去重: {len(all_matches)} → {len(unique)} 场")
        return unique
    print("[BEIDAN] 未找到北单赔率数据")
    return []


def _match_beidan_odds(home_cn: str, away_cn: str, beidan_matches: list) -> dict:
    """在北单赔率数据中查找匹配的比赛赔率
    
    匹配策略：
    1. 精确匹配（去除空格后完全相同）
    2. 包含匹配（一方包含另一方，处理简称/全称差异）
    
    Args:
        home_cn: 主队中文名
        away_cn: 客队中文名
        beidan_matches: 北单比赛列表
        
    Returns:
        dict {"w": float, "d": float, "l": float} or None
    """
    if not beidan_matches or not home_cn or not away_cn:
        return None

    # 北单队名别名映射（北单简称 → schedule标准名）
    # 仅包含名称差异显著的映射，同名映射无需列出
    # 模糊匹配会自动处理子串包含关系（如"比尔森"⊂"比尔森胜利"）
    _BEIDAN_ALIAS = {
        # === 简称/缩写 → 全称 ===
        "萨斯菲": "萨斯菲尔德",
        "竞技": "竞技俱乐部",
        "飓风": "飓风队",
        "普拉腾斯": "普拉滕斯",
        "图库曼": "图库曼竞技",
        "意大利人": "奥达斯",
        "墨美洲": "美洲队",
        "全北现代": "全北",
        # === 音译差异 ===
        "费特斯塔": "腓特烈斯塔",
        "塞纳乔琪": "塞那乔其",
        "KS莫摩斯": "莫玛斯",
        "AB格莱萨": "格莱萨克",
        "奥尔格里": "奥雷布洛",
        "希勒勒": "赫勒鲁普",
        "瑞普斯威尔": "拉波斯维尔",
        "奥特鲁加": "阿斯特拉",
        "佩特罗鲁": "彼得罗鲁",
        "华沙军团": "历基亚",
        "费恩哈普": "芬哈普斯",
        "圣帕特里": "圣帕特里克",
        "韦尔": "瓦杜兹",
        "伊韦尔东": "伊东",
        "亚布洛": "亚布洛内茨",
        "维德祖罗兹": "鲁奇",
        "霍森斯": "贺森斯",
        "KF奥斯陆": "奥德KFUM",
        "桑纳菲": "桑德菲杰",
        "萨普斯堡": "萨普斯堡08",
        "贝雷达比": "贝雷达比历克",
        "博托沙尼": "波图森尼",
        "KA阿古雷": "阿古雷利",
        "戈亚尼亚": "戈亚尼亚竞技",
        "拉卡莱拉联": "拉卡莱拉",
        "康塞普森": "大学康塞普森",
        "纽夫莱": "纽布莱斯",
        "圣贝纳多": "圣本托",
        "克里丘马": "克里西乌马",
        "帕梅拉斯": "帕尔梅拉斯",
        "拉普大学": "拉普拉塔大学",
        "里奥夸托": "里奥夸尔托",
        "盖斯": "加尔斯",
        "布鲁马波": "布洛马波卡纳",
        "什切青": "波尔什切青",
        "比亚韦": "比亚韦斯托克",
        "扎布矿工": "扎布热矿工",
        "琴斯托霍": "琴斯托霍瓦",
        "弗雷西亚": "弗雷德里西亚",
        "克里斯蒂": "克里斯蒂安松",
        "斯特罗姆": "斯特罗姆加斯特",
        "国际图尔": "国际图尔库",
        "布迪纳摩": "布加勒斯特迪纳摩",
        "圣格塞普西": "圣格奥尔基",
        "沃伦塔利": "沃伦塔利",
        "科布漫步": "科克城",
        "戈尔韦联": "戈尔韦",
        "摩顿": "格里诺克",
        "斯坦豪斯": "斯莱戈",
        "斯特勒门": "斯托罗门",
        "松达尔": "桑德菲杰",
        "桑德尼斯": "桑德纳",
        "奥萨尼": "奥桑内",
    }

    def _alias(name: str) -> str:
        return _BEIDAN_ALIAS.get(name, name)

    # 精确匹配
    for bm in beidan_matches:
        b_home = bm.get("home", "")
        b_away = bm.get("away", "")
        odds = bm.get("odds")
        if not odds or not odds.get("w") or not odds.get("d") or not odds.get("l"):
            continue

        # 正序匹配（含别名）
        if (_alias(b_home) == home_cn or b_home == home_cn) and \
           (_alias(b_away) == away_cn or b_away == away_cn):
            return odds

        # 倒序匹配
        if (_alias(b_home) == away_cn or b_home == away_cn) and \
           (_alias(b_away) == home_cn or b_away == home_cn):
            return odds

    # 模糊匹配（子串包含）
    best_match = None
    best_score = 0
    for bm in beidan_matches:
        b_home = bm.get("home", "")
        b_away = bm.get("away", "")
        odds = bm.get("odds")
        if not odds or not odds.get("w") or not odds.get("d") or not odds.get("l"):
            continue

        # 计算名称相似度
        def _sim(a: str, b: str) -> float:
            if not a or not b:
                return 0.0
            a2, b2 = _alias(a), _alias(b)
            if a2 == b2 or a == b:
                return 1.0
            if a in b2 or b2 in a or a2 in b or b in a2:
                return 0.7
            # 字符集重合度
            common = len(set(a) & set(b))
            total = len(set(a) | set(b))
            return common / total if total > 0 else 0.0

        # 正序
        h_sim = _sim(b_home, home_cn)
        a_sim = _sim(b_away, away_cn)
        score_fwd = (h_sim + a_sim) / 2
        # 倒序
        h_sim_r = _sim(b_home, away_cn)
        a_sim_r = _sim(b_away, home_cn)
        score_rev = (h_sim_r + a_sim_r) / 2
        score = max(score_fwd, score_rev)

        if score > best_score:
            best_score = score
            best_match = odds

    # 阈值：0.6
    if best_score >= 0.6 and best_match:
        return best_match

    return None




asyncio.run(main())
