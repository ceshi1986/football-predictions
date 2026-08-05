#!/usr/bin/env python3
"""
v5 策略回测脚本
基于v4.5回测深度分析结果，设计v5策略并回测258场比赛
"""

import json
from collections import defaultdict, OrderedDict
from datetime import datetime

# ============================================================
# 数据加载
# ============================================================
with open('backtest_v45_detail.json') as f:
    data = json.load(f)
matches = data['matches']

# ============================================================
# 工具函数
# ============================================================

DIR_MAP = {0: 'H', 1: 'D', 2: 'A'}  # 胜/平/负
DIR_CN = {'H': '胜', 'D': '平', 'A': '负'}

def compute_signal(kelly, payout):
    """计算单家公司的Kelly信号"""
    if kelly is None or payout is None:
        return None
    w, d, l = kelly
    if w <= payout and d <= payout and l > payout:
        return 'H'
    if l <= payout and d <= payout and w > payout:
        return 'A'
    if l <= payout and d > payout and w > payout:
        return 'A_strong'
    if w <= payout and d > payout and l > payout:
        return 'pure_H'
    if w <= payout and l <= payout and d > payout:
        return 'no_draw'
    if w <= payout and d <= payout and l <= payout:
        return 'all_good'
    return 'mixed'


def company_favored_direction(kelly):
    """公司看好方向 = Kelly值最低的方向"""
    if kelly is None:
        return None
    return DIR_MAP[kelly.index(min(kelly))]


def kelly_sum(m):
    """365+韦德各方向Kelly和"""
    return [m['kelly_365'][i] + m['kelly_weide'][i] for i in range(3)]


def kelly_sum_direction(m):
    """Kelly和最低方向 (365+韦德)"""
    ks = kelly_sum(m)
    return DIR_MAP[ks.index(min(ks))]


def kelly_sum_lowest_two(m):
    """Kelly和最低两方向 (双选)"""
    ks = kelly_sum(m)
    sorted_dirs = sorted(range(3), key=lambda i: ks[i])
    return [DIR_MAP[sorted_dirs[0]], DIR_MAP[sorted_dirs[1]]]


def kelly_sum_lowest_one(m):
    """Kelly和最低方向 (单选)"""
    return kelly_sum_direction(m)


def max_kelly_payout_diff(kelly, payout):
    """公司Kelly-payout差值 (三个方向最大差)"""
    if kelly is None or payout is None:
        return None
    return max(abs(k - payout) for k in kelly)


def is_h_type_signal(sig):
    """是否是看好主方向的信号"""
    return sig in ('H', 'pure_H')


def is_a_type_signal(sig):
    """是否是看好客方向的信号"""
    return sig in ('A', 'A_strong')


def no_macau_data(m):
    """无澳门数据"""
    return m['kelly_macau'] is None


def odds_direction(m):
    """赔率看好方向"""
    return m.get('odds_favorite', None)


def odds_see_home(m):
    """赔率看主胜 (主胜赔率最低)"""
    return odds_direction(m) == 'H'


def odds_see_away(m):
    """赔率看客胜 (客胜赔率最低)"""
    return odds_direction(m) == 'A'


def libo_contradicts(m):
    """立博矛盾: 立博看好方向与365+韦德主流方向不一致"""
    if m['kelly_libo'] is None:
        return False
    libo_dir = company_favored_direction(m['kelly_libo'])
    main_dir = kelly_sum_direction(m)
    return libo_dir != main_dir


def macau_contradicts(m):
    """澳门矛盾: 澳门看好方向与365+韦德主流方向不一致"""
    if m['kelly_macau'] is None:
        return False
    macau_dir = company_favored_direction(m['kelly_macau'])
    main_dir = kelly_sum_direction(m)
    return macau_dir != main_dir


