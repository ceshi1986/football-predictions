#!/usr/bin/env python3
"""
构建固定回测总表 v2：
- 合并所有数据源，以566备份为基准（有正确V6.5场景）
- 对仅matched_690中有的比赛，从kdata重新计算V6.5信号和场景
- 对仅match_results中有的比赛，尝试从每日Kelly数据匹配
- 去重（按home+away），剔除无法回测的场次
"""
import json, os, re
from collections import defaultdict, Counter

REPO = '/Coze/Drive/私人助理小策/所有对话/主对话/fp-repo'

# ============================================================
# Kelly信号计算（从backtest_v65.py复制）
# ============================================================

def get_signal_from_kelly(kh, kd, ka, payout, is_strong_home):
    if kh is None or kd is None or ka is None or payout is None:
        return 'X'
    fav_h = kh <= payout
    fav_d = kd <= payout
    fav_a = ka <= payout
    raw = set()
    if fav_h: raw.add('胜')
    if fav_d: raw.add('平')
    if fav_a: raw.add('负')
    if len(raw) == 0:
        return 'X'
    if is_strong_home:
        mapping = {
            frozenset(['胜']): 'A', frozenset(['胜', '平']): 'B',
            frozenset(['胜', '负']): 'C', frozenset(['平']): 'Y',
            frozenset(['负']): 'Z', frozenset(['平', '负']): 'W',
            frozenset(['胜', '平', '负']): 'D',
        }
    else:
        mapping = {
            frozenset(['胜']): 'Z', frozenset(['胜', '平']): 'W',
            frozenset(['胜', '负']): 'C', frozenset(['平']): 'Y',
            frozenset(['负']): 'A', frozenset(['平', '负']): 'B',
            frozenset(['胜', '平', '负']): 'D',
        }
    return mapping.get(frozenset(raw), 'X')

def resolve_d_state(kh, kd, ka, is_strong_home):
    if kh is None or kd is None or ka is None:
        return 'X'
    if kh == kd == ka:
        return 'B'
    if kh == kd and kh > ka:
        return 'Z' if is_strong_home else 'A'
    if kh == ka and kh > kd:
        return 'Y'
    if kd == ka and kd > kh:
        return 'A' if is_strong_home else 'Z'
    if kh == kd and kh < ka:
        return 'B' if is_strong_home else 'W'
    if kh == ka and kh < kd:
        return 'C'
    if kd == ka and kd < kh:
        return 'W' if is_strong_home else 'B'
    max_val = max(kh, kd, ka)
    if max_val == kh:
        return 'W' if is_strong_home else 'B'
    elif max_val == kd:
        return 'C'
    else:
        return 'B' if is_strong_home else 'W'

def compute_signals_and_scene(kdata, is_strong_home):
    """从kdata计算365和韦德的信号及场景"""
    companies = kdata.get('companies', {})
    
    # 提取365 Kelly
    c365 = companies.get('bet365', {})
    k365 = c365.get('kelly', [None, None, None])
    p365 = c365.get('payout')
    
    # 提取韦德 Kelly
    cwd = companies.get('weide', {})
    kwd = cwd.get('kelly', [None, None, None])
    pwd = cwd.get('payout')
    
    if len(k365) < 3 or len(kwd) < 3:
        return None, None, None, None
    
    kh365, kd365, ka365 = float(k365[0]), float(k365[1]), float(k365[2])
    khwd, kdwd, kawd = float(kwd[0]), float(kwd[1]), float(kwd[2])
    p365 = float(p365) if p365 else 0.91
    pwd = float(pwd) if pwd else 0.91
    
    sig_365_raw = get_signal_from_kelly(kh365, kd365, ka365, p365, is_strong_home)
    sig_weide_raw = get_signal_from_kelly(khwd, kdwd, kawd, pwd, is_strong_home)
    
    sig_365 = sig_365_raw
    sig_weide = sig_weide_raw
    if sig_365 == 'D':
        sig_365 = resolve_d_state(kh365, kd365, ka365, is_strong_home)
    if sig_weide == 'D':
        sig_weide = resolve_d_state(khwd, kdwd, kawd, is_strong_home)
    
    if sig_365 == 'X' or sig_weide == 'X':
        return sig_365_raw, sig_weide_raw, sig_365, sig_weide, None
    
    scene = sig_365 + sig_weide
    return sig_365_raw, sig_weide_raw, sig_365, sig_weide, scene

# ============================================================
# 1. 加载数据源
# ============================================================

with open(f'{REPO}/data/matched_690.json') as f:
    m690 = json.load(f)
with open(f'{REPO}/backtest_v64_2252_566场_20260815_备份.json') as f:
    b566 = json.load(f)['detail']
with open(f'{REPO}/data/match_results_merged.json') as f:
    mrm = json.load(f)

# ============================================================
# 2. 以566备份为基准构建master（566有正确的V6.5场景）
# ============================================================

def match_key(item):
    return f"{item['home']}_{item['away']}"

master = {}

# 第一层：566备份（最高优先级，有完整V6.5数据）
for item in b566:
    mk = match_key(item)
    master[mk] = {**item, '_source': '566'}

print(f'566备份: {len(master)}场')

# 第二层：matched_690（补充566没有的比赛）
added_690 = 0
for item in m690:
    mk = match_key(item)
    if mk not in master:
        # 需要从kdata重新计算V6.5信号和场景
        master[mk] = {**item, '_source': '690'}
        added_690 += 1

print(f'matched_690新增: {added_690}场')

# 第三层：match_results_merged（补充以上两个都没有的）
added_mrm = 0
for item in mrm:
    mk = match_key(item)
    if mk not in master:
        master[mk] = {**item, '_source': 'mrm'}
        added_mrm += 1

print(f'match_results新增: {added_mrm}场')
print(f'合并总计: {len(master)}场')

# ============================================================
# 3. 为缺少V6.5信号的比赛计算信号和场景
# ============================================================

need_recalc = 0
recalc_ok = 0
recalc_fail = 0

for mk, item in master.items():
    # 如果已有正确的sig_365和sig_weide（来自566备份），跳过
    if item.get('sig_365') and item.get('sig_weide') and item.get('scenario') and len(item['scenario']) == 2:
        # 检查场景字母是否都在A/B/C/W/Y/Z范围内
        sc = item['scenario']
        if all(c in 'ABCWYZ' for c in sc):
            continue
    
    # 需要重新计算
    need_recalc += 1
    kdata = item.get('kdata')
    if not kdata or not isinstance(kdata, dict):
        recalc_fail += 1
        continue
    
    strong = item.get('strong', '')
    if not strong:
        strong = 'home' if item.get('is_strong_home') else 'away'
    is_strong_home = (strong == 'home')
    
    result = compute_signals_and_scene(kdata, is_strong_home)
    if result and result[4]:  # scene is valid
        sig_365_raw, sig_weide_raw, sig_365, sig_weide, scene = result
        item['sig_365_raw'] = sig_365_raw
        item['sig_weide_raw'] = sig_weide_raw
        item['sig_365'] = sig_365
        item['sig_weide'] = sig_weide
        item['scenario'] = scene
        item['is_strong_home'] = is_strong_home
        item['strong'] = strong
        recalc_ok += 1
    else:
        recalc_fail += 1

print(f'\n需要重算信号: {need_recalc}场')
print(f'  成功: {recalc_ok}')
print(f'  失败: {recalc_fail}')

# ============================================================
# 4. 筛选可回测场次 & 构建总表
# ============================================================

def calc_result(item):
    sh, sa = int(item['score_h']), int(item['score_a'])
    if sh > sa: return '胜'
    elif sh == sa: return '平'
    else: return '负'

backtest_table = []
excluded = []
exclude_reasons = Counter()

