#!/usr/bin/env python3
"""解析用户提供的07-27和07-28赛果文本，更新pre_match_clean_data.json"""

import json
import re
import sys
from datetime import datetime

# 用户提供的赛果文本
raw_text = """135 丹麦超 第1轮 07-27 00:00 完 [10]霍森斯 (0) 1-1 北西兰 [5] 1-1 1 3.90 3.61 1.83 - 欧 亚 析 2推荐 136 挪超 第15轮 07-27 01:15 完 [14]奥勒松 (1) 1-1 维京 [1] 0-1 3 5.11 4.57 1.51 - 欧 亚 析 102推荐 137 罗甲 第2轮 07-27 01:30 完 [16]奇克塞雷达 (1) 0-2 布星 [3] 0-2 0 3.75 3.52 1.86 - 欧 亚 析 2推荐 138 捷甲 第1轮 07-27 02:00 完 [7]赫拉德茨 (0) 2-1 帕杜比斯 [8] 1-0 3 2.00 3.36 3.49 - 欧 亚 析 推荐 139 阿甲 第1轮 07-27 02:00 完 图库曼 (0) 0-0 门多萨 0-0 1 2.79 3.00 2.60 - 欧 亚 析 3推荐 140 波兰甲 第1轮 07-27 02:15 完 [13]克拉科夫 (0) 2-1 卡托威斯 [10] 0-0 3 2.02 3.44 3.35 - 欧 亚 析 1推荐 141 巴西甲 第20轮 07-27 03:00 完 [6]巴伊亚 (0) 1-1 科林蒂安 [7] 1-1 1 2.32 3.14 3.07 - 欧 亚 析 8推荐 142 智利甲 第16轮 07-27 03:00 完 [8]纽夫莱 (0) 2-0 帕莱斯蒂诺 [5] 2-0 3 2.29 3.18 2.96 - 欧 亚 析 1推荐 143 巴西乙 第20轮 07-27 03:00 完 1 [10]圣贝纳多 (0) 3-4 塞阿拉 [18] 1-0 0 2.24 2.84 3.43 - 欧 亚 析 1推荐 144 巴西乙 第20轮 07-27 03:00 完 [1]克里丘马 (-1) 0-0 累航海 [13] 0-0 0 1.51 3.77 6.13 - 欧 亚 析 6推荐 145 冰岛超 第16轮 07-27 03:15 完 [3]弗拉姆 (-1) 0-0 哈夫纳夫 [11] 0-0 0 1.51 4.74 4.46 - 欧 亚 析 推荐 146 冰岛超 第16轮 07-27 03:15 完 [9]阿克拉内斯 (0) 5-1 加尔达贝尔 [8] 3-0 3 2.20 3.94 2.58 - 欧 亚 析 推荐 147 阿甲 第1轮 07-27 04:15 完 拉普大学 (0) 0-2 阿独立 0-0 0 2.14 2.91 3.77 - 欧 亚 析 4推荐 148 巴西甲 第20轮 07-27 05:30 完 [16]格雷米奥 (0) 1-1 弗鲁米嫩 [4] 0-0 1 3.28 3.18 2.19 - 欧 亚 析 102推荐 149 巴西甲 第20轮 07-27 05:30 完 [2]弗拉门戈 (-1) 1-1 圣保罗 [12] 0-0 0 1.44 4.30 6.84 - 欧 亚 析 134推荐 150 智利甲 第16轮 07-27 05:30 完 [13]意大利人 (0) 1-2 智利大学 [3] 0-1 0 3.40 3.45 1.99 - 欧 亚 析 2推荐 151 巴西乙 第20轮 07-27 05:30 完 [20]米内罗美洲 (0) 1-0 戈亚斯 [7] 0-0 3 2.56 2.85 2.88 - 欧 亚 析 5推荐 152 巴西乙 第20轮 07-27 05:30 完 [16]隆迪那 (0) 1-4 诺瓦桑蒂诺 [6] 1-3 0 3.43 3.17 2.07 - 欧 亚 析 推荐 153 巴西甲 第20轮 07-27 06:30 完 [1]帕梅拉斯 (-1) 1-2 米竞技 [13] 0-0 0 1.59 3.66 5.85 - 欧 亚 析 9推荐 154 巴西甲 第20轮 07-27 06:30 完 [19]雷莫 (0) 2-0 维多利亚 [11] 1-0 3 2.35 3.23 2.92 - 欧 亚 析 3推荐 155 阿甲 第1轮 07-27 06:30 完 利斯特雷 (0) 3-0 博卡 3-0 3 4.13 2.78 2.10 - 欧 亚 析 4推荐 156 墨西超 第2轮 07-27 07:00 完 [8]内卡萨 (0) 2-1 蒙特雷 [7] 1 0-0 3 3.35 3.59 1.99 - 欧 亚 析 4推荐 157 智利甲 第16轮 07-27 08:30 完 [14]康塞普森 (0) 2-0 希金斯 [10] 1 1-0 3 1.80 3.47 4.16 - 欧 亚 析 5推荐 158 墨西超 第2轮 07-27 09:06 完 [5]帕丘卡 (-1) 1-2 克雷塔罗 [15] 1-0 0 1.66 3.69 4.78 - 欧 亚 析 20推荐 159 罗甲 第2轮 07-27 23:30 完 [15]克卢日 (-1) 5-0 沃伦塔利 [13] 1 3-0 3 1.81 3.42 4.09 - 欧 亚 析 39推荐 160 捷甲 第1轮 07-28 00:00 完 1 [9]利森 (0) 2-4 博莱 [8] 1-2 0 3.24 3.44 2.07 - 欧 亚 析 21推荐 161 挪超 第15轮 07-28 01:00 完 [10]罗森博格 (-1) 4-0 费特斯塔 [12] 2-0 3 1.52 4.24 5.61 - 欧 亚 析 203推荐 162 丹麦超 第1轮 07-28 01:00 完 [8]兰讷斯 (-1) 1-1 锡尔克堡 [9] 1-1 0 1.68 3.97 4.43 - 欧 亚 析 15推荐 163 瑞典超 第14轮 07-28 01:00 完 [4]赫根 (0) 0-0 索尔纳 [7] 0-0 1 1.88 3.96 3.41 - 欧 亚 析 180推荐 164 波兰甲 第1轮 07-28 01:00 完 [11]卢宾 (0) 2-0 格里维治 [12] 0-0 3 2.57 3.11 2.68 - 欧 亚 析 17推荐 165 挪甲 第15轮 07-28 01:00 完 [4]斯塔贝克 (-1) 6-0 赫德 [6] 3-0 3 1.36 5.07 6.33 - 欧 亚 析 10推荐 166 瑞典超甲 第16轮 07-28 01:00 完 [14]厄勒布鲁 (0) 0-0 奥迪沃特 [10] 1 0-0 1 2.61 3.35 2.44 - 欧 亚 析 10推荐 167 瑞典超甲 第16轮 07-28 01:05 完 [7]厄斯特什 (0) 3-0 瓦尔贝里 [2] 0-0 3 2.87 3.51 2.19 - 欧 亚 析 9推荐 168 冰岛超 第16轮 07-28 02:00 完 [4]贝雷达比 (-1) 1-0 埃亚尔 [8] 0-0 1 1.65 4.14 4.03 - 欧 亚 析 29推荐 169 罗甲 第2轮 07-28 02:30 完 [12]博托沙尼 (0) 1-1 布特快速 [6] 1 0-1 1 2.92 3.12 2.34 - 欧 亚 析 7推荐 170 冰岛超 第16轮 07-28 03:15 完 [10]KA阿古雷 (-1) 0-0 托尔 [12] 0-0 0 1.56 4.31 4.48 - 欧 亚 析 14推荐 171 巴西乙 第20轮 07-28 06:30 完 [12]雷加塔斯 (0) 2-0 维拉诺瓦 [3] 2-0 3 1.92 3.27 3.78 - 欧 亚 析 13推荐 172 巴西乙 第20轮 07-28 06:30 完 [8]戈亚尼亚 (0) 3-1 铁路工人 [2] 2-1 3 2.03 3.07 3.70 - 欧 亚 析 19推荐 173 智利甲 第16轮 07-28 07:00 完 [16]拉卡莱拉联 (0) 1-1 埃弗顿 [8] 0-0 1 2.70 3.16 2.50 - 欧 亚 析 12推荐"""