def odds_contradicts_kelly(m):
    """赔率矛盾: 赔率看好方向与Kelly和最低方向不一致"""
    od = odds_direction(m)
    if od is None:
        return False
    kd = kelly_sum_direction(m)
    # Map: H=胜, A=负, D=平
    # If odds favor H but Kelly favors A or D → contradiction
    # If odds favor A but Kelly favors H or D → contradiction
    if od == 'H':
        return kd != 'H'
    elif od == 'A':
        return kd != 'A'
    return False


def diff_365(m):
    """365差值"""
    return max_kelly_payout_diff(m['kelly_365'], m['payout_365'])


def diff_weide(m):
    """韦德差值"""
    return max_kelly_payout_diff(m['kelly_weide'], m['payout_weide'])


def check_pick_hit(pick, result_dir):
    """检查选择是否命中"""
    rd_map = {'H': '胜', 'D': '平', 'A': '负'}
    result_cn = rd_map.get(result_dir, result_dir)
    return result_cn in pick or result_dir in pick


def pick_to_cn(pick):
    """将方向列表转为中文"""
    return '+'.join(DIR_CN.get(d, d) for d in sorted(pick, key=lambda x: {'胜':0,'平':1,'负':2}.get(DIR_CN.get(x,x),3)))


# ============================================================
# v5 场景分类
# ============================================================

def classify_v5_scenario(m):
    """
    v5场景分类 (按优先级)
    返回: (scenario, sub_rule, dual_pick, single_pick)
    """
    sig_365 = m['signal_365']
    sig_weide = m['signal_weide']
    
    # ---- ①A强废弁: 原①A强降级到弱/④ ----
    # 不再作为独立高优先级场景
    
    # 1. ①H: 两家看好主不败 (H or pure_H, 但不是两家pure_H)
    if is_h_type_signal(sig_365) and is_h_type_signal(sig_weide):
        # 区分①H和纯主胜双
        if sig_365 == 'pure_H' and sig_weide == 'pure_H':
            # 纯主胜双 (priority 9)
            return classify_pure_H_dual(m)
        # ①H: 至少一家不是pure_H
        return classify_1h(m)
    
    # Check for ①H混合: 一家纯主胜 + 一家H
    if (is_h_type_signal(sig_365) and is_h_type_signal(sig_weide)):
        pass  # Already handled above
    
    # ①H混合: one pure_H + one H (not both pure_H, not both H-only)
    if (sig_365 == 'pure_H' and sig_weide == 'H') or (sig_365 == 'H' and sig_weide == 'pure_H'):
        return classify_1h_mixed(m)
    
    # Also: one pure_H + one H (with all_good mixed in)
    # Check broader: one h-type + one h-type, but different sub-types
    # Already covered above since both h-type goes to ①H or 纯主胜双
    # ①H混合 specifically requires one pure_H + one H (non-pure_H h-type)
    # Wait, I already handled both h-type above in rule 1.
    # Let me reconsider: 
    # - Both H → ①H
    # - Both pure_H → 纯主胜双
    # - pure_H + H → ①H混合
    # The first rule catches ALL h-type pairs. Need to restructure.

    # Actually, let me redo the classification more carefully:
    pass  # Will be restructured below


