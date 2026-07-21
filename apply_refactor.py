#!/usr/bin/env python3
"""
重构脚本：融合新旧预测逻辑 - 凯利七场景引擎替换ABCD
"""
import re

# 读取原文件
with open('/app/data/所有对话/主对话/fp-repo/codeact/scripts/daily_predictions.py', 'r', encoding='utf-8') as f:
    content = f.read()

# ============================================================
# 1. 替换常量区域：_KEY_BOOKMAKERS 和旧常量
# ============================================================
old_constants = '''# ===== 凯利场景分析 =====
# 核心bookmaker key映射（The Odds API key -> 内部标识）
# 旧版逻辑：Pinnacle作为凯利分析核心庄家（Pinnacle返还率最高，赔率最接近真实概率）
_KEY_BOOKMAKERS = {
    "bet365": "bet365",
    "betvictor": "betvictor",
    "ladbrokes_uk": "ladbrokes",
    "williamhill": "williamhill",
    "coral": "coral",
    "betway": "betway",
    "pinnacle": "pinnacle",
}

# 立博平局Kelly阈值：低于返还率=立博对平局比市场更保守
# 全量回测：0.9393阈值触发0场（立博实际返还率均值≈0.93），故修正为1.0
LADBROKES_DRAW_KELLY_MEDIAN = 1.0
# Kelly异常过滤阈值
KELLY_MIN_FILTER_THRESHOLD = 0.87'''

new_constants = '''# ===== 凯利七场景检测引擎 v5 =====
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
}'''

content = content.replace(old_constants, new_constants)

# ============================================================
# 2. 替换 calc_kelly_scenario 函数
# ============================================================
# 找到函数开始和结束位置
func_start_marker = "def calc_kelly_scenario(bookmaker_odds: dict, home_team: str, away_team: str) -> dict:"
func_start = content.index(func_start_marker)

# 找到函数结束位置（下一个 def 或 class）
# 从函数开始往后找 "def predict_match"
func_end_marker = "\ndef predict_match("
func_end = content.index(func_end_marker, func_start)

# 新函数
new_calc_kelly = '''
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

'''

content = content[:func_start] + new_calc_kelly + content[func_end:]

# ============================================================
# 3. 替换 predict_match 函数
# ============================================================
# 找到 predict_match 函数的开始和结束
pm_start_marker = "def predict_match(match: dict, teams: dict, kelly_data: dict = None) -> dict:"
pm_start = content.index(pm_start_marker)

# 找到 predict_match 的结束（下一个 def）
pm_end_marker = "\ndef fetch_github_file("
pm_end = content.index(pm_end_marker, pm_start)

new_predict_match = '''def predict_match(match: dict, teams: dict, kelly_data: dict = None) -> dict:
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

'''

content = content[:pm_start] + new_predict_match + content[pm_end:]

# ============================================================
# 4. 修改主循环中 Odds API kelly_data 调用
# ============================================================
# 替换 Odds API 的 calc_kelly_scenario 调用
old_odds_api_call = '''            if matched_odds_evt:
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
                    print(f"[KELLY] {_home} vs {_away}: 场景{kelly_data['scenario']} {kelly_data.get('signal', '')}{unique_tag}{reverse_tag}")'''

new_odds_api_call = '''            if matched_odds_evt:
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
                    print(f"[KELLY] {_home} vs {_away}: 场景{kelly_data['scenario']} {kelly_data.get('signal', '')}{disp_tag}{skip_tag_k}")'''

content = content.replace(old_odds_api_call, new_odds_api_call)

# ============================================================
# 5. 修改主循环中 500com kelly_data 调用
# ============================================================
old_500com_call = '''            # ===== 500.com 凯利数据 fallback =====
            # 当 Odds API 无数据时，使用500.com抓取的凯利数据
            if not kelly_data and kelly_500com_data:
                matched_500com = _match_500com_match(_home, _away, match_league, kelly_500com_data)
                if matched_500com:
                    bookmaker_odds = _convert_500com_to_bookmaker_odds(matched_500com.get("companies", {}))
                    if len(bookmaker_odds) >= 2:
                        kelly_data = calc_kelly_scenario(
                            bookmaker_odds,
                            matched_500com.get("home", _home),
                            matched_500com.get("away", _away),
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
                            print(f"[KELLY-500COM] {_home} vs {_away}: 场景{kelly_data['scenario']} {kelly_data.get('signal', '')}{unique_tag}{reverse_tag}")'''