# 方向映射
DIR_MAP = {"0": "负", "1": "平", "3": "胜"}

# 解析赛果
# 模式：匹配 编号 联赛 轮次 日期 时间 完 [排名]主队(让球) 比分 客队 [排名] 半场 方向
# 更灵活的模式：跳过编号，匹配日期 + 时间 + 主队 + 比分 + 客队 + 半场 + 方向
pattern = re.compile(
    r'\d{3}\s+.*?\s+.*?\s+(\d{2}-\d{2})\s+(\d{2}:\d{2})\s+完\s+.*?'
    r'(?:\[?\d*\]?\s*)?'  # 排名
    r'([^\s(]+)'  # 主队名
    r'\s*\([^)]*\)\s*'  # 让球
    r'(\d+)-(\d+)'  # 比分
    r'\s+'  # 空格
    r'([^\s\[]+)'  # 客队名 (去掉排名)
    r'\s*.*?'  # 跳过排名
    r'\s+(\d+-\d+)\s+'  # 半场比分
    r'([013])\s+'  # 方向
)

results = []
for line in raw_text.strip().split('\n'):
    line = line.strip()
    if not line:
        continue
    
    m = pattern.search(line)
    if m:
        date = m.group(1)  # 07-27
        time = m.group(2)  # 00:00
        home = m.group(3).strip()
        home_goals = int(m.group(4))
        away_goals = int(m.group(5))
        away = m.group(6).strip()
        half_score = m.group(7)
        direction_code = m.group(8)
        
        # 清理客队名中的排名后缀
        away = re.sub(r'\s*\[\d+\]$', '', away).strip()
        
        direction = DIR_MAP[direction_code]
        full_score = f"{home_goals}-{away_goals}"
        
        results.append({
            "date": date,
            "time": time,
            "home": home,
            "away": away,
            "direction": direction,
            "full_score": full_score,
            "home_goals": home_goals,
            "away_goals": away_goals,
            "half_score": half_score
        })