def classify_v5(m):
    """v5完整分类"""
    sig_365 = m['signal_365']
    sig_weide = m['signal_weide']
    
    # ---- Step 1: ①H vs 纯主胜双 vs ①H混合 ----
    both_h_type = is_h_type_signal(sig_365) and is_h_type_signal(sig_weide)
    if both_h_type:
        both_pure_h = (sig_365 == 'pure_H' and sig_weide == 'pure_H')
        one_pure_h_one_h = ((sig_365 == 'pure_H' and sig_weide == 'H') or 
                            (sig_365 == 'H' and sig_weide == 'pure_H'))
        both_h = (sig_365 == 'H' and sig_weide == 'H')
        
        if both_pure_h:
            # 纯主胜双
            return apply_pure_H_dual(m)
        elif one_pure_h_one_h:
            # ①H混合
            return apply_1h_mixed(m)
        elif both_h:
            # ①H
            return apply_1h(m)
        else:
            # One pure_H + one pure_H? No, that's both_pure_h
            # One H + one pure_H? No, that's one_pure_h_one_h
            # Could be: pure_H + pure_H (caught), H + H (caught), pure_H + H (caught)
            # Or: one is H, one is pure_H (caught)
            # What about all_good or mixed? These are not h-type
            # This shouldn't happen since both are h-type
            # Edge: one H + one pure_H but with all_good mixed in? No.
            # If both are h-type but not matching above patterns → ①H (broader)
            return apply_1h(m)
    
    # ---- Step 2: ①A原 ----
    both_a = (sig_365 == 'A' and sig_weide == 'A')
    if both_a:
        return apply_1a_original(m)
    
    # ---- Step 3: 去平+H ----
    # one no_draw + other h-type (H or pure_H)
    def is_nodraw(s): return s == 'no_draw'
    if (is_nodraw(sig_365) and is_h_type_signal(sig_weide)) or \
       (is_h_type_signal(sig_365) and is_nodraw(sig_weide)):
        return apply_nodraw_h(m)
    
    # ---- Step 4: 去平+A ----
    # one no_draw + other a-type (A or A_strong)
    if (is_nodraw(sig_365) and is_a_type_signal(sig_weide)) or \
       (is_a_type_signal(sig_365) and is_nodraw(sig_weide)):
        return apply_nodraw_a(m)
    
    # ---- Step 5: ③ ----
    if sig_365 == 'no_draw' and sig_weide == 'no_draw':
        return apply_3(m)
    
    # ---- Step 6: ② ----
    # 各不看好不同方向: 365 favors H-type, Weide favors A-type (or vice versa)
    # Or: other mixed-direction signal pairs
    # Definition: one company's favored direction is different from the other's
    # More specifically: signals favor different teams
    if _is_scenario_2(sig_365, sig_weide):
        return apply_2(m)
    
    # ---- Step 7: ④ ----
    # 独低于返还率加强: only one company has a below-payout direction
    # But also need to apply 赔率矛盾过滤
    if _is_scenario_4(m):
        return apply_4(m)
    
    # ---- Step 8: ①A混合 ----
    # one A + one A_strong (neither is no_draw)
    if ((sig_365 == 'A' and sig_weide == 'A_strong') or 
        (sig_365 == 'A_strong' and sig_weide == 'A')):
        return apply_1a_mixed(m)
    
    # ---- Step 9: 弱 ----
    return apply_weak(m)


def _is_scenario_2(sig_365, sig_weide):
    """判断是否场景②: 各看好不同方向"""
    # H-type vs A-type → different directions
    if is_h_type_signal(sig_365) and is_a_type_signal(sig_weide):
        return True
    if is_a_type_signal(sig_365) and is_h_type_signal(sig_weide):
        return True
    # no_draw vs h-type or a-type: not ② (these are 去平+H/A, already caught)
    # mixed/all_good with h-type or a-type: could be ②
    # Specifically: if signals don't agree on direction → ②
    # For simplicity: if one is mixed/all_good and the other is clearly directional
    # Actually, let's be more precise:
    # ② = 365看好A方向, 韦德看好B方向 (different teams favored)
    # This includes:
    # - H vs A/A_strong
    # - pure_H vs A/A_strong  
    # - H vs mixed (if mixed favors different direction)
    # - A vs mixed (if mixed favors different direction)
    # etc.
    # For the remaining cases after higher-priority checks:
    # - We've already handled: both h-type, both a, no_draw combos, ①A混合
    # - Remaining signal pairs where directions differ → ②
    # Remaining pairs:
    # - h-type vs mixed/all_good (different directions)
    # - a-type vs mixed/all_good
    # - h-type vs a-type (should have been caught, but just in case)
    # - no_draw vs mixed/all_good
    # - mixed vs mixed/all_good
    # - A_strong + A_strong (both a-type but A_strong, not caught by ①A原)
    # etc.
    
    # More practical: check if the two signals favor different overall directions
    dir_365 = _signal_direction(sig_365)
    dir_weide = _signal_direction(sig_weide)
    if dir_365 is not None and dir_weide is not None and dir_365 != dir_weide:
        return True
    return False


