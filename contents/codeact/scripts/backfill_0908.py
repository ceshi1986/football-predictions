#!/usr/bin/env python3
"""
V6.9.2 赛果回填脚本（2026-09-08）
- 解析两批手动赛果（9/2-9/4粘贴文本单行格式 + 9/4-9/7多行tab格式）
- 回填回测表33条未判定记录（8/30-9/3）
- 9/4-9/7锁定预测：V6.9.2字母判定+D状态13拆分+72表→匹配赛果→追加detail
用法: python3 backfill_0908.py [--apply]
"""
import json, os, re, sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAILY = os.path.join(BASE, 'data', '500com_daily')
BT_PATH = os.path.join(BASE, 'backtest_master_table_dedup.json')
PASTE_TXT = os.path.join(BASE, 'data', 'manual_results', 'results_0902_0904_paste.txt')
TXT_363 = "/Coze/Drive/私人助理小策/1 K2联赛 第25轮 09-04 18 30 完 [13]_1788800499620_0_rdrr.txt"
TXT_BLOCK = os.path.join(BASE, 'data', 'manual_results', 'results_0830_0907_block.txt')

# ============ V6.9.2 72子组表 ============
TABLE72 = {
 'AA主':'胜平','AA客':'负胜','AB主':'平胜','AB客':'负平','AC主':'胜负','AC客':'胜平',
 'AW主':'胜负','AW客':'胜负','AY主':'胜平','AY客':'平胜','AZ主':'负平','AZ客':'负胜',
 'BA主':'胜平','BA客':'平负','BB主':'胜平','BB客':'平负','BC主':'胜平','BC客':'负胜',
 'BW主':'胜平','BW客':'负胜','BY主':'胜平','BY客':'平负','BZ主':'胜负','BZ客':'胜平',
 'CA主':'胜负','CA客':'负胜','CB主':'胜平','CB客':'平负','CC主':'胜负','CC客':'负胜',
 'CW主':'胜负','CW客':'负平','CY主':'胜平','CY客':'平负','CZ主':'胜负','CZ客':'胜负',
 'WA主':'胜平','WA客':'平负','WB主':'胜平','WB客':'平负','WC主':'胜平','WC客':'负胜',
 'WW主':'胜平','WW客':'平负','WY主':'胜平','WY客':'负胜','WZ主':'胜负','WZ客':'胜平',
 'YA主':'胜负','YA客':'胜负','YB主':'胜平','YB客':'平负','YC主':'胜负','YC客':'负平',
 'YW主':'胜平','YW客':'胜平','YY主':'平胜','YY客':'平负','YZ主':'平负','YZ客':'负平',
 'ZA主':'胜平','ZA客':'负胜','ZB主':'胜平','ZB客':'平负','ZC主':'胜负','ZC客':'胜负',
 'ZW主':'胜平','ZW客':'胜负','ZY主':'平负','ZY客':'胜平','ZZ主':'胜负','ZZ客':'胜负',
}

# D状态13拆分：返回该公司保留方向集合(h,d,a)
# kelly=[kh,kd,ka]
def d_split(kelly, is_home_strong):
    kh, kd, ka = kelly
    eps = 1e-9
    h_eq_d = abs(kh-kd)<eps; d_eq_a = abs(kd-ka)<eps; h_eq_a = abs(kh-ka)<eps
    if h_eq_d and d_eq_a:  # 1 h=d=a 去掉强队负
        return {'h','d'} if is_home_strong else {'h','d'}  # B主/B客→保留h,d
    if h_eq_a and kh>kd:  # 2 h=a>d → d
        return {'d'}
    if d_eq_a and kd>kh:  # 3 d=a>h → h
        return {'h'}
    if h_eq_d and kh>ka:  # 4 h=d>a → a
        return {'a'}
    if h_eq_d and kh<ka:  # 5 h=d<a → h,d
        return {'h','d'}
    if h_eq_a and kh<kd:  # 6 h=a<d → h,a
        return {'h','a'}
    if d_eq_a and kd<kh:  # 7 d=a<h → d,a
        return {'d','a'}
    # 全不等：看排序
    if kh>kd>ka or kh>ka>kd:  # 8 h>d>a / 9 h>a>d → d,a
        return {'d','a'}
    if kd>kh>ka or kd>ka>kh:  # 10 d>h>a / 11 d>a>h → h,a
        return {'h','a'}
    if ka>kh>kd or ka>kd>kh:  # 12 a>h>d / 13 a>d>h → h,d
        return {'h','d'}
    return {'h','d','a'}

