#!/usr/bin/env python3
"""
回测：365和韦德信号矛盾时，立博超低Kelly的命中率
"""
import json
import os
import glob
from datetime import datetime

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def classify_signal(kelly, payout):
    """根据Kelly和payout分类信号"""
    k_h, k_d, k_a = kelly
    fav = []
    if k_h <= payout:
        fav.append('H')
    if k_d <= payout:
        fav.append('D')
    if k_a <= payout:
        fav.append('A')
    
    if len(fav) == 0:
        return 'none', fav
    elif set(fav) == {'H', 'D'}:
        return '1H', fav  # 主不败
    elif set(fav) == {'D', 'A'}:
        return '1A', fav  # 客不败
    elif set(fav) == {'H'}:
        return 'pure_H', fav  # 纯主胜
    elif set(fav) == {'A'}:
        return 'pure_A', fav  # 纯客胜
    elif set(fav) == {'H', 'A'}:
        return 'qu_ping', fav  # 去平
    else:
        return 'other', fav

def get_result(score_h, score_a):
    if score_h > score_a:
        return 'H'
    elif score_h < score_a:
        return 'A'
    else:
        return 'D'

def main():
    # 加载赛果
    results_path = '/app/data/所有对话/主对话/fp-repo/data/match_results.json'
    results = load_json(results_path)
    
    # 建立赛果索引 (date, home, away) -> result
    result_index = {}
    for r in results:
        key = (r['date'], r['home'], r['away'])
        result_index[key] = get_result(r['score_h'], r['score_a'])
    
    # 加载所有快照
    snapshot_dir = '/app/data/所有对话/主对话/fp-repo/data/500com_daily/'
    all_snapshots = []
    for date_folder in sorted(glob.glob(os.path.join(snapshot_dir, '2026*'))):
        snap_dir = os.path.join(date_folder, 'snapshots')
        if os.path.exists(snap_dir):
            for snap_file in sorted(glob.glob(os.path.join(snap_dir, 'kelly_snapshot_*.json'))):
                try:
                    snap = load_json(snap_file)
                    all_snapshots.append(snap)
                except:
                    pass
    
    print(f"加载了 {len(all_snapshots)} 个快照")
    
    # 统计变量
    total_disagree = 0
    libo_low_kelly_cases = []
    
    # 遍历快照，找赛前最新数据
    processed_matches = set()
    
    for snap in all_snapshots:
        snap_date = snap['date']
        scrape_time_str = snap['scrape_time']
        
        for match_id, match_data in snap.get('matches', {}).items():
            match_name = match_data.get('match_name', '')
            jingcai_id = match_data.get('jingcai_id', '')
            
            # 解析比赛时间
            match_time_str = match_data.get('match_time', '')
            if not match_time_str:
                continue
            
            # 构建赛果key
            parts = match_name.split(' vs ')
            if len(parts) != 2:
                parts = match_name.split(' VS ')
            if len(parts) != 2:
                continue
            
            home, away = parts[0].strip(), parts[1].strip()
            result_key = (snap_date, home, away)
            
            if result_key not in result_index:
                continue
            
            match_key = (snap_date, match_name)
            if match_key in processed_matches:
                continue
            processed_matches.add(match_key)
            
            result = result_index[result_key]
            
            # 获取365、韦德、立博的数据
            companies = match_data.get('companies', {})
            bet365 = companies.get('bet365', {})
            weide = companies.get('weide', {})
            libo = companies.get('libo', {})
            
            if not all([bet365, weide, libo]):
                continue
            
            k365 = bet365.get('kelly', [])
            p365 = bet365.get('payout', 0.9)
            kwd = weide.get('kelly', [])
            pwd = weide.get('payout', 0.9)
            klb = libo.get('kelly', [])
            plb = libo.get('payout', 0.9)
            
            if len(k365) < 3 or len(kwd) < 3 or len(klb) < 3:
                continue
            
            # 分类365和韦德的信号
            sig365, fav365 = classify_signal(k365, p365)
            sigwd, favwd = classify_signal(kwd, pwd)
            
            # 判断是否矛盾（信号方向不同）
            # 矛盾定义：一家看好主(①H或pure_H)，另一家看好客(①A或pure_A)，或一家去平另一家相反
            is_disagree = False
            if sig365 in ['1H', 'pure_H'] and sigwd in ['1A', 'pure_A']:
                is_disagree = True
            elif sig365 in ['1A', 'pure_A'] and sigwd in ['1H', 'pure_H']:
                is_disagree = True
            elif sig365 == 'qu_ping' and sigwd in ['1H', 'pure_H', '1A', 'pure_A']:
                is_disagree = True
            elif sigwd == 'qu_ping' and sig365 in ['1H', 'pure_H', '1A', 'pure_A']:
                is_disagree = True
            # 也包含：一家①H，另一家纯主胜（这不算矛盾，算①H混合）
            # 也包含：两家都去平（场景③）
            
            if not is_disagree:
                continue
            
            total_disagree += 1
            
            # 找立博最低Kelly方向
            libo_kelly_min = min(klb)
            libo_min_idx = klb.index(libo_kelly_min)
            libo_direction = ['H', 'D', 'A'][libo_min_idx]
            
            # 判断立博是否有超低Kelly (≤0.85)
            if libo_kelly_min <= 0.85:
                # 检查立博超低Kelly方向是否命中
                hit = (libo_direction == result)
                
                libo_low_kelly_cases.append({
                    'date': snap_date,
                    'match': match_name,
                    'jingcai_id': jingcai_id,
                    'sig365': sig365,
                    'k365': k365,
                    'p365': p365,
                    'sigwd': sigwd,
                    'kwd': kwd,
                    'pwd': pwd,
                    'siglb': classify_signal(klb, plb)[0],
                    'klb': klb,
                    'plb': plb,
                    'libo_min_kelly': libo_kelly_min,
                    'libo_direction': libo_direction,
                    'result': result,
                    'hit': hit
                })
    
    # 输出结果
    print(f"\n{'='*60}")
    print(f"回测结果：365和韦德矛盾时，立博超低Kelly命中率")
    print(f"{'='*60}")
    print(f"365和韦德信号矛盾的比赛总数: {total_disagree}")
    print(f"其中立博Kelly≤0.85的比赛数: {len(libo_low_kelly_cases)}")
    
    if libo_low_kelly_cases:
        hits = sum(1 for c in libo_low_kelly_cases if c['hit'])
        total = len(libo_low_kelly_cases)
        hit_rate = hits / total * 100 if total > 0 else 0
        
        print(f"\n立博超低Kelly命中率: {hits}/{total} = {hit_rate:.1f}%")
        
        print(f"\n详细案例:")
        print(f"{'-'*80}")
        for c in libo_low_kelly_cases:
            status = "✅命中" if c['hit'] else "❌未中"
            print(f"{c['date']} {c['jingcai_id']:8s} {c['match'][:20]:20s} | "
                  f"365:{c['sig365']:6s} WD:{c['sigwd']:6s} | "
                  f"LB最低:{c['libo_direction']} K={c['libo_min_kelly']:.2f} | "
                  f"结果:{c['result']} {status}")
        
        # 按立博方向分组统计
        print(f"\n按立博超低Kelly方向分组:")
        from collections import defaultdict
        dir_stats = defaultdict(lambda: {'hits': 0, 'total': 0})
        for c in libo_low_kelly_cases:
            d = c['libo_direction']
            dir_stats[d]['total'] += 1
            if c['hit']:
                dir_stats[d]['hits'] += 1
        
        for d, stats in dir_stats.items():
            rate = stats['hits'] / stats['total'] * 100 if stats['total'] > 0 else 0
            print(f"  方向{d}: {stats['hits']}/{stats['total']} = {rate:.1f}%")
    else:
        print("\n没有找到符合条件的案例")

if __name__ == '__main__':
    main()