def _signal_direction(sig):
    """信号的大方向: H, A, or None"""
    if sig in ('H', 'pure_H'):
        return 'H'
    if sig in ('A', 'A_strong'):
        return 'A'
    if sig == 'no_draw':
        return 'no_draw'  # ambiguous
    return None


def _is_scenario_4(m):
    """判断是否场景④: 独低于返还率加强"""
    # ④: only one company has a clearly below-payout direction
    # Or: one company has a strong below-payout direction, the other doesn't
    # More practically: after all higher-priority scenarios are excluded,
    # ④ applies when signals suggest one company has a direction below payout
    # but the other doesn't clearly agree
    sig_365 = m['signal_365']
    sig_weide = m['signal_weide']
    
    # ④ = only one company's signal has a direction below payout
    # Check: one company has a clear directional signal, other doesn't
    has_clear_365 = sig_365 in ('H', 'pure_H', 'A', 'A_strong', 'no_draw')
    has_clear_weide = sig_weide in ('H', 'pure_H', 'A', 'A_strong', 'no_draw')
    
    # If both have clear signals → not ④ (caught by earlier scenarios)
    # If neither has clear signals → not ④ (weak)
    # If one has clear signal, other doesn't → ④
    if has_clear_365 != has_clear_weide:
        return True
    
    # Also: A_strong + A_strong (was ①A强, now demoted)
    # Both have clear signals but both are A_strong
    if sig_365 == 'A_strong' and sig_weide == 'A_strong':
        return True
    
    # Both mixed/all_good → not ④
    return False


# ============================================================
# 场景应用函数
# ============================================================

def _base_kelly_pick(m):
    """Kelly和最低两方向 + 最低方向"""
    dual = kelly_sum_lowest_two(m)
    single = kelly_sum_lowest_one(m)
    return dual, single


def _nodraw_kelly_pick(m):
    """去平类场景: 平 + 非平方向中Kelly和更低的方向"""
    ks = kelly_sum(m)
    # 非平方向: H(0) and A(2)
    lower_non_draw = 'H' if ks[0] <= ks[2] else 'A'
    dual = ['D', lower_non_draw]
    single = lower_non_draw
    return dual, single


def apply_1h(m):
    """①H: 胜+平 / 胜"""
    # Enhanced sub-rules (priority order):
    # 1a: ①H+立博矛盾 → 胜+平 / 胜 (90.9%)
    # 1b: ①H+赔率看主 → 胜+平 / 胜 (83.3%)
    # base: ①H → 胜+平 / 胜
    
    dual = ['H', 'D']  # 胜+平
    single = 'H'  # 胜
    
    sub_rule = '①H'
    if libo_contradicts(m):
        sub_rule = '①H+立博矛盾'
    elif odds_see_home(m):
        sub_rule = '①H+赔率看主'
    
    return '①H', sub_rule, dual, single


def apply_1h_mixed(m):
    """①H混合: 胜+平 / 胜"""
    # Enhanced sub-rules (priority order):
    # 2a: ①H混合+澳门矛盾 → 胜+平 / 胜 (100%)
    # 2b: ①H混合+立博矛盾 → 胜+平 / 胜 (90.9%)
    # 2c: ①H混合+365差0.01-0.03 → 胜+平 / 胜 (80.0%)
    # base: ①H混合 → 胜+平 / 胜
    
    dual = ['H', 'D']  # 胜+平
    single = 'H'  # 胜
    
    sub_rule = '①H混合'
    d365 = diff_365(m)
    if macau_contradicts(m):
        sub_rule = '①H混合+澳门矛盾'
    elif libo_contradicts(m):
        sub_rule = '①H混合+立博矛盾'
    elif d365 is not None and 0.01 <= d365 <= 0.03:
        sub_rule = '①H混合+365差0.01-0.03'
    
    return '①H混合', sub_rule, dual, single