print(f"解析到 {len(results)} 场比赛结果")

# 加载数据文件
data_path = "/app/data/所有对话/主对话/fp-repo/data/pre_match_clean_data.json"
with open(data_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"数据集共 {len(data)} 场比赛")

# 匹配并更新
matched = 0
unmatched_results = []
for match in data:
    if match.get("result") and match.get("full_score"):
        continue  # 已有赛果，跳过
    
    match_date = match.get("match_time", "").split(" ")[0]  # "07-25"
    home = match.get("home", "").strip()
    away = match.get("away", "").strip()
    
    # 尝试匹配
    for r in results:
        if r["date"] == match_date:
            # 队名匹配
            r_home = r["home"]
            r_away = r["away"]
            
            # 直接匹配
            if home == r_home and away == r_away:
                match["result"] = r["direction"]
                match["full_score"] = r["full_score"]
                match["home_goals"] = r["home_goals"]
                match["away_goals"] = r["away_goals"]
                match["half_score"] = r["half_score"]
                matched += 1
                break
    
    if not match.get("result"):
        unmatched_results.append({
            "match_id": match["match_id"],
            "match_name": match["match_name"],
            "match_time": match["match_time"],
            "home": home,
            "away": away
        })

print(f"\n匹配成功: {matched} 场")
print(f"未匹配: {len(unmatched_results)} 场")

if unmatched_results:
    print("\n未匹配的比赛:")
    for m in unmatched_results:
        print(f"  {m['match_id']}: {m['match_name']} ({m['match_time']})")

# 统计更新后的赛果覆盖情况
date_counts = {}
for match in data:
    d = match["match_time"].split(" ")[0]
    if d not in date_counts:
        date_counts[d] = {"total": 0, "with_result": 0}
    date_counts[d]["total"] += 1
    if match.get("result"):
        date_counts[d]["with_result"] += 1

print("\n=== 赛果覆盖统计 ===")
for d in sorted(date_counts.keys()):
    c = date_counts[d]
    print(f"  {d}: {c['with_result']}/{c['total']}")

# 保存
with open(data_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"\n✅ 已保存到 {data_path}")