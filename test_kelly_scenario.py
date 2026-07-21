#!/usr/bin/env python3
"""
测试用例：验证凯利七场景检测引擎
沙佩科vs弗拉门戈数据：
  Bet365: payout=0.93, kelly=1.03/0.95/0.91
  韦德:   payout=0.93, kelly=0.96/0.92/0.93
预期：场景一（主胜两家都不看好），客胜被看好
"""
import sys
import os
import math
import json

# ===== 直接提取需要的函数（避免触发 main()） =====
# 从 daily_predictions.py 提取纯函数

# 复制核心函数
def calc_elo_probs(home_strength, away_strength):
    d = home_strength - away_strength
    hf = 0.5 / (1 + 10 ** (-d / 14))
    df = 0.28 * math.exp(-abs(d) / 18)
    af = 1 - hf - df
    t = hf + df + af
    return {"胜": hf/t, "平": df/t, "负": af/t}

def calc_kelly_probs(w, d, l):
    total = 1/w + 1/d + 1/l
    R = 1/total
    return {"胜": R/w, "平": R/d, "负": R/l}

# ===== 从修改后的文件中提取七场景引擎代码 =====
# 读取文件内容，提取七场景相关函数
script_path = os.path.join(os.path.dirname(__file__), 'codeact', 'scripts', 'daily_predictions.py')
with open(script_path, 'r', encoding='utf-8') as f:
    source = f.read()

# 提取常量和函数定义
exec_globals = {}
# 先定义需要的常量
exec_globals['math'] = math
exec_globals['json'] = json

# 提取从 "# ===== 凯利七场景检测引擎 v5 =====" 到 "def predict_match(" 的代码段
marker1 = "# ===== 凯利七场景检测引擎 v5 ====="
marker2 = "\ndef predict_match("
idx1 = source.index(marker1)
idx2 = source.index(marker2)
kelly_engine_code = source[idx1:idx2]

# 执行代码段以定义所有函数
exec(kelly_engine_code, exec_globals)

# 获取函数引用
calc_kelly_scenario = exec_globals['calc_kelly_scenario']
_k_judge_kelly = exec_globals['_k_judge_kelly']
_k_favored = exec_globals['_k_favored']
_k_bad_dirs = exec_globals['_k_bad_dirs']
_k_is_safe = exec_globals['_k_is_safe']
_K_DIRS = exec_globals['_K_DIRS']
_K_DN = exec_globals['_K_DN']

print("=" * 60)
print("测试1: 沙佩科vs弗拉门戈 - 场景一检测")
print("=" * 60)

# 构造Kelly数据
kelly_companies = {
    "bet365": {
        "kelly_h": 1.03,
        "kelly_d": 0.95,
        "kelly_a": 0.91,
        "payout": 0.93,
    },
    "weide": {
        "kelly_h": 0.96,
        "kelly_d": 0.92,
        "kelly_a": 0.93,
        "payout": 0.93,
    },
}

base_probs = {"hf": 0.40, "df": 0.27, "af": 0.33}

result = calc_kelly_scenario(kelly_companies, base_probs)

print(f"\n场景列表: {result['scenarios']}")
print(f"场景编号: {result['scenario']}")
print(f"场景标签: {result['label']}")
print(f"概率调整: {result['adjustments']}")
print(f"置信度调节: {result['confidence_mod']}")
print(f"Skip: {result['skip']}")
print(f"Pick: {result['pick']}")
print(f"Cover: {result['cover']}")
print(f"离散度: {result['dispersion']}")
print(f"Bet365 Kelly: {result['bet365_kelly']}")
print(f"韦德 Kelly: {result['weide_kelly']}")
if result['finalProbs']:
    print(f"调整后概率: {result['finalProbs']}")

errors = []

# 验证
if result['scenario'] != '1':
    errors.append(f"❌ 场景编号预期为'1'，实际为'{result['scenario']}'")
else:
    print(f"\n✅ 场景编号正确: 1（场景一-两家不看好主胜）")

has_scenario_1 = any('1' in s for s in result['scenarios'])
if not has_scenario_1:
    errors.append(f"❌ 场景列表应包含场景一相关标签，实际: {result['scenarios']}")
else:
    print(f"✅ 场景列表包含场景一: {result['scenarios']}")

if '主胜' not in result['label'] or '不看好' not in result['label']:
    errors.append(f"❌ 标签应包含'不看好主胜'，实际: {result['label']}")
else:
    print(f"✅ 标签正确标识'不看好主胜': {result['label']}")

if result['skip']:
    errors.append(f"❌ 不应skip")
else:
    print(f"✅ 未skip")

# Kelly判断验证
b365 = kelly_companies['bet365']
w = kelly_companies['weide']
assert _k_judge_kelly(b365['kelly_h'], b365['payout']) == 'bad'
assert _k_judge_kelly(b365['kelly_d'], b365['payout']) == 'bad'
assert _k_judge_kelly(b365['kelly_a'], b365['payout']) == 'favor'
print(f"✅ Bet365 Kelly判断正确: h=bad, d=bad, a=favor")

assert _k_judge_kelly(w['kelly_h'], w['payout']) == 'bad'
assert _k_judge_kelly(w['kelly_d'], w['payout']) == 'favor'
assert _k_judge_kelly(w['kelly_a'], w['payout']) == 'ok'
print(f"✅ 韦德 Kelly判断正确: h=bad, d=favor, a=ok")

b365_bad = _k_bad_dirs(b365)
w_bad = _k_bad_dirs(w)
common_bad = [d for d in b365_bad if d in w_bad]
if common_bad != ['h']:
    errors.append(f"❌ commonBad预期['h']，实际{common_bad}")
else:
    print(f"✅ 共同不看好: ['h']（主胜两家都不看好）")

b365_favor = _k_favored(b365)
if 'a' not in b365_favor:
    errors.append(f"❌ Bet365应favor客胜")
else:
    print(f"✅ 客胜被Bet365看好: favor={b365_favor}")

if result['finalProbs']:
    fp = result['finalProbs']
    if fp['af'] > base_probs['af']:
        print(f"✅ 调整后客胜概率提升: {base_probs['af']:.3f} → {fp['af']:.3f}")
    else:
        errors.append(f"❌ 调整后客胜概率未提升: {base_probs['af']:.3f} → {fp['af']:.3f}")

print("\n" + "=" * 60)
print("测试2: 场景七-离散度过高 → skip")
print("=" * 60)

kelly_companies_7 = {
    "bet365": {"kelly_h": 0.85, "kelly_d": 1.05, "kelly_a": 0.98, "payout": 0.93},
    "weide":  {"kelly_h": 1.02, "kelly_d": 0.88, "kelly_a": 0.95, "payout": 0.93},
}
result7 = calc_kelly_scenario(kelly_companies_7, base_probs)
print(f"场景: {result7['scenario']}, Skip: {result7['skip']}, 标签: {result7['label']}")
if result7['skip'] and result7['scenario'] == '7':
    print("✅ 场景七skip检测正确")
else:
    errors.append(f"❌ 场景七预期skip=True,scenario='7'，实际skip={result7['skip']},scenario={result7['scenario']}")

print("\n" + "=" * 60)
print("测试3: 场景零-共同看好")
print("=" * 60)

kelly_companies_0 = {
    "bet365": {"kelly_h": 0.90, "kelly_d": 0.96, "kelly_a": 0.99, "payout": 0.93},
    "weide":  {"kelly_h": 0.91, "kelly_d": 0.95, "kelly_a": 0.98, "payout": 0.93},
}
result0 = calc_kelly_scenario(kelly_companies_0, base_probs)
print(f"场景: {result0['scenario']}, Pick: {result0['pick']}, 标签: {result0['label']}")
if result0['scenario'] == '0' and result0['pick'] == 'h':
    print("✅ 场景零共同看好主胜检测正确")
else:
    errors.append(f"❌ 场景零预期scenario='0',pick='h'，实际scenario={result0['scenario']},pick={result0['pick']}")

print("\n" + "=" * 60)
print("测试4: 场景三-去平局")
print("=" * 60)

# 只有平局被dropped（仅一家不看好平局），主客都safe，无共同favor
kelly_companies_3 = {
    "bet365": {"kelly_h": 0.93, "kelly_d": 0.95, "kelly_a": 0.93, "payout": 0.93},
    "weide":  {"kelly_h": 0.92, "kelly_d": 0.93, "kelly_a": 0.93, "payout": 0.93},
}
# bet365: h=0.93(diff=0,ok), d=0.95(diff=-0.02,bad), a=0.93(diff=0,ok) → favor=[], bad=[d]
# weide: h=0.92(diff=0.01,favor), d=0.93(diff=0,ok), a=0.93(diff=0,ok) → favor=[h], bad=[]
# safe: h(ok,favor→both not bad)✓, d(bad,ok→not safe)✗, a(ok,ok→both not bad)✓ → dropped=['d']
# commonFavor=[] (f365=[], fW=[h]) ✓
# commonBad=[] (b365=[d], bW=[]) ✓
# → 场景三：仅平局被dropped
result3 = calc_kelly_scenario(kelly_companies_3, base_probs)
print(f"场景: {result3['scenario']}, 标签: {result3['label']}")
if result3['scenario'] == '3':
    print("✅ 场景三去平局检测正确")
else:
    errors.append(f"❌ 场景三预期scenario='3'，实际scenario={result3['scenario']}, label={result3['label']}")

print("\n" + "=" * 60)
print("测试5: 场景五-信号矛盾")
print("=" * 60)

# 无共同bad，无共同favor，各看好不同方向
kelly_companies_5 = {
    "bet365": {"kelly_h": 0.90, "kelly_d": 0.96, "kelly_a": 0.93, "payout": 0.93},
    "weide":  {"kelly_h": 0.96, "kelly_d": 0.93, "kelly_a": 0.90, "payout": 0.93},
}
# bet365: h=0.90(diff=0.03,favor), d=0.96(diff=-0.03,bad), a=0.93(diff=0,ok) → favor=[h], bad=[d]
# weide: h=0.96(diff=-0.03,bad), d=0.93(diff=0,ok), a=0.90(diff=0.03,favor) → favor=[a], bad=[h]
# safe: h(favor,bad→weide bad→NOT safe)✗, d(bad,ok→bet365 bad→NOT safe)✗, a(ok,favor→both not bad)✓
# dropped=['h','d']
# commonFavor=[] (f365=[h], fW=[a]) ✓, commonBad=[] (b365=[d], bW=[h]) ✓
# 场景三检查: dropped=['h','d'], 'h' in dropped → 不触发
# 场景五: o365=['h']>=1, oW=['a']>=1 → 触发 ✓
result5 = calc_kelly_scenario(kelly_companies_5, base_probs)
print(f"场景: {result5['scenario']}, 标签: {result5['label']}")
if result5['scenario'] == '5':
    print("✅ 场景五信号矛盾检测正确")
else:
    errors.append(f"❌ 场景五预期scenario='5'，实际scenario={result5['scenario']}, label={result5['label']}")

# ===== 总结 =====
print("\n" + "=" * 60)
if errors:
    print(f"❌ 测试失败: {len(errors)} 个错误")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print("✅ 全部5个测试通过！")
    sys.exit(0)