def apply_1a_original(m):
    """①A原: 平+负 / 平"""
    # Enhanced sub-rules:
    # 3a: ①A原+两家都是A → same pick (85.7%)
    # base: ①A原 → 平+负 / 平
    
    dual = ['D', 'A']  # 平+负
    single = 'D'  # 平
    
    sub_rule = '①A原'
    if m['signal_365'] == 'A' and m['signal_weide'] == 'A':
        sub_rule = '①A原+两家A'
    
    return '①A原', sub_rule, dual, single


def apply_nodraw_h(m):
    """去平+H: 平+非平Kelly和更低方向"""
    # Enhanced sub-rules:
    # 4a: 去平+H+无澳门 → same pick (100%)
    # base: 去平+H
    
    dual, single = _nodraw_kelly_pick(m)
    
    sub_rule = '去平+H'
    if no_macau_data(m):
        sub_rule = '去平+H+无澳门'
    
    return '去平+H', sub_rule, dual, single


def apply_nodraw_a(m):
    """去平+A: Kelly和最低两方向"""
    # Enhanced sub-rules:
    # 5a: 去平+A+365差>0.03 → same pick (高信心)
    # base: 去平+A
    # NOTE: 365差0.01-0.03排除规则已取消 (回测发现该排除反而降低命中率)
    
    dual, single = _base_kelly_pick(m)
    
    sub_rule = '去平+A'
    d365 = diff_365(m)
    if d365 is not None and d365 > 0.03:
        sub_rule = '去平+A+365差>0.03'
    
    return '去平+A', sub_rule, dual, single


def apply_2(m):
    """②: Kelly和最低两方向"""
    # Enhanced sub-rules:
    # 6a: ②+365差>0.03 → same pick, 可博单选 (92.3%)
    # 6b: ②+赔率看客 → same pick (90.9%)
    # 6c: ②+赔率看客+无澳门 → same pick (90.9%)
    # base: ②
    
    dual, single = _base_kelly_pick(m)
    
    sub_rule = '②'
    d365 = diff_365(m)
    if d365 is not None and d365 > 0.03:
        sub_rule = '②+365差>0.03'
    elif odds_see_away(m) and no_macau_data(m):
        sub_rule = '②+赔率看客+无澳门'
    elif odds_see_away(m):
        sub_rule = '②+赔率看客'
    
    return '②', sub_rule, dual, single


def apply_3(m):
    """③: 胜+负 / 胜"""
    # Enhanced: same as base
    dual = ['H', 'A']  # 胜+负
    single = 'H'  # 胜
    return '③', '③', dual, single


def apply_4(m):
    """④: Kelly和最低两方向"""
    # 赔率矛盾过滤: ④+赔率矛盾 → 降级到弱
    if odds_contradicts_kelly(m):
        return apply_weak(m, force_reason='④排除(赔率矛盾)')
    
    # Enhanced sub-rules:
    # 8a: ④+赔率看客 → same pick (100%)
    # 8b: ④+365差>0.05 → same pick (87.5%)
    # 8c: ④+无澳门 → same pick (85.7%)
    # base: ④
    
    dual, single = _base_kelly_pick(m)
    
    sub_rule = '④'
    d365 = diff_365(m)
    if odds_see_away(m):
        sub_rule = '④+赔率看客'
    elif d365 is not None and d365 > 0.05:
        sub_rule = '④+365差>0.05'
    elif no_macau_data(m):
        sub_rule = '④+无澳门'
    
    return '④', sub_rule, dual, single


def apply_pure_H_dual(m):
    """纯主胜双: 胜+平 / 胜"""
    # Enhanced:
    # 9a: 纯主胜双+韦德差0.01-0.03 → same pick (80.0%)
    # base: 纯主胜双
    
    dual = ['H', 'D']  # 胜+平
    single = 'H'  # 胜
    
    sub_rule = '纯主胜双'
    dwd = diff_weide(m)
    if dwd is not None and 0.01 <= dwd <= 0.03:
        sub_rule = '纯主胜双+韦德差0.01-0.03'
    
    return '纯主胜双', sub_rule, dual, single