# 方向集合→字母
def dirs_to_letter(dirs, is_home_strong):
    s = frozenset(dirs)
    m = {
        frozenset({'h'}): ('A','Z'),
        frozenset({'h','d'}): ('B','W'),
        frozenset({'h','a'}): ('Y','Y'),
        frozenset({'d'}): ('Z','Z'),
        frozenset({'a'}): ('C','A'),
        frozenset({'d','a'}): ('W','B'),
        frozenset({'h','d','a'}): ('D','D'),
        frozenset(): ('X','X'),
    }
    t = m.get(s)
    return t[0] if is_home_strong else t[1] if t else 'X'

def classify(lock):
    """V6.9.2 判定，返回 dict 或 None"""
    comps = lock.get('companies', {})
    c365, cw = comps.get('bet365') or {}, comps.get('weide') or {}
    k365, kw = c365.get('kelly'), cw.get('kelly')
    p365, pw = c365.get('payout'), cw.get('payout')
    odds = c365.get('latest_odds')
    if not k365 or not kw or not odds or len(k365)<3 or len(kw)<3 or len(odds)<3:
        return None
    if p365 is None or pw is None:
        return None
    is_home_strong = odds[0] <= odds[2]
    def letters(kelly, payout):
        dset = {d for d,v in zip(('h','d','a'), kelly) if v <= payout + 0.001}
        L = dirs_to_letter(dset, is_home_strong)
        raw = L
        if L == 'D':
            dset2 = d_split(kelly, is_home_strong)
            L = dirs_to_letter(dset2, is_home_strong)
        return L, raw
    L365, raw365 = letters(k365, p365)
    Lw, raww = letters(kw, pw)
    if 'X' in (L365, Lw) or 'D' in (L365, Lw):
        return None
    scenario = L365 + Lw
    suffix = '主' if is_home_strong else '客'
    subgroup = scenario + suffix
    prediction = TABLE72.get(subgroup)
    if not prediction:
        return None
    # Kelly≥1.0排除（韦德）
    excl = set()
    if kw[0] >= 1.0: excl.add('胜')
    if kw[2] >= 1.0: excl.add('负')
    # 平K≥1.0不排除
    final_pred = ''.join(ch for ch in prediction if ch not in excl)
    if not final_pred:
        final_pred = prediction  # 排无可排则保留原双选
    return {
        'scenario': scenario, 'sig_365': L365, 'sig_weide': Lw,
        'sig_365_raw': raw365, 'sig_weide_raw': raww,
        'strong': 'home' if is_home_strong else 'away',
        'is_strong_home': is_home_strong, 'subgroup': subgroup,
        'prediction': final_pred, 'double_select': final_pred,
        'pred_type': 'V6.9',
        'kelly_365': k365[:3], 'kelly_weide': kw[:3], 'odds_365': odds[:3],
    }

# ============ 赛果解析 ============
def clean_team(s):
    s = re.sub(r'\([+-]?\d+(?:/\d+)?\)', '', s)   # 让球
    s = re.sub(r'\[\d+\]', '', s)                   # 排名
    s = re.sub(r'^\d+(?=[^\dA-Za-z])', '', s)      # 开头杂散数字（数字+中文）
    s = re.sub(r'^\d+', '', s)                      # 纯数字开头
    s = re.sub(r'(?<=[^\dA-Za-z])\d$', '', s)      # 中文队名后杂散数字（保护96/1905/04）
    return s.strip()

def raw_result(sh, sa):
    return '胜' if sh>sa else ('平' if sh==sa else '负')

