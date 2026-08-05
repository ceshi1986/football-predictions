#!/usr/bin/env python3
"""
回测：立博超低Kelly的命中率（不限365韦德是否矛盾）
"""
import json
import os
import glob
from collections import defaultdict

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_result(score_h, score_a):
    if score_h > score_a:
        return 'H'
    elif score_h < score_a:
        return 'A'
    else:
        return 'D'

def main():
    # 加载赛果
    results = load_json('/app/data/所有对话/主对话/fp-repo/data/match_results.json')
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
                    all_snapshots.append(load_json(snap_file))
                except:
                    pass
    
    print(f"加载了 {len(all_snapshots)} 个快照")
    
    # 统计：立博最低Kelly的方向命中率
    processed = set()
    libo_min_cases = []
    
    # 按阈值分组
    thresholds = [0.80, 0.82, 0.85, 0.88, 0.90]
    threshold_stats = {t: {'hits': 0, 'total': 0, 'cases': []} for t in thresholds}
    
    for snap in all_snapshots:
        snap_date = snap['date']
        
        for match_id, match_data in snap.get('matches', {}).items():
            match_name = match_data.get('match_name', '')
            jingcai_id = match_data.get('jingcai_id', '')
            
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
            if match_key in processed:
                continue
            processed.add(match_key)
            
            result = result_index[result_key]
            companies = match_data.get('companies', {})
            libo = companies.get('libo', {})
            
            if not libo:
                continue
            
            klb = libo.get('kelly', [])
            plb = libo.get('payout', 0.9)
            
            if len(klb) < 3:
                continue
            
            # 找立博最低Kelly方向
            libo_min = min(klb)
            libo_min_idx = klb.index(libo_min)
            libo_dir = ['H', 'D', 'A'][libo_min_idx]
            hit = (libo_dir == result)
            
            case = {
                'date': snap_date,
                'jingcai_id': jingcai_id,
                'match': match_name[:25],
                'klb': klb,
                'plb': plb,
                'libo_min': libo_min,
                'libo_dir': libo_dir,
                'result': result,
                'hit': hit
            }
            libo_min_cases.append(case)
            
            # 按阈值统计
            for t in thresholds:
                if libo_min <= t:
                    threshold_stats[t]['total'] += 1
                    if hit:
                        threshold_stats[t]['hits'] += 1
                    threshold_stats[t]['cases'].append(case)
    
    # 输出结果
    print(f"\n{'='*70}")
    print(f"回测结果：立博最低Kelly方向命中率（所有比赛）")
    print(f"{'='*70}")
    print(f"总比赛数（有立博数据且有赛果）: {len(libo_min_cases)}")
    
    print(f"\n按立博最低Kelly阈值分组:")
    print(f"{'阈值':<8} {'命中':<6} {'总数':<6} {'命中率':<10} {'平均最低K':<12}")
    print(f"{'-'*50}")
    
    for t in sorted(thresholds):
        stats = threshold_stats[t]
        if stats['total'] > 0:
            rate = stats['hits'] / stats['total'] * 100
            avg_min = sum(c['libo_min'] for c in stats['cases']) / stats['total']
            print(f"≤{t:<6} {stats['hits']:<6} {stats['total']:<6} {rate:>5.1f}%     {avg_min:.3f}")
    
    # 详细案例（≤0.85）
    print(f"\n{'='*70}")
    print(f"立博最低Kelly ≤ 0.85 的详细案例:")
    print(f"{'='*70}")
    for c in threshold_stats[0.85]['cases']:
        status = "✅" if c['hit'] else "❌"
        print(f"{c['date']} {c['jingcai_id']:8s} {c['match']:25s} | "
              f"LB K={c['klb'][0]:.2f}/{c['klb'][1]:.2f}/{c['klb'][2]:.2f} "
              f"payout={c['plb']:.2f} | "
              f"最低:{c['libo_dir']}(K={c['libo_min']:.2f}) | "
              f"结果:{c['result']} {status}")
    
    # 对比：365和韦德最低Kelly方向命中率
    print(f"\n{'='*70}")
    print(f"对比：365和韦德最低Kelly方向命中率")
    print(f"{'='*70}")
    
    for company_name, company_key in [('365', 'bet365'), ('韦德', 'weide')]:
        processed2 = set()
        cases = []
        for snap in all_snapshots:
            snap_date = snap['date']
            for match_id, match_data in snap.get('matches', {}).items():
                match_name = match_data.get('match_name', '')
                jingcai_id = match_data.get('jingcai_id', '')
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
                if match_key in processed2:
                    continue
                processed2.add(match_key)
                
                result = result_index[result_key]
                companies = match_data.get('companies', {})
                comp = companies.get(company_key, {})
                if not comp:
                    continue
                k = comp.get('kelly', [])
                p = comp.get('payout', 0.9)
                if len(k) < 3:
                    continue
                
                k_min = min(k)
                k_dir = ['H', 'D', 'A'][k.index(k_min)]
                hit = (k_dir == result)
                cases.append({'k_min': k_min, 'hit': hit})
        
        # 按阈值统计
        print(f"\n{company_name} 最低Kelly方向命中率:")
        for t in [0.85, 0.88, 0.90]:
            filtered = [c for c in cases if c['k_min'] <= t]
            if filtered:
                hits = sum(1 for c in filtered if c['hit'])
                total = len(filtered)
                rate = hits / total * 100
                print(f"  ≤{t}: {hits}/{total} = {rate:.1f}%")

if __name__ == '__main__':
    main()
