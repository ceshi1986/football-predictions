#!/usr/bin/env python3
"""V6策略回测 - 修复D状态前后对比，使用策略文档的正确策略表"""
import json

with open('backtest_v45_detail.json') as f:
    matches = json.load(f)['matches']

DIR_NAMES = ['主胜', '平', '客胜']

# V6策略表 (from 策略文档 6.2 速查表 - 正确的)
STRATEGY = {
    'AA':'胜平','AB':'胜平','AC':'胜负','AD':'','AE':'','AF':'',
    'BA':'胜平','BB':'胜平','BC':'胜平','BD':'','BE':'','BF':'',
    'CA':'胜负','CB':'胜平','CC':'胜负','CD':'','CE':'','CF':'',
    'WA':'胜平','WB':'平胜','WC':'负胜','WD':'',
    'AW':'胜平','AY':'胜平','AZ':'胜负',
    'BW':'平胜','BY':'胜平','BZ':'胜平',
    'CW':'负胜','CY':'胜平','CZ':'胜负',
    'YA':'胜平','YB':'胜平','YC':'胜平',
    'ZA':'胜负','ZB':'胜平','ZC':'胜负',
    'WW':'平负','WY':'平负','WZ':'平负',
    'YW':'平负','YY':'平胜','YZ':'平负',
    'ZW':'平负','ZY':'平负','ZZ':'负胜',
}
# Clean empty entries
STRATEGY = {k:v for k,v in STRATEGY.items() if v}

def letter_from_favs(favs, is_home):
    if not favs: return 'X'
    if len(favs) == 3: return 'D'
    key = ''.join(favs)
    if is_home:
        return {'h':'A','hd':'B','ha':'C','d':'Y','a':'Z','da':'W'}.get(key, 'X')
    else:
        return {'h':'Z','hd':'C','ha':'B','d':'Y','a':'A','da':'W'}.get(key, 'X')

def letter(kelly, payout, is_home):
    favs = [d for d, k in zip(['h','d','a'], kelly) if k <= payout]
    return letter_from_favs(favs, is_home)

# D state OLD
def d_old(kelly, payout, is_home):
    if all(k == kelly[0] for k in kelly):
        return 'B'
    max_val = max(kelly)
    for i, d in enumerate(['h','d','a']):
        if kelly[i] == max_val:
            max_dir = d
            break
    favs = [d for d in ['h','d','a'] if d != max_dir]
    return letter_from_favs(favs, is_home)

# D state NEW (fixed)
def d_new(kelly, payout, is_home):
    if all(k == kelly[0] for k in kelly):
        return 'B' if is_home else 'W'
    max_val = max(kelly)
    favs = [d for d, k in zip(['h','d','a'], kelly) if k != max_val]
    return letter_from_favs(favs, is_home)

def classify(k365, p365, kw, pw, odds, d_func):
    is_home = (odds[0] <= odds[2])  # 胜赔<=负赔 → 主队强
    s365 = letter(k365, p365, is_home)
    sw = letter(kw, pw, is_home)
    if s365 == 'D' and sw == 'D': return None, None, is_home
    has_d = False
    if s365 == 'D':
        s365 = d_func(k365, p365, is_home)
        has_d = True
    if sw == 'D':
        sw = d_func(kw, pw, is_home)
        has_d = True
    if s365 == 'X' or sw == 'X': return None, None, is_home
    return s365 + sw, has_d, is_home

def check_hit(pred, result, is_home):
    """判断实际结果是否命中预测。pred中的胜/负是相对强队方向，需根据is_home转为实际方向"""
    if not pred: return False
    if is_home:
        mapping = {'胜':'H', '平':'D', '负':'A'}
    else:
        mapping = {'胜':'A', '平':'D', '负':'H'}
    return any(result == mapping[ch] for ch in pred)

def run(d_func, label):
    total = valid = dual_hit = d_total = d_hit = 0
    no_pred = 0
    changed = []
    for m in matches:
        total += 1
        scen, has_d, is_home = classify(m['kelly_365'], m['payout_365'], m['kelly_weide'], m['payout_weide'], m['odds_365'], d_func)
        if scen is None: continue
        valid += 1
        pred = STRATEGY.get(scen, '')
        if not pred:
            no_pred += 1
            continue
        hit = check_hit(pred, m['result_dir'], is_home)
        if hit: dual_hit += 1
        if has_d:
            d_total += 1
            if hit: d_hit += 1
        if label == 'NEW':
            scen_old, _, _ = classify(m['kelly_365'], m['payout_365'], m['kelly_weide'], m['payout_weide'], m['odds_365'], d_old)
            if scen_old != scen:
                changed.append(f"  {m['home']} vs {m['away']}: {scen_old}→{scen} | {STRATEGY.get(scen_old,'?')}→{pred} | result={m['result_dir']} {'✓' if hit else '✗'}")
    return valid, dual_hit, d_total, d_hit, no_pred, changed

print("="*60)
print("V6策略回测 - D状态修复前后对比")
print("策略表来源: 策略文档6.2速查表")
print("="*60)

for label, func in [("修复前", d_old), ("修复后", d_new)]:
    valid, dual_hit, d_total, d_hit, no_pred, _ = run(func, label)
    effective = valid - no_pred
    print(f"\n【{label}】")
    print(f"  总场次: {len(matches)}, 有效: {valid}, 无策略: {no_pred}, 实际对比: {effective}")
    print(f"  双选命中: {dual_hit}/{effective} = {dual_hit/effective*100:.1f}%")
    if d_total:
        print(f"  D状态: {d_total}场, 命中: {d_hit}/{d_total} = {d_hit/d_total*100:.1f}%")

# Changes detail
_, _, _, _, _, changed = run(d_new, 'NEW')
if changed:
    print(f"\n{'='*60}")
    print(f"修复影响（{len(changed)}场变化）:")
    for c in changed:
        print(c)
else:
    print(f"\n修复前后无变化")

# 分范畴统计
print(f"\n{'='*60}")
print("修复后 - 分范畴统计:")
cat_stats = {1: [0,0], 2: [0,0], 3: [0,0]}
for m in matches:
    scen, _, is_home = classify(m['kelly_365'], m['payout_365'], m['kelly_weide'], m['payout_weide'], m['odds_365'], d_new)
    if not scen: continue
    pred = STRATEGY.get(scen, '')
    if not pred: continue
    hit = check_hit(pred, m['result_dir'], is_home)
    s1, s2 = scen[0], scen[1]
    has_fav = lambda s: s in 'ABC'
    if has_fav(s1) and has_fav(s2): cat = 1
    elif has_fav(s1) or has_fav(s2): cat = 2
    else: cat = 3
    cat_stats[cat][0] += 1
    if hit: cat_stats[cat][1] += 1
for cat in [1,2,3]:
    t, h = cat_stats[cat]
    print(f"  范畴{cat}: {h}/{t} = {h/t*100:.1f}%" if t else f"  范畴{cat}: 0场")