def parse_oneline(text):
    """单行格式（粘贴文本）"""
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln: continue
        m = re.search(r'(\d{2})-(\d{2})\s+(\d{2}):(\d{2})\s+完\s+', ln)
        if not m: continue
        date = f"2026{m.group(1)}{m.group(2)}"
        rest = ln[m.end():]
        # 全场比分：找第一个 X-Y（半场比分在其后，形式"X - Y"）
        sm = re.search(r'(\d+)\s*-\s*(\d+)', rest)
        if not sm: continue
        sh, sa = int(sm.group(1)), int(sm.group(2))
        # 队名：比分前为主队段，比分后到半场比分前为客队段
        before = rest[:sm.start()]
        after = rest[sm.end():]
        # 半场比分"X - Y"
        hm = re.search(r'\d+\s*-\s*\d+', after)

        away_raw = after[:hm.start()] if hm else after
        away_raw = re.split(r'\s{2,}|\t', away_raw)[0]
        home = clean_team(before)
        away = clean_team(away_raw)
        out.append({'date': date, 'home': home, 'away': away,
                    'score_h': sh, 'score_a': sa, 'result': raw_result(sh, sa)})
    return out

def parse_multiline(path):
    """多行tab格式（363场文件）：每条3行
    行1: seq\t联赛\t轮次\t时间\t状态\t主队
    行2: 全场比分 X-Y
    行3: 客队\t半场比分\t赔率\t让球赛果\t...
    """
    with open(path, encoding='utf-8-sig') as f:
        lines = [l.rstrip('\n').rstrip('\r') for l in f]
    out = []
    i = 0
    while i < len(lines):
        parts = lines[i].split('\t')
        if len(parts) >= 6 and parts[0].strip().isdigit():
            league = parts[1].strip()
            tstr = parts[3].strip()
            status = parts[4].strip()
            home_line = parts[5].strip()
            score_line = lines[i+1].strip() if i+1 < len(lines) else ''
            line3 = lines[i+2].split('\t') if i+2 < len(lines) else []
            tm = re.match(r'(\d{2})-(\d{2})\s+(\d{2}):(\d{2})', tstr)
            sm = re.match(r'(\d+)\s*-\s*(\d+)$', score_line)
            if tm and status == '完' and sm and line3:
                sh, sa = int(sm.group(1)), int(sm.group(2))
                away = clean_team(line3[0])
                home = clean_team(home_line)
                out.append({
                    'date': f"2026{tm.group(1)}{tm.group(2)}",
                    'home': home, 'away': away,
                    'score_h': sh, 'score_a': sa,
                    'result': raw_result(sh, sa),
                    'league': league, 'seq': parts[0].strip(),
                })
            i += 4 if lines[i+3:i+4] and lines[i+3].strip()=='置顶' else 3
        else:
            i += 1
    return out

def parse_block(path):
    """逐字段一行格式（8/30-8/31完赛列表，178_1788808678816）
    每条约16-17行：序号/联赛/轮次/时间/状态/主队/主分/-/客分/客队/半场/赔率/让球赛果/图片/析亚欧推荐/[置顶]/图片
    改期/中断场比分为占位符，自动跳过。
    """
    with open(path, encoding='utf-8-sig') as f:
        lines = [l.rstrip('\n').rstrip('\r') for l in f]
    out = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.isdigit() and i+5 < len(lines):
            league = lines[i+1].strip()
            tstr = lines[i+3].strip()
            status = lines[i+4].strip()
            tm = re.match(r'(\d{2})-(\d{2})\s+(\d{2}):(\d{2})$', tstr)
            if tm:
                home_line = lines[i+5].strip()
                j = None
                for k in range(i+6, min(i+19, len(lines))):
                    if lines[k].strip() == '-':
                        j = k; break
                if j is not None:
                    sh_l = lines[j-1].strip()
                    sa_l = lines[j+1].strip()
                    away_l = lines[j+2].strip() if j+2 < len(lines) else ''
                    if status == '完' and sh_l.isdigit() and sa_l.isdigit():
                        out.append({
                            'date': f"2026{tm.group(1)}{tm.group(2)}",
                            'home': clean_team(home_line), 'away': clean_team(away_l),
                            'score_h': int(sh_l), 'score_a': int(sa_l),
                            'result': raw_result(int(sh_l), int(sa_l)),
                            'league': league, 'seq': s,
                        })
                    i = j + 3
                    continue
        i += 1
    return out