def apply_1a_mixed(m):
    """①A混合: 需赔率一致, 否则降级弱"""
    # 赔率矛盾 → 降级弱 (44.4%)
    if odds_contradicts_kelly(m):
        return apply_weak(m, force_reason='①A混合排除(赔率矛盾)')
    
    # 赔率一致 → Kelly和最低两方向 (81.8%)
    dual, single = _base_kelly_pick(m)
    return '①A混合', '①A混合', dual, single


def apply_weak(m, force_reason=None):
    """弱: Kelly和最低两方向"""
    dual, single = _base_kelly_pick(m)
    sub_rule = force_reason if force_reason else '弱'
    return '弱', sub_rule, dual, single


# ============================================================
# 执行回测
# ============================================================

results = []
for m in matches:
    scenario, sub_rule, dual_pick, single_pick = classify_v5(m)
    
    # Check dual hit
    result_dir = m['result_dir']
    rd_map = {'H': '胜', 'D': '平', 'A': '负'}
    result_cn = rd_map.get(result_dir, result_dir)
    dual_hit = result_cn in [DIR_CN.get(d, d) for d in dual_pick]
    single_hit = (DIR_CN.get(single_pick, single_pick) == result_cn)
    
    results.append({
        'date': m['date'],
        'home': m['home'],
        'away': m['away'],
        'score': f"{m['score_h']}-{m['score_a']}",
        'result_dir': result_dir,
        'v45_scenario': m['scenario'],
        'v5_scenario': scenario,
        'v5_sub_rule': sub_rule,
        'v5_dual_pick': [DIR_CN.get(d, d) for d in dual_pick],
        'v5_single_pick': DIR_CN.get(single_pick, single_pick),
        'v5_dual_hit': dual_hit,
        'v5_single_hit': single_hit,
        'v45_dual_hit': m['dual_hit'],
        'v45_single_hit': m['single_hit'],
        'signal_365': m['signal_365'],
        'signal_weide': m['signal_weide'],
        'signal_libo': m['signal_libo'],
        'signal_macau': m['signal_macau'],
        'odds_favorite': m.get('odds_favorite'),
        'diff_365': diff_365(m),
        'diff_weide': diff_weide(m),
        'odds_contra': odds_contradicts_kelly(m),
        'libo_contra': libo_contradicts(m),
        'macau_contra': macau_contradicts(m),
        'no_macau': no_macau_data(m),
    })

# ============================================================
# 统计
# ============================================================

# Overall
total = len(results)
v5_dual_hits = sum(1 for r in results if r['v5_dual_hit'])
v5_single_hits = sum(1 for r in results if r['v5_single_hit'])
v45_dual_hits = sum(1 for r in results if r['v45_dual_hit'])
v45_single_hits = sum(1 for r in results if r['v45_single_hit'])

print("=" * 60)
print("v5 回测结果总览")
print("=" * 60)
print(f"总场次: {total}")
print(f"v5双选命中率: {v5_dual_hits}/{total} = {v5_dual_hits/total*100:.1f}%")
print(f"v4.5双选命中率: {v45_dual_hits}/{total} = {v45_dual_hits/total*100:.1f}%")
print(f"v5单选命中率: {v5_single_hits}/{total} = {v5_single_hits/total*100:.1f}%")
print(f"v4.5单选命中率: {v45_single_hits}/{total} = {v45_single_hits/total*100:.1f}%")
print(f"双选提升: {(v5_dual_hits-v45_dual_hits)/total*100:+.1f}%")
print(f"单选提升: {(v5_single_hits-v45_single_hits)/total*100:+.1f}%")

# Per scenario
print("\n" + "=" * 60)
print("v5 各场景统计")
print("=" * 60)