new_500com_call = '''            # ===== 500.com 凯利数据 fallback =====
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
                            print(f"[KELLY-500COM] {_home} vs {_away}: 场景{kelly_data['scenario']} {kelly_data.get('signal', '')}{disp_tag}{skip_tag_k}")'''

content = content.replace(old_500com_call, new_500com_call)

# ============================================================
# 6. 修改 record 构建（更新 kelly 相关字段）
# ============================================================
old_record = '''                "kellyScenario": pred.get("kellyScenario"),
                "kellySignal": pred.get("kellySignal"),
                "ladbrokesDrawKelly": pred.get("ladbrokesDrawKelly"),
                "kellyUniqueDirection": pred.get("kellyUniqueDirection"),
                "kellyUniqueSignal": pred.get("kellyUniqueSignal"),
                "kellyReverseDirection": pred.get("kellyReverseDirection"),
                "kellyReverseSignal": pred.get("kellyReverseSignal"),'''

new_record = '''                "kellyScenario": pred.get("kellyScenario"),
                "kellySignal": pred.get("kellySignal"),
                "kellyPick": pred.get("kellyPick"),
                "kellyCover": pred.get("kellyCover"),
                "kellyDispersion": pred.get("kellyDispersion"),'''

content = content.replace(old_record, new_record)

# ============================================================
# 7. 修改摘要显示中的 kelly 标签
# ============================================================
old_summary_kelly = '''                    kelly_tag = ""
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
                        reverse_tag = f" [反向排除{rev_dir_label}]"'''

new_summary_kelly = '''                    kelly_tag = ""
                    ks = p.get("kellyScenario")
                    if ks:
                        kelly_tag = f" [凯利{ks}]"
                    # 离散度标签
                    kelly_disp = p.get("kellyDispersion")
                    disp_tag = f" D{round(kelly_disp,3)}" if kelly_disp else ""
                    unique_tag = ""
                    reverse_tag = ""'''

content = content.replace(old_summary_kelly, new_summary_kelly)

# 修改摘要行中的标签拼接
old_summary_line = '''                    line = (
                        f"  {p.get('home', '')} vs {p.get('away', '')}\\n"
                        f"    {pred_type} {pred_text} | 置信度{conf}% | {stars_str}{kelly_tag}{unique_tag}{reverse_tag}{skip_tag}\\n"
                        f"    {odds_tag} {p.get('reason', '')}"
                    )'''

new_summary_line = '''                    line = (
                        f"  {p.get('home', '')} vs {p.get('away', '')}\\n"
                        f"    {pred_type} {pred_text} | 置信度{conf}% | {stars_str}{kelly_tag}{disp_tag}{unique_tag}{reverse_tag}{skip_tag}\\n"
                        f"    {odds_tag} {p.get('reason', '')}"
                    )'''

content = content.replace(old_summary_line, new_summary_line)

# ============================================================
# 8. 更新 Odds API 赔率获取的过滤条件
#    现在需要 bet365 + betvictor(韦德)，不再要求 pinnacle
# ============================================================
old_odds_filter = '''                # 至少需要2家核心公司赔率才有场景分析价值
                # 优先 bet365+betvictor，其次 pinnacle+betvictor（小联赛bet365常缺）
                key_count = len(bookmakers)
                has_b365_bv = "bet365" in bookmakers and "betvictor" in bookmakers
                has_pin_bv = "pinnacle" in bookmakers and "betvictor" in bookmakers
                if key_count >= 2 and (has_b365_bv or has_pin_bv):'''

new_odds_filter = '''                # 至少需要2家核心公司赔率才有场景分析价值
                # 核心：bet365 + betvictor(韦德)，备选 pinnacle+betvictor
                key_count = len(bookmakers)
                has_b365_bv = "bet365" in bookmakers and "betvictor" in bookmakers
                has_pin_bv = "pinnacle" in bookmakers and "betvictor" in bookmakers
                has_b365_pin = "bet365" in bookmakers and "pinnacle" in bookmakers
                if key_count >= 2 and (has_b365_bv or has_pin_bv or has_b365_pin):'''

content = content.replace(old_odds_filter, new_odds_filter)

# 写入修改后的文件
with open('/app/data/所有对话/主对话/fp-repo/codeact/scripts/daily_predictions.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("[OK] daily_predictions.py 已修改完成")
print(f"[INFO] 文件总行数: {len(content.splitlines())}")