# ============ 队名模糊匹配 ============
ALIAS = {
    '奥德赫维里鲁汶':'旧海弗莱鲁汶', '乔治罗尼亚':'雅盖隆', '米德尔斯堡':'米堡',
    '加的夫城':'卡迪夫城', '西布罗姆':'西布朗维奇', '雷克斯':'雷克瑟姆',
    '卡洛治':'卡鲁日星', '乌契':'洛桑乌契', '女王巡游':'女王公园巡游者',
    '奥斯纳':'奥斯纳布吕克',
    # 8/30-8/31批次译名差异（统一到500万完赛表写法）
    '曼联':'曼彻斯特联', '伊普斯':'伊普斯维奇',
    '卡萨比亚':'卡萨皮亚', '莫雷拉人':'摩雷伦斯',
    '费尔格拉斯':'费尔盖拉斯', '查维斯':'沙维什',
    '里斯本竞技':'葡萄牙体育', '法鲁人':'法伦斯',
    '瓦鲁尔':'瓦路尔',
    '奥达科斯':'奥达克斯意大利人',
    '阿尔多斯维':'阿尔多希维',
    '门多萨独立':'里瓦达维亚独立', '竞技':'竞技俱乐部',
}
def norm(s):
    if not s: return ''
    for k,v in ALIAS.items():
        s = s.replace(k,v)
    return s.replace(' ','').replace('FC','').replace('cf','').lower()

