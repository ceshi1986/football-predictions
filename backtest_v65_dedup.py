#!/usr/bin/env python3
"""
V6.5去重回测脚本
1. 从backtest_v64_detail.json去重（按mid保留首次）
2. 用V6.5策略回测去重后的数据
3. 计算每个场景的胜平负概率，更新单选推荐
"""
import json
from collections import defaultdict

def main():
    base_dir = '/Coze/Drive/私人助理小策/所有对话/主对话/fp-repo'
    
    # 加载原始回测数据
    with open(f'{base_dir}/backtest_v64_detail.json', 'r') as f:
        data = json.load(f)
    
    details = data['details']
    print(f"原始数据: {len(details)} 场")
    
    # 1. 去重（按mid保留首次）
    seen_mids = set()
    deduped = []
    for d in details:
        mid = d.get('mid')
        if mid not in seen_mids:
            seen_mids.add(mid)
            deduped.append(d)
        else:
            print(f"  去重: {d['date']} {d['home']} vs {d['away']} (mid={mid})")
    
    print(f"去重后: {len(deduped)} 场 (去除 {len(details) - len(deduped)} 场重复)")
    
    # 2. 用V6.5策略回测
    # V6.5 = V6.4 + Override修正
    # 从backtest_v64_detail.json中读取每个match的recommendation和hit
    # 统计每个场景的双选命中率
    
    scenario_stats = defaultdict(lambda: {
        'total': 0, 
        'hits': 0, 
        'win': 0, 
        'draw': 0, 
        'lose': 0,
        'recommendations': []
    })
    
    for d in deduped:
        scene = d.get('scene')
        is_home = d.get('is_home')
        if not scene or is_home is None:
            continue
        
        # 构建子组名称
        subgroup = f"{scene}{'主' if is_home else '客'}"
        
        # 获取推荐和命中情况（V6.4已经包含了V6.5的override）
        rec = d.get('rec_v64')
        hit = d.get('hit_v64')
        
        # 获取实际赛果
        score = d.get('score', '')
        if '-' in score:
            parts = score.split('-')
            try:
                score_h, score_a = int(parts[0]), int(parts[1])
                if score_h > score_a:
                    actual = '胜'
                elif score_h == score_a:
                    actual = '平'
                else:
                    actual = '负'
            except:
                continue
        else:
            continue
        
        # 统计
        scenario_stats[subgroup]['total'] += 1
        if hit:
            scenario_stats[subgroup]['hits'] += 1
        
        if actual == '胜':
            scenario_stats[subgroup]['win'] += 1
        elif actual == '平':
            scenario_stats[subgroup]['draw'] += 1
        else:
            scenario_stats[subgroup]['lose'] += 1
        
        scenario_stats[subgroup]['recommendations'].append({
            'rec': rec,
            'hit': hit,
            'actual': actual
        })
    
    # 3. 计算每个场景的胜平负概率
    print(f"\n===== V6.5去重回测结果 =====")
    print(f"有效回测场次: {sum(s['total'] for s in scenario_stats.values())}")
    
    total_hits = sum(s['hits'] for s in scenario_stats.values())
    total_matches = sum(s['total'] for s in scenario_stats.values())
    overall_rate = total_hits / total_matches * 100 if total_matches > 0 else 0
    
    print(f"双选命中: {total_hits}/{total_matches} = {overall_rate:.1f}%\n")
    
    # 4. 计算每个场景的胜平负概率和单选推荐
    subgroup_data = {}
    
    for subgroup, stats in sorted(scenario_stats.items()):
        total = stats['total']
        if total == 0:
            continue
        
        win_rate = stats['win'] / total * 100
        draw_rate = stats['draw'] / total * 100
        lose_rate = stats['lose'] / total * 100
        double_rate = stats['hits'] / total * 100
        
        # 确定最佳单选
        directions = [('胜', win_rate), ('平', draw_rate), ('负', lose_rate)]
        directions.sort(key=lambda x: x[1], reverse=True)
        best_single = directions[0][0]
        best_single_rate = directions[0][1]
        
        # 确定双选推荐（选覆盖率最高的组合，且必须包含单选）
        # 三种双选组合
        combos = [
            ('胜+平', win_rate + draw_rate),
            ('胜+负', win_rate + lose_rate),
            ('平+负', draw_rate + lose_rate)
        ]
        
        # 优先选包含best_single的组合
        best_combo = None
        best_combo_rate = 0
        
        for combo, rate in combos:
            if best_single in combo:
                if rate > best_combo_rate:
                    best_combo = combo
                    best_combo_rate = rate
        
        # 如果没有找到包含best_single的组合（理论上不会发生），选最高的
        if best_combo is None:
            combos.sort(key=lambda x: x[1], reverse=True)
            best_combo = combos[0][0]
            best_combo_rate = combos[0][1]
        
        subgroup_data[subgroup] = {
            'total': total,
            'win': stats['win'],
            'draw': stats['draw'],
            'lose': stats['lose'],
            'win_rate': round(win_rate, 1),
            'draw_rate': round(draw_rate, 1),
            'lose_rate': round(lose_rate, 1),
            'double_select': best_combo,
            'double_hit_rate': round(best_combo_rate, 1),
            'best_single': best_single,
            'best_single_rate': round(best_single_rate, 1)
        }
        
        print(f"{subgroup} ({total}场):")
        print(f"  胜平负: {win_rate:.1f}% / {draw_rate:.1f}% / {lose_rate:.1f}%")
        print(f"  双选: {best_combo} ({best_combo_rate:.1f}%)")
        print(f"  单选: {best_single} ({best_single_rate:.1f}%)")
    
    # 5. 保存结果
    output = {
        'total_matches': len(deduped),
        'deduped_matches': len(deduped),
        'removed_duplicates': len(details) - len(deduped),
        'valid_backtest': total_matches,
        'total_hits': total_hits,
        'overall_hit_rate': round(overall_rate, 1),
        'subgroup_data': subgroup_data
    }
    
    output_path = f'{base_dir}/backtest_v65_dedup_result.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n结果已保存到: {output_path}")
    
    # 6. 验证一致性
    print(f"\n===== 一致性验证 =====")
    issues = []
    for subgroup, data in subgroup_data.items():
        single = data['best_single']
        double = data['double_select']
        single_rate = data['best_single_rate']
        double_rate = data['double_hit_rate']
        
        # 检查单选是否在双选范围内
        if single not in double:
            issues.append(f"{subgroup}: 单选'{single}'不在双选'{double}'范围内")
        
        # 检查单选率是否<=双选率
        if single_rate > double_rate:
            issues.append(f"{subgroup}: 单选率{single_rate}%>双选率{double_rate}%")
    
    if issues:
        print(f"发现 {len(issues)} 个问题:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("✓ 所有子组数据一致，无逻辑矛盾")
    
    return output

if __name__ == '__main__':
    main()