for mk, item in sorted(master.items(), key=lambda x: x[1].get('date', '')):
    # 检查赛果
    if item.get('score_h') is None or item.get('score_a') is None:
        excluded.append({**item, '_exclude_reason': 'no_score'})
        exclude_reasons['no_score'] += 1
        continue
    
    # 检查V6.5场景
    sc = item.get('scenario', '')
    if not sc or len(sc) != 2 or not all(c in 'ABCWYZ' for c in sc):
        excluded.append({**item, '_exclude_reason': 'no_v65_scenario'})
        exclude_reasons['no_v65_scenario'] += 1
        continue
    
    # 检查Kelly信号
    if not item.get('sig_365') or not item.get('sig_weide'):
        excluded.append({**item, '_exclude_reason': 'no_signal'})
        exclude_reasons['no_signal'] += 1
        continue
    
    # X信号排除
    if item['sig_365'] == 'X' or item['sig_weide'] == 'X':
        excluded.append({**item, '_exclude_reason': 'X_signal'})
        exclude_reasons['X_signal'] += 1
        continue
    
    result = calc_result(item)
    strong = item.get('strong', '')
    is_strong_home = item.get('is_strong_home', strong == 'home')
    subgroup = f"{sc}{'主' if is_strong_home else '客'}"
    
    record = {
        'date': item['date'],
        'home': item['home'],
        'away': item['away'],
        'score_h': int(item['score_h']),
        'score_a': int(item['score_a']),
        'result': result,
        'scenario': sc,
        'strong': strong,
        'is_strong_home': is_strong_home,
        'subgroup': subgroup,
        'sig_365': item['sig_365'],
        'sig_weide': item['sig_weide'],
        'sig_365_raw': item.get('sig_365_raw', ''),
        'sig_weide_raw': item.get('sig_weide_raw', ''),
    }
    backtest_table.append(record)

print(f'\n=== 回测总表 ===')
print(f'可回测: {len(backtest_table)}场')
print(f'被排除: {len(excluded)}场')
print(f'排除原因: {dict(exclude_reasons)}')

# 统计
dates = sorted(set(r['date'] for r in backtest_table))
scenarios = Counter(r['scenario'] for r in backtest_table)
subgroups = Counter(r['subgroup'] for r in backtest_table)
results = Counter(r['result'] for r in backtest_table)

print(f'日期范围: {dates[0]} ~ {dates[-1]} ({len(dates)}天)')
print(f'场景数: {len(scenarios)} → {sorted(scenarios.keys())}')
print(f'子组数: {len(subgroups)}')
print(f'赛果: 胜{results.get("胜",0)} 平{results.get("平",0)} 负{results.get("负",0)}')

# ============================================================
# 5. 保存
# ============================================================

output = {
    'version': '2.0',
    'description': '固定回测总表 - 合并所有数据源+去重+V6.5信号重算',
    'created': '2026-08-16',
    'total_matches': len(backtest_table),
    'excluded_count': len(excluded),
    'excluded_reasons': dict(exclude_reasons),
    'date_range': [dates[0], dates[-1]],
    'scenario_count': len(scenarios),
    'subgroup_count': len(subgroups),
    'detail': backtest_table
}

outpath = f'{REPO}/backtest_master_table.json'
with open(outpath, 'w') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f'\n✅ 已保存: {outpath} ({os.path.getsize(outpath)/1024:.0f}KB)')

# 保存排除列表
excl_output = {
    'total': len(excluded),
    'reasons': dict(exclude_reasons),
    'detail': [{'date': e['date'], 'home': e['home'], 'away': e['away'], 
                'reason': e['_exclude_reason']} for e in excluded]
}
with open(f'{REPO}/backtest_master_excluded.json', 'w') as f:
    json.dump(excl_output, f, ensure_ascii=False, indent=2)
print(f'✅ 排除列表: backtest_master_excluded.json')

# 子组明细
print(f'\n=== 子组明细 ===')
for sg in sorted(subgroups.keys()):
    cnt = subgroups[sg]
    sg_results = Counter(r['result'] for r in backtest_table if r['subgroup'] == sg)
    print(f'  {sg}: {cnt}场 (胜{sg_results.get("胜",0)} 平{sg_results.get("平",0)} 负{sg_results.get("负",0)})')