scenario_stats = defaultdict(lambda: {'total': 0, 'dual_hit': 0, 'single_hit': 0})
for r in results:
    s = r['v5_scenario']
    scenario_stats[s]['total'] += 1
    scenario_stats[s]['dual_hit'] += r['v5_dual_hit']
    scenario_stats[s]['single_hit'] += r['v5_single_hit']

for s in ['①H', '①H混合', '①A原', '去平+H', '去平+A', '③', '②', '纯主胜双', '④', '①A混合', '弱']:
    if s in scenario_stats:
        d = scenario_stats[s]
        dr = d['dual_hit']/d['total']*100 if d['total'] else 0
        sr = d['single_hit']/d['total']*100 if d['total'] else 0
        print(f"  {s}: dual={d['dual_hit']}/{d['total']}={dr:.1f}%, single={d['single_hit']}/{d['total']}={sr:.1f}%")

# Per sub-rule
print("\n" + "=" * 60)
print("v5 各子规则统计")
print("=" * 60)

sub_rule_stats = defaultdict(lambda: {'total': 0, 'dual_hit': 0, 'single_hit': 0})
for r in results:
    sr = r['v5_sub_rule']
    sub_rule_stats[sr]['total'] += 1
    sub_rule_stats[sr]['dual_hit'] += r['v5_dual_hit']
    sub_rule_stats[sr]['single_hit'] += r['v5_single_hit']

# Sort by scenario priority then sub-rule
for sr, d in sorted(sub_rule_stats.items(), key=lambda x: x[1]['total'], reverse=True):
    dr = d['dual_hit']/d['total']*100 if d['total'] else 0
    sr_rate = d['single_hit']/d['total']*100 if d['total'] else 0
    print(f"  {sr}: dual={d['dual_hit']}/{d['total']}={dr:.1f}%, single={d['single_hit']}/{d['total']}={sr_rate:.1f}%")

# Demoted matches
print("\n" + "=" * 60)
print("v5 降级/排除的比赛")
print("=" * 60)

demoted = [r for r in results if r['v5_scenario'] != r['v45_scenario']]
for r in demoted:
    print(f"  {r['date']} {r['home']} vs {r['away']}: {r['v45_scenario']} → {r['v5_scenario']} (sub: {r['v5_sub_rule']})")

# v45→v5 pick changes
print("\n" + "=" * 60)
print("v4.5→v5 选择变化")
print("=" * 60)

pick_changes = [r for r in results if r['v5_dual_hit'] != r['v45_dual_hit']]
gained = [r for r in pick_changes if r['v5_dual_hit'] and not r['v45_dual_hit']]
lost = [r for r in pick_changes if not r['v5_dual_hit'] and r['v45_dual_hit']]
print(f"v5新命中: {len(gained)}场")
for r in gained:
    print(f"  + {r['date']} {r['home']} vs {r['away']} ({r['v45_scenario']}→{r['v5_scenario']}) v5pick={'+'.join(r['v5_dual_pick'])} result={r['result_dir']}")
print(f"v5新丢失: {len(lost)}场")
for r in lost:
    print(f"  - {r['date']} {r['home']} vs {r['away']} ({r['v45_scenario']}→{r['v5_scenario']}) v5pick={'+'.join(r['v5_dual_pick'])} result={r['result_dir']}")

# Save detailed results
with open('backtest_v5_detail.json', 'w') as f:
    json.dump({
        'meta': {
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_matches': total,
            'v5_dual_rate': f"{v5_dual_hits/total*100:.1f}%",
            'v5_single_rate': f"{v5_single_hits/total*100:.1f}%",
            'v45_dual_rate': f"{v45_dual_hits/total*100:.1f}%",
            'v45_single_rate': f"{v45_single_hits/total*100:.1f}%",
        },
        'scenario_stats': {s: dict(d) for s, d in scenario_stats.items()},
        'sub_rule_stats': {sr: dict(d) for sr, d in sub_rule_stats.items()},
        'results': results,
    }, f, ensure_ascii=False, indent=2)

print(f"\n详细结果已保存到 backtest_v5_detail.json")