def team_match(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb: return False
    if na == nb: return True
    if len(na)>=3 and (na in nb or nb in na): return True
    # 字符重合度
    sa, sb = set(na), set(nb)
    if sa and len(sa & sb)/max(len(sa|sb),1) >= 0.7: return True
    return False

def find_result(home, away, date, results):
    """同日期优先，前后放宽1天"""
    cands = []
    for r in results:
        if abs(int(r['date']) - int(date)) <= 1:
            cands.append(r)
    for r in cands:
        if team_match(home, r['home']) and team_match(away, r['away']):
            return r
    # 主客互换保护
    for r in cands:
        if team_match(home, r['away']) and team_match(away, r['home']):
            return r
    return None

def hit_of(pred, result):
    return result in pred

# ============ 主流程 ============
def main():
    apply = '--apply' in sys.argv
    NOW = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 1. 解析赛果
    with open(PASTE_TXT, encoding='utf-8') as f:
        res1 = parse_oneline(f.read())
    res2 = parse_multiline(TXT_363)
    res3 = parse_block(TXT_BLOCK)
    results = res1 + res2 + res3
    print(f"赛果解析: 粘贴{len(res1)}场 + 363文件{len(res2)}场 + 逐行块{len(res3)}场 = {len(results)}场")
    from collections import Counter
    print("日期分布:", dict(sorted(Counter(r['date'] for r in results).items())))

    # 2. 蛙跳ID集合（按日期）
    frog = {}
    for d in os.listdir(DAILY):
        fp = os.path.join(DAILY, d, 'frog_jump_latest.json')
        if os.path.exists(fp):
            try:
                fj = json.load(open(fp, encoding='utf-8'))
                ids = set(fj.get('frog_jumps', {}).keys())
                frog[d] = ids
            except Exception:
                frog[d] = set()

    # 3. 打开回测表
    bt = json.load(open(BT_PATH, encoding='utf-8'))
    det = bt['detail']

    # 3a. 回填33条未判定
    unfilled = [r for r in det if r.get('result') is None]
    print(f"\n未判定记录: {len(unfilled)}条")
    filled_now, still_missing = 0, []
    for rec in unfilled:
        m = find_result(rec['home'], rec['away'], rec['date'], results)
        if not m:
            still_missing.append(rec)
            continue
        rec['score_h'] = m['score_h']
        rec['score_a'] = m['score_a']
        rec['result'] = m['result']
        rec['actual_result'] = m['result']
        rec['hit'] = hit_of(rec.get('double_select') or rec.get('prediction') or '', m['result'])
        filled_now += 1
    print(f"已回填: {filled_now}条; 仍缺: {len(still_missing)}条")
    for r in still_missing:
        print(f"  缺 {r['date']} {r['home']} vs {r['away']} ({r.get('subgroup')})")

    # 4. 9/4-9/7 锁定预测 → 新增
    existing = set()
    for r in det:
        existing.add((r['date'], norm(r['home']), norm(r['away'])))
    new_recs = []
    seen_locks = set()
    frog_skipped = 0
    no_result = []
    skipped_nodata = 0
    for d in ['20260830','20260831','20260904','20260905','20260906','20260907']:
        lp = os.path.join(DAILY, d, 'locked_predictions.json')
        if not os.path.exists(lp): continue
        locks = json.load(open(lp, encoding='utf-8'))
        frog_ids = frog.get(d, set())
        # 去重：同一场多key，按 (home,away,match_time) 去重
        uniq = {}
        for key, lk in locks.items():
            if not lk.get('home') or not lk.get('away'):
                continue
            sig = (norm(lk['home']), norm(lk['away']), lk.get('match_time',''))
            if sig in seen_locks: continue
            # 蛙跳跳过（fixture id / 竞彩编号 命中蛙跳名单）
            if key in frog_ids:
                seen_locks.add(sig); frog_skipped += 1; continue
            uniq[sig] = (key, lk)
        for sig,(key,lk) in uniq.items():
            seen_locks.add(sig)
            cls = classify(lk)
            if not cls:
                skipped_nodata += 1
                continue
            # 已在回测表（按队名+日期±1）？
            already = any((abs(int(r['date'])-int(d))<=1 and norm(r['home'])==sig[0] and norm(r['away'])==sig[1])
                          for r in det if r.get('result') is not None or r.get('score_h') is not None)
            m = find_result(lk['home'], lk['away'], d, results)
            if not m:
                no_result.append((d, lk['home'], lk['away'], cls['subgroup'], cls['prediction']))
                continue
            if already:
                continue
            rec = {
                'date': d,
                'home': lk['home'], 'away': lk['away'],
                'score_h': m['score_h'], 'score_a': m['score_a'],
                'result': m['result'], 'actual_result': m['result'],
                'scenario': cls['scenario'], 'strong': cls['strong'],
                'is_strong_home': cls['is_strong_home'],
                'subgroup': cls['subgroup'],
                'sig_365': cls['sig_365'], 'sig_weide': cls['sig_weide'],
                'sig_365_raw': cls['sig_365_raw'], 'sig_weide_raw': cls['sig_weide_raw'],
                'hit': hit_of(cls['prediction'], m['result']),
                'double_select': cls['prediction'],
                'match_id': key if key.isdigit() else '',
                'league': m.get('league',''),
                'prediction': cls['prediction'], 'pred_type': 'V6.9.2',
                'kelly_365': cls['kelly_365'], 'kelly_weide': cls['kelly_weide'],
                'odds_365': cls['odds_365'],
                'locked_at': lk.get('locked_at'),
                'created_at': NOW,
                'updated_at': NOW,
            }
            new_recs.append(rec)
    print(f"\n新增可判定记录: {len(new_recs)}条; 蛙跳跳过: {frog_skipped}; 数据不足跳过: {skipped_nodata}")
    print(f"有预测但无赛果(未完赛/未匹配): {len(no_result)}")
    for x in no_result[:20]:
        print("  无果:", x)
    hits = sum(1 for r in new_recs if r['hit'])
    print(f"新增命中: {hits}/{len(new_recs)} = {hits/max(len(new_recs),1)*100:.2f}%")
    # 子组分布抽查
    print("\n新增记录明细:")
    for r in sorted(new_recs, key=lambda x:(x['date'],x['subgroup'])):
        flag = '✅' if r['hit'] else '❌'
        print(f"  {flag} {r['date']} {r['home']} {r['score_h']}-{r['score_a']} {r['away']} | {r['subgroup']} 选{r['double_select']} 果{r['result']}")

    if apply:
        import shutil
        bak = BT_PATH + f'.bak_20260908_{datetime.now().strftime("%H%M%S")}'
        shutil.copy(BT_PATH, bak)
        print(f"\n备份: {bak}")
        det.extend(new_recs)
        judged = [r for r in det if r.get('result') in ('胜','平','负') and r.get('hit') is not None]
        hits_all = sum(1 for r in judged if r['hit'])
        bt['total_matches'] = len(det)
        bt['total'] = len(det)
        bt['total_judged'] = len(judged)
        bt['total_hits'] = hits_all
        bt['hit_rate'] = round(hits_all/len(judged)*100, 2)
        bt['last_updated'] = NOW
        bt['updated_at'] = NOW
        json.dump(bt, open(BT_PATH,'w',encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f"已写回: 总{len(det)} 判定{len(judged)} 命中{hits_all} 命中率{bt['hit_rate']}%")
    else:
        print("\n[dry-run] 未写回。加 --apply 执行写回。")

if __name__ == '__main__':
    main()
