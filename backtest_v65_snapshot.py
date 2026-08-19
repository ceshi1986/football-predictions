#!/usr/bin/env python3
"""
V6.5 快照回测：使用赛前60-120分钟的Kelly快照数据做预测，对比最终数据命中率
"""
import json, os, re, sys
from datetime import datetime, timedelta
from collections import defaultdict, Counter

REPO = '/Coze/Drive/私人助理小策/所有对话/主对话/fp-repo'
SNAP_DIR = os.path.join(REPO, 'data', '500com_daily')

# ============================================================
# V6.5 策略表（从代码中提取）
# ============================================================
# 场景 -> 双选推荐
_V65_STRATEGY = {
    # 强主
    'AA主': '胜+平', 'AB主': '胜+平', 'AC主': '胜+平',
    'AW主': '胜+平', 'AY主': '胜+平', 'AZ主': '胜+负',
    'BA主': '胜+平', 'BB主': '胜+平', 'BC主': '胜+平',
    'BW主': '胜+平', 'BY主': '胜+平', 'BZ主': '胜+负',
    'CA主': '胜+平', 'CB主': '胜+平', 'CC主': '胜+平',
    'CW主': '胜+平', 'CY主': '胜+平', 'CZ主': '胜+负',
    'WA主': '胜+平', 'WB主': '胜+平', 'WC主': '胜+平',
    'WW主': '胜+平', 'WY主': '胜+平', 'WZ主': '胜+负',
    'YA主': '胜+平', 'YB主': '胜+平', 'YC主': '胜+平',
    'YW主': '胜+平', 'YY主': '胜', 'YZ主': '胜+负',
    'ZA主': '胜+负', 'ZB主': '胜+负', 'ZC主': '胜+负',
    'ZW主': '胜+负', 'ZY主': '胜+负', 'ZZ主': '胜+负',
    # 强客
    'AA客': '胜+负', 'AB客': '胜+负', 'AC客': '胜+负',
    'AW客': '平+负', 'AY客': '胜+负', 'AZ客': '胜+负',
    'BA客': '胜+负', 'BB客': '胜+负', 'BC客': '胜+负',
    'BW客': '胜+负', 'BY客': '胜+负', 'BZ客': '胜+负',
    'CA客': '胜+负', 'CB客': '胜+负', 'CC客': '胜+负',
    'CW客': '胜+负', 'CY客': '胜+负', 'CZ客': '胜+负',
    'WA客': '平+负', 'WB客': '平+负', 'WC客': '平+负',
    'WW客': '平+负', 'WY客': '平+负', 'WZ客': '平+负',
    'YA客': '平+负', 'YB客': '平+负', 'YC客': '平+负',
    'YW客': '平+负', 'YY客': '负', 'YZ客': '平+负',
    'ZA客': '平+负', 'ZB客': '平+负', 'ZC客': '平+负',
    'ZW客': '平+负', 'ZY客': '平+负', 'ZZ客': '平+负',
}

# ============================================================
# Kelly信号计算
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

def compute_signal(kelly_h, kelly_d, kelly_a, payout, is_strong_home):
    sig = get_signal_from_kelly(kelly_h, kelly_d, kelly_a, payout, is_strong_home)
    if sig == 'D':
        sig = resolve_d_state(kelly_h, kelly_d, kelly_a, is_strong_home)
    return sig

# ============================================================
# 时间解析
# ============================================================
def parse_match_time(time_str, date_str):
    """解析比赛时间，返回datetime
    格式: "MM-DD HH:MM" 或 "YYYY-MM-DD HH:MM"
    date_str: "YYYYMMDD" 是比赛日期"""
    if not time_str:
        return None
    
    time_str = time_str.strip()
    
    # "MM-DD HH:MM"
    m = re.match(r'^(\d{2})-(\d{2})\s+(\d{2}):(\d{2})$', time_str)
    if m:
        month, day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        year = int(date_str[:4])
        return datetime(year, month, day, hour, minute)
    
    # "YYYY-MM-DD HH:MM"
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})$', time_str)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                       int(m.group(4)), int(m.group(5)))
    
    return None

def parse_snapshot_time(filename):
    """从文件名解析快照时间
    kelly_snapshot_HHMMSS.json -> 返回 HH:MM:SS
    500com_kelly_snapshot_HHMMSS.json -> 返回 HH:MM:SS"""
    m = re.search(r'(\d{6})\.json$', filename)
    if m:
        t = m.group(1)
        return int(t[:2]), int(t[2:4]), int(t[4:6])
    return None

# ============================================================
# 快照加载
# ============================================================
def load_snapshot(filepath, date_str):
    """加载快照文件，返回 {snapshot_time: datetime, matches: {match_key: {bet365: (kh,kd,ka,payout), weide: (kh,kd,ka,payout)}}}"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except:
        return None
    
    # 获取快照时间
    scrape_time = None
    
    # 尝试从 meta 获取
    meta = data.get('_snapshot_meta', {})
    if meta and meta.get('snapshot_time'):
        try:
            scrape_time = datetime.strptime(meta['snapshot_time'], '%Y-%m-%d %H:%M:%S')
        except:
            pass
    
    if not scrape_time and data.get('scrape_time'):
        try:
            scrape_time = datetime.strptime(data['scrape_time'], '%Y-%m-%d %H:%M:%S')
        except:
            pass
    
    if not scrape_time and data.get('fetch_time'):
        try:
            scrape_time = datetime.strptime(data['fetch_time'], '%Y-%m-%d %H:%M:%S')
        except:
            pass
    
    # 从文件名推断时间
    fname = os.path.basename(filepath)
    h, m, s = parse_snapshot_time(fname) or (0, 0, 0)
    
    if not scrape_time:
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        try:
            scrape_time = datetime(year, month, day, h, m, s)
        except:
            return None
    
    # 解析比赛Kelly数据
    matches_data = data.get('matches', {})
    if not isinstance(matches_data, dict):
        return None
    
    result_matches = {}
    for mk, mv in matches_data.items():
        if not isinstance(mv, dict):
            continue
        
        match_name = mv.get('match_name', '') or ''
        match_time = mv.get('match_time', '')
        
        # 从match_title中提取名字 (500com格式)
        if not match_name and mv.get('match_title'):
            title = mv['match_title']
            # "格尼斯坦VS埃尔维斯(2026芬超)-百家欧指-500彩票网"
            m_title = re.match(r'^(.+?)VS(.+?)\(', title)
            if m_title:
                match_name = f"{m_title.group(1)} vs {m_title.group(2)}"
        
        companies = mv.get('companies', {})
        if not isinstance(companies, dict):
            continue
        
        # 提取bet365数据
        c365 = companies.get('bet365', {})
        c365_data = extract_kelly(c365)
        
        # 提取weide数据
        cwd = companies.get('weide', {})
        cwd_data = extract_kelly(cwd)
        
        if c365_data and cwd_data:
            result_matches[mk] = {
                'match_name': match_name,
                'match_time': match_time,
                'bet365': c365_data,
                'weide': cwd_data,
            }
    
    return {
        'snapshot_time': scrape_time,
        'matches': result_matches,
    }

def extract_kelly(company_data):
    """从公司数据中提取Kelly值 [h, d, a] 和 payout"""
    if not isinstance(company_data, dict):
        return None
    
    # 旧格式：kelly数组 [h, d, a] + payout
    kelly_arr = company_data.get('kelly')
    payout = company_data.get('payout')
    
    if kelly_arr and isinstance(kelly_arr, list) and len(kelly_arr) >= 3:
        try:
            kh, kd, ka = float(kelly_arr[0]), float(kelly_arr[1]), float(kelly_arr[2])
            p = float(payout) if payout else None
            return {'kh': kh, 'kd': kd, 'ka': ka, 'payout': p}
        except:
            pass
    
    # 新格式：instant_kelly字典 {win:{value}, draw:{value}, lose:{value}} + instant_return
    instant_kelly = company_data.get('instant_kelly')
    instant_return = company_data.get('instant_return')
    
    if instant_kelly and isinstance(instant_kelly, dict):
        try:
            win_val = instant_kelly.get('win', {})
            draw_val = instant_kelly.get('draw', {})
            lose_val = instant_kelly.get('lose', {})
            
            if isinstance(win_val, dict):
                kh = float(win_val.get('value', 0))
                kd = float(draw_val.get('value', 0))
                ka = float(lose_val.get('value', 0))
            else:
                kh = float(win_val)
                kd = float(draw_val)
                ka = float(lose_val)
            
            # payout: instant_return 是百分比字符串如 "92.49%"
            p = None
            if instant_return:
                ret_str = str(instant_return).replace('%', '').strip()
                try:
                    p = float(ret_str) / 100.0
                except:
                    p = None
            
            return {'kh': kh, 'kd': kd, 'ka': ka, 'payout': p}
        except:
            pass
    
    return None

# ============================================================
# 名字匹配
# ============================================================
def normalize_name(name):
    """标准化球队名用于匹配"""
    if not name:
        return ''
    name = name.strip().lower()
    # 去掉特殊字符
    name = re.sub(r'[\s\-_vs./]+', '', name)
    return name

def names_match(name1, name2):
    """检查两个名字是否匹配"""
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)
    if n1 == n2:
        return True
    # 包含关系
    if n1 in n2 or n2 in n1:
        return True
    # 去掉括号内容后比较
    n1_clean = re.sub(r'\(.*?\)', '', n1)
    n2_clean = re.sub(r'\(.*?\)', '', n2)
    if n1_clean == n2_clean:
        return True
    if n1_clean in n2_clean or n2_clean in n1_clean:
        return True
    return False

def find_match_in_snapshot(home, away, snapshot_matches, date_str):
    """在快照中找到匹配的比赛"""
    for mk, mv in snapshot_matches.items():
        mname = mv.get('match_name', '')
        # 解析 "team1 vs team2"
        parts = re.split(r'\s+vs\s+|\s+VS\s+', mname)
        if len(parts) == 2:
            snap_home = parts[0].strip()
            snap_away = parts[1].strip()
        else:
            continue
        
        if names_match(home, snap_home) and names_match(away, snap_away):
            return mk, mv
        # 反向匹配
        if names_match(home, snap_away) and names_match(away, snap_home):
            return mk, mv
    
    return None, None

# ============================================================
# 主逻辑
# ============================================================
def main():
    # 1. 加载主表
    with open(os.path.join(REPO, 'backtest_master_table_dedup.json')) as f:
        master_data = json.load(f)
    records = master_data['detail']
    print(f"回测主表: {len(records)} 场比赛")
    
    # 2. 构建比赛日期->比赛列表映射
    date_matches = defaultdict(list)
    for r in records:
        date_matches[r['date']].append(r)
    
    # 3. 加载所有日期数据，获取比赛时间
    match_times = {}  # (date, home, away) -> datetime
    for date_str in sorted(date_matches.keys()):
        # 从zgzcw_kelly_data获取比赛时间
        kelly_path = os.path.join(SNAP_DIR, date_str, 'zgzcw_kelly_data.json')
        if os.path.exists(kelly_path):
            try:
                with open(kelly_path) as f:
                    kdata = json.load(f)
                for mk, mv in kdata.get('matches', {}).items():
                    mt = parse_match_time(mv.get('match_time', ''), date_str)
                    if mt:
                        mname = mv.get('match_name', '')
                        parts = re.split(r'\s+vs\s+|\s+VS\s+', mname)
                        if len(parts) == 2:
                            snap_home = parts[0].strip()
                            snap_away = parts[1].strip()
                            # 匹配主表中的比赛
                            for r in date_matches[date_str]:
                                key = (r['date'], r['home'], r['away'])
                                if key not in match_times:
                                    if names_match(r['home'], snap_home) and names_match(r['away'], snap_away):
                                        match_times[key] = mt
                                    elif names_match(r['home'], snap_away) and names_match(r['away'], snap_home):
                                        match_times[key] = mt
            except Exception as e:
                print(f"  加载 {date_str} kelly_data 失败: {e}")
        
        # 也从500com_kelly_data获取
        kelly_path2 = os.path.join(SNAP_DIR, date_str, '500com_kelly_data.json')
        if os.path.exists(kelly_path2):
            try:
                with open(kelly_path2) as f:
                    kdata = json.load(f)
                for mk, mv in kdata.get('matches', {}).items():
                    mt = parse_match_time(mv.get('match_time', ''), date_str)
                    if mt:
                        mname = mv.get('match_name', '')
                        parts = re.split(r'\s+vs\s+|\s+VS\s+', mname)
                        if len(parts) == 2:
                            snap_home = parts[0].strip()
                            snap_away = parts[1].strip()
                            for r in date_matches[date_str]:
                                key = (r['date'], r['home'], r['away'])
                                if key not in match_times:
                                    if names_match(r['home'], snap_home) and names_match(r['away'], snap_away):
                                        match_times[key] = mt
            except:
                pass
    
    print(f"找到比赛时间: {len(match_times)}/{len(records)} 场")
    
    # 4. 加载所有快照
    print("\n加载快照文件...")
    date_snapshots = {}  # date -> [snapshot_data, ...]
    for date_str in sorted(date_matches.keys()):
        snap_dir = os.path.join(SNAP_DIR, date_str, 'snapshots')
        if not os.path.isdir(snap_dir):
            continue
        
        snapshots = []
        for fname in sorted(os.listdir(snap_dir)):
            if not fname.endswith('.json'):
                continue
            fpath = os.path.join(snap_dir, fname)
            snap = load_snapshot(fpath, date_str)
            if snap:
                snapshots.append(snap)
        
        # 按时间排序
        snapshots.sort(key=lambda x: x['snapshot_time'])
        date_snapshots[date_str] = snapshots
        if snapshots:
            print(f"  {date_str}: {len(snapshots)} 个快照 "
                  f"({snapshots[0]['snapshot_time'].strftime('%H:%M')} ~ {snapshots[-1]['snapshot_time'].strftime('%H:%M')})")
    
    # 5. 为每场比赛找最佳快照并做预测
    print(f"\n{'='*60}")
    print("开始回测...")
    print(f"{'='*60}")
    
    results = []
    no_match_time = 0
    no_snapshot_dir = 0
    no_suitable_snapshot = 0
    no_match_in_snapshot = 0
    no_kelly_data = 0
    
    for r in records:
        date_str = r['date']
        home = r['home']
        away = r['away']
        actual = r['result']
        key = (date_str, home, away)
        
        # 获取比赛时间
        mt = match_times.get(key)
        if not mt:
            no_match_time += 1
            results.append({
                **r,
                'snap_signal_365': None,
                'snap_signal_weide': None,
                'snap_scenario': None,
                'snap_recommendation': None,
                'snap_hit': None,
                'snap_hit_time': None,
                'snap_offset_min': None,
                'reason': 'no_match_time',
            })
            continue
        
        # 检查是否有快照目录
        if date_str not in date_snapshots or not date_snapshots[date_str]:
            no_snapshot_dir += 1
            results.append({
                **r,
                'snap_signal_365': None,
                'snap_signal_weide': None,
                'snap_scenario': None,
                'snap_recommendation': None,
                'snap_hit': None,
                'snap_hit_time': None,
                'snap_offset_min': None,
                'reason': 'no_snapshot_dir',
            })
            continue
        
        snapshots = date_snapshots[date_str]
        
        # 找赛前60-120分钟的快照
        # 目标：赛前60-120分钟（即赛前1-2小时）
        target_min = 60  # 至少赛前60分钟
        target_max = 120  # 最多赛前120分钟
        
        best_snap = None
        best_offset = None
        
        for snap in snapshots:
            snap_time = snap['snapshot_time']
            offset = (mt - snap_time).total_seconds() / 60.0  # 分钟
            
            # 快照必须在比赛前
            if offset < 0:
                continue
            
            # 优先找60-120分钟的
            if target_min <= offset <= target_max:
                if best_snap is None:
                    best_snap = snap
                    best_offset = offset
                else:
                    # 在这个范围内选最接近60分钟的
                    if abs(offset - 90) < abs(best_offset - 90):
                        best_snap = snap
                        best_offset = offset
        
        # 如果没找到60-120分钟的，找赛前最近的（但要在赛前）
        if best_snap is None:
            for snap in snapshots:
                snap_time = snap['snapshot_time']
                offset = (mt - snap_time).total_seconds() / 60.0
                if offset < 0:
                    continue
                # 放宽条件，赛前0-180分钟
                if offset <= 180:
                    if best_snap is None:
                        best_snap = snap
                        best_offset = offset
                    else:
                        if abs(offset - 90) < abs(best_offset - 90):
                            best_snap = snap
                            best_offset = offset
        
        if best_snap is None:
            no_suitable_snapshot += 1
            results.append({
                **r,
                'snap_signal_365': None,
                'snap_signal_weide': None,
                'snap_scenario': None,
                'snap_recommendation': None,
                'snap_hit': None,
                'snap_hit_time': None,
                'snap_offset_min': None,
                'reason': 'no_suitable_snapshot',
            })
            continue
        
        # 在快照中找这场比赛
        mk, mv = find_match_in_snapshot(home, away, best_snap['matches'], date_str)
        if not mk:
            no_match_in_snapshot += 1
            results.append({
                **r,
                'snap_signal_365': None,
                'snap_signal_weide': None,
                'snap_scenario': None,
                'snap_recommendation': None,
                'snap_hit': None,
                'snap_hit_time': None,
                'snap_offset_min': round(best_offset),
                'reason': 'no_match_in_snapshot',
            })
            continue
        
        # 提取Kelly数据
        c365 = mv['bet365']
        cwd = mv['weide']
        
        if not c365 or not cwd:
            no_kelly_data += 1
            results.append({
                **r,
                'snap_signal_365': None,
                'snap_signal_weide': None,
                'snap_scenario': None,
                'snap_recommendation': None,
                'snap_hit': None,
                'snap_hit_time': None,
                'snap_offset_min': round(best_offset),
                'reason': 'no_kelly_data',
            })
            continue
        
        is_strong_home = r.get('is_strong_home', False)
        
        # 计算信号
        sig_365 = compute_signal(c365['kh'], c365['kd'], c365['ka'], c365['payout'], is_strong_home)
        sig_weide = compute_signal(cwd['kh'], cwd['kd'], cwd['ka'], cwd['payout'], is_strong_home)
        
        if sig_365 == 'X' or sig_weide == 'X':
            no_kelly_data += 1
            results.append({
                **r,
                'snap_signal_365': sig_365,
                'snap_signal_weide': sig_weide,
                'snap_scenario': None,
                'snap_recommendation': None,
                'snap_hit': None,
                'snap_hit_time': best_snap['snapshot_time'].strftime('%H:%M'),
                'snap_offset_min': round(best_offset),
                'reason': 'X_signal',
            })
            continue
        
        scenario = f"{sig_365}{sig_weide}"
        subgroup = f"{scenario}{'主' if is_strong_home else '客'}"
        rec = _V65_STRATEGY.get(subgroup)
        
        # 判断是否命中
        hit = None
        if rec:
            hit = actual in rec.split('+')
        
        results.append({
            **r,
            'snap_signal_365': sig_365,
            'snap_signal_weide': sig_weide,
            'snap_scenario': scenario,
            'snap_subgroup': subgroup,
            'snap_recommendation': rec,
            'snap_hit': hit,
            'snap_hit_time': best_snap['snapshot_time'].strftime('%H:%M'),
            'snap_offset_min': round(best_offset),
            'reason': 'ok',
        })
    
    # 6. 统计结果
    ok_results = [r for r in results if r['reason'] == 'ok']
    hit_results = [r for r in ok_results if r['snap_hit']]
    
    # 对比原始V6.5结果（最终数据）
    original_ok = [r for r in records if r.get('subgroup') and r.get('subgroup') in _V65_STRATEGY]
    
    print(f"\n{'='*60}")
    print(f"快照回测结果")
    print(f"{'='*60}")
    print(f"总比赛数: {len(records)}")
    print(f"可回测（有快照数据）: {len(ok_results)}")
    print(f"  - 无双选命中: {len(ok_results) - len(hit_results)}")
    print(f"  - 双选命中: {len(hit_results)}")
    
    if ok_results:
        snap_double_rate = len(hit_results) / len(ok_results) * 100
        print(f"\n快照双选命中率: {len(hit_results)}/{len(ok_results)} = {snap_double_rate:.1f}%")
    else:
        snap_double_rate = 0
    
    # 统计无法回测的原因
    reason_counts = Counter(r['reason'] for r in results if r['reason'] != 'ok')
    print(f"\n无法回测: {len(results) - len(ok_results)} 场")
    for reason, count in reason_counts.most_common():
        desc = {
            'no_match_time': '无法获取比赛时间',
            'no_snapshot_dir': '该日期无快照数据',
            'no_suitable_snapshot': '无合适的赛前快照',
            'no_match_in_snapshot': '快照中找不到该比赛',
            'no_kelly_data': 'Kelly数据无效或为X信号',
        }.get(reason, reason)
        print(f"  - {desc}: {count}")
    
    # 按offset分布统计
    offsets = [r['snap_offset_min'] for r in ok_results if r['snap_offset_min'] is not None]
    if offsets:
        print(f"\n快照时间分布（距开赛分钟数）:")
        bins = [(0, 30), (30, 60), (60, 90), (90, 120), (120, 180)]
        for lo, hi in bins:
            count = sum(1 for o in offsets if lo <= o < hi)
            hits = sum(1 for r in ok_results if r['snap_offset_min'] is not None and lo <= r['snap_offset_min'] < hi and r['snap_hit'])
            rate = hits/count*100 if count > 0 else 0
            print(f"  {lo}-{hi}分钟: {count}场, 命中{hits}场 ({rate:.1f}%)")
    
    # 按场景统计
    scene_stats = defaultdict(lambda: {'total': 0, 'hits': 0})
    for r in ok_results:
        sg = r.get('snap_subgroup', '')
        if sg:
            scene_stats[sg]['total'] += 1
            if r['snap_hit']:
                scene_stats[sg]['hits'] += 1
    
    if scene_stats:
        print(f"\n{'='*60}")
        print("各场景命中率")
        print(f"{'='*60}")
        for sg in sorted(scene_stats.keys()):
            s = scene_stats[sg]
            rate = s['hits']/s['total']*100 if s['total'] > 0 else 0
            print(f"  {sg}: {s['hits']}/{s['total']} = {rate:.1f}%")
    
    # 7. 保存详细结果
    output = {
        'summary': {
            'total_matches': len(records),
            'backtestable': len(ok_results),
            'double_hit': len(hit_results),
            'double_hit_rate': round(snap_double_rate, 1),
            'not_backtestable': len(results) - len(ok_results),
            'reasons': dict(reason_counts),
        },
        'results': results,
    }
    
    outpath = os.path.join(REPO, 'backtest_v65_snapshot_result.json')
    with open(outpath, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存到: {outpath}")
    
    return output

if __name__ == '__main__':
    main()
