#!/usr/bin/env python3
"""
V6.4策略完整回测脚本 - 2252场比赛
"""
import json
import os
import re
import glob
from collections import defaultdict

# ============================================================
# 1. 数据加载
# ============================================================

def load_match_results(path):
    with open(path) as f:
        return json.load(f)

def load_kelly_data(base_dir, date):
    """加载某日期的Kelly数据，优先zgzcw_kelly_data.json，其次kelly_data_full.json"""
    date_dir = os.path.join(base_dir, date)
    if not os.path.isdir(date_dir):
        return None
    
    # 优先zgzcw
    z_path = os.path.join(date_dir, 'zgzcw_kelly_data.json')
    if os.path.exists(z_path):
        with open(z_path) as f:
            data = json.load(f)
        return ('zgzcw', data)
    
    # 其次kelly_data_full
    k_path = os.path.join(date_dir, 'kelly_data_full.json')
    if os.path.exists(k_path):
        with open(k_path) as f:
            data = json.load(f)
        return ('full', data)
    
    return None

# ============================================================
# 2. 队名标准化与匹配
# ============================================================

def normalize_name(name):
    """标准化队名"""
    if not name:
        return ""
    # 去掉括号内容
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'（.*?）', '', name)
    # 去掉排名数字（如 "1. ", "10. "）
    name = re.sub(r'^\d+\.\s*', '', name)
    # 去掉数字
    name = re.sub(r'\d+', '', name)
    # 去掉盘口相关内容
    name = re.sub(r'[↑↓→]', '', name)
    # 去掉多余空格
    name = name.strip()
    return name

def fuzzy_match(k_name, result_name):
    """模糊匹配两个队名"""
    k = normalize_name(k_name)
    r = normalize_name(result_name)
    if not k or not r:
        return False
    if k == r:
        return True
    if k in r or r in k:
        return True
    # 编辑距离<3
    if edit_distance(k, r) < 3:
        return True
    # 检查是否共享至少一个较长词
    k_words = set(k.split())
    r_words = set(r.split())
    common = k_words & r_words
    if common:
        for w in common:
            if len(w) >= 2:
                return True
    return False

def edit_distance(s1, s2):
    """Levenshtein距离"""
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]

# ============================================================
# 3. 盘口映射
# ============================================================

HANDICAP_MAP = {
    '平手': 0, '平手/半球': 0.25, '平/半': 0.25,
    '半球': 0.5, '半球/一球': 0.75, '半/一': 0.75,
    '一球': 1.0, '一球/球半': 1.25, '一/球半': 1.25,
    '球半': 1.5, '球半/两球': 1.75, '球半/两': 1.75,
    '两球': 2.0, '两球/两球半': 2.25, '两/两半': 2.25,
    '两球半': 2.5, '两球半/三球': 2.75, '两半/三': 2.75,
    '三球': 3.0, '三球/三球半': 3.25, '三/三半': 3.25,
    '三球半': 3.5, '三球半/四球': 3.75, '三半/四': 3.75,
    '四球': 4.0, '四球/四球半': 4.25, '四/四半': 4.25,
    '四球半': 4.5,
}

def parse_handicap(h_str):
    """解析盘口字符串为数值。受让为负值。"""
    if not h_str:
        return None
    # 清理箭头
    h_str = re.sub(r'[↑↓]', '', h_str).strip()
    # 受让
    is_reverse = False
    if h_str.startswith('受'):
        is_reverse = True
        h_str = h_str[1:]
    val = HANDICAP_MAP.get(h_str)
    if val is None:
        return None
    return -val if is_reverse else val

# ============================================================
# 4. 策略核心逻辑
# ============================================================

def get_company_kelly(companies, key):
    """从companies中提取指定公司的Kelly数据。兼容两种格式。"""
    # 直接匹配
    if key in companies:
        c = companies[key]
        if isinstance(c, dict):
            return c
        if isinstance(c, list) and len(c) > 0:
            return c[0]
    # 模糊匹配
    for k, v in companies.items():
        if key.lower() in k.lower() or k.lower() in key.lower():
            if isinstance(v, dict):
                return v
            if isinstance(v, list) and len(v) > 0:
                return v[0]
    return None

def get_bet365(companies):
    """获取Bet365数据"""
    for k in ['bet365', 'Bet365', '365', '36*', '36*']:
        c = get_company_kelly(companies, k)
        if c:
            return c
    return None

def get_weide(companies):
    """获取韦德数据"""
    for k in ['weide', '韦德', '韦*', 'Weide']:
        c = get_company_kelly(companies, k)
        if c:
            return c
    return None

def get_macau_handicap(companies_or_ah, fmt_type):
    """获取澳门亚盘数据"""
    if fmt_type == 'zgzcw':
        # companies dict
        if isinstance(companies_or_ah, dict):
            c = get_company_kelly(companies_or_ah, 'macau')
            if c and 'asian_handicap' in c:
                return c['asian_handicap']
            return None
        return None
    else:
        return None

def get_macau_ah_from_list(ah_list):
    """从asian_handicap列表中找澳门"""
    if not ah_list:
        return None
    for a in ah_list:
        cn = a.get('company_name', '')
        if '澳' in cn:
            return a
    return None

def determine_strong_team(bet365_data):
    """根据365最新赔率确定强队方。胜赔低=主队强，负赔低=客队强。"""
    if not bet365_data:
        return None, None  # is_strong_home, strong_side
    odds_h = bet365_data.get('latest_odds', bet365_data.get('odds_h', [0,0,0]))
    if isinstance(odds_h, list):
        if len(odds_h) >= 3:
            h, d, a = odds_h[0], odds_h[1], odds_h[2]
        else:
            return None, None
    elif isinstance(odds_h, dict):
        h = odds_h.get('h', odds_h.get('odds_h', 0))
        d = odds_h.get('d', odds_h.get('odds_d', 0))
        a = odds_h.get('a', odds_h.get('odds_a', 0))
    else:
        return None, None
    
    if h <= 0 or a <= 0:
        return None, None
    
    if h < a:
        return True, 'home'  # 主队强
    elif a < h:
        return False, 'away'  # 客队强
    else:
        return None, None  # 平赔

def get_kelly_values(company_data):
    """提取Kelly三值和返还率"""
    if not company_data:
        return None, None, None, None
    
    kh = company_data.get('kelly_h', company_data.get('kelly', [None,None,None]))
    kd = company_data.get('kelly_d', None)
    ka = company_data.get('kelly_a', None)
    payout = company_data.get('payout', None)
    
    if isinstance(kh, list) and len(kh) >= 3:
        return kh[0], kh[1], kh[2], payout if payout else company_data.get('payout')
    
    return kh, kd, ka, payout

def get_signal_from_kelly(kh, kd, ka, payout, is_strong_home):
    """
    从Kelly值获取强队视角信号字母。
    返回: A/B/C/Y/Z/W/D/X
    """
    if kh is None or kd is None or ka is None or payout is None:
        return 'X'
    
    # 判断每个方向是否看好（K ≤ payout）
    fav_h = kh <= payout
    fav_d = kd <= payout
    fav_a = ka <= payout
    
    raw = set()
    if fav_h:
        raw.add('胜')
    if fav_d:
        raw.add('平')
    if fav_a:
        raw.add('负')
    
    if len(raw) == 0:
        return 'X'
    
    # 强队视角映射
    if is_strong_home:
        # 强队是主队
        mapping = {
            frozenset(['胜']): 'A',
            frozenset(['胜', '平']): 'B',
            frozenset(['胜', '负']): 'C',
            frozenset(['平']): 'Y',
            frozenset(['负']): 'Z',
            frozenset(['平', '负']): 'W',
            frozenset(['胜', '平', '负']): 'D',
        }
    else:
        # 强队是客队
        mapping = {
            frozenset(['胜']): 'Z',
            frozenset(['胜', '平']): 'W',
            frozenset(['胜', '负']): 'C',
            frozenset(['平']): 'Y',
            frozenset(['负']): 'A',
            frozenset(['平', '负']): 'B',
            frozenset(['胜', '平', '负']): 'D',
        }
    
    return mapping.get(frozenset(raw), 'X')

def resolve_d_state(kh, kd, ka, is_strong_home):
    """
    处理D状态（三方向全看好），按13种情形映射。
    返回转换为的字母。
    """
    if kh is None or kd is None or ka is None:
        return 'X'
    
    # 13种情形
    # ① 三值相等
    if kh == kd == ka:
        return 'B'  # 去掉强队负
    
    # ② 两高相等+一低
    if kh == kd and kh > ka:
        # a(客胜)最低
        return 'Z' if is_strong_home else 'A'
    if kh == ka and kh > kd:
        # d(平)最低
        return 'Y'
    if kd == ka and kd > kh:
        # h(主胜)最低
        return 'A' if is_strong_home else 'Z'
    
    # ③ 两低相等+一高
    if kh == kd and kh < ka:
        # h,d保留 → B(强队主) or W(强队客)
        return 'B' if is_strong_home else 'W'
    if kh == ka and kh < kd:
        # h,a保留 → C
        return 'C'
    if kd == ka and kd < kh:
        # d,a保留 → W(强队主) or B(强队客)
        return 'W' if is_strong_home else 'B'
    
    # ④ 三值不同 - 移除最高值
    max_val = max(kh, kd, ka)
    if max_val == kh:
        # 移除h，保留d,a → W(强队主) or B(强队客)
        return 'W' if is_strong_home else 'B'
    elif max_val == kd:
        # 移除d，保留h,a → C
        return 'C'
    else:
        # 移除a，保留h,d → B(强队主) or W(强队客)
        return 'B' if is_strong_home else 'W'

# ============================================================
# 5. 场景速查表（与 daily_predictions.py 保持一致）
# ============================================================

# V6 36场景策略表: (365_state, weide_state) → (prediction_strong_view, hit_rate%)
# prediction 为强队视角（胜=强队胜，负=强队负）
V6_SCENARIO_TABLE = {
    # 范畴一（两家都含强队胜方向A/B/C）
    ('A','A'): ('胜平', 81.0), ('A','B'): ('胜平', 90.9), ('A','C'): ('胜平', 88.9),
    ('B','A'): ('胜平', 69.0), ('B','B'): ('胜平', 81.8), ('B','C'): ('胜平', 73.9),
    ('C','A'): ('胜负', 80.0), ('C','B'): ('胜平', 83.3), ('C','C'): ('胜负', 85.7),
    # 范畴二（一家含A/B/C，另一家含W/Y/Z）
    ('A','W'): ('胜平', 66.7), ('A','Y'): ('胜平', 66.7), ('A','Z'): ('胜负', 100.0),
    ('B','W'): ('胜平', 100.0), ('B','Y'): ('胜平', 100.0), ('B','Z'): ('胜平', 88.9),
    ('C','W'): ('平负', 83.3), ('C','Y'): ('胜平', 100.0), ('C','Z'): ('胜负', 100.0),
    ('W','A'): ('胜平', 89.5), ('W','B'): ('胜平', 83.3), ('W','C'): ('胜负', 72.7),
    ('Y','A'): ('胜负', 100.0), ('Y','B'): ('胜平', 100.0), ('Y','C'): ('胜负', 100.0),
    ('Z','A'): ('胜负', 75.0), ('Z','B'): ('胜平', 100.0), ('Z','C'): ('胜负', 100.0),
    # 范畴三（两家都不含强队胜方向）
    ('W','W'): ('胜平', 76.9), ('W','Y'): ('胜负', 100.0), ('W','Z'): ('胜负', 90.9),
    ('Y','W'): ('平负', 100.0), ('Y','Y'): ('平胜', 0.0), ('Y','Z'): ('胜负', 100.0),
    ('Z','W'): ('胜负', 100.0), ('Z','Y'): ('平负', 100.0), ('Z','Z'): ('负胜', 100.0),
}

# 强队视角 → 主队视角 转换（强队=客队时使用）
# 强队胜=客队胜=主队负, 强队平=平, 强队负=客队负=主队胜
_STRONG_TO_HOME_CONVERT = {
    '胜平': '平负', '胜负': '负胜', '平胜': '平胜',
    '负胜': '胜负', '平负': '平胜', '负平': '平负',
}

# V6.5 Override修正表（与 daily_predictions.py _V65_OVERRIDES 一致）
# 格式: (scene_code, is_home_strong) -> prediction_home_view（主队视角）
V65_OVERRIDES = {
    ('ZA', True):  '胜负',   ('AZ', True):  '平负',
    ('WZ', False): '胜平',   ('AW', False): '平负',   ('AW', True):  '胜负',
    ('CW', False): '平负',   ('CW', True):  '胜负',   ('WW', False): '平负',
    ('YC', False): '负平',   ('YZ', True):  '胜平',
    ('AA', False): '平负',   ('BZ', False): '胜平',   ('BZ', True):  '胜负',
    ('WC', False): '胜负',   ('WC', True):  '胜平',
    ('BC', False): '胜负',   ('BC', True):  '胜平',
    ('BW', False): '胜平',   ('WY', True):  '胜平',
    ('YB', True):  '胜平',   ('BB', False): '胜负',
    ('BA', True):  '胜负',   ('YW', True):  '胜平',
    ('ZW', True):  '胜平',
}

def get_recommendation(scene_code, is_home_strong):
    """
    获取场景推荐（主队视角）。
    逻辑与 daily_predictions.py 完全一致：
    1. 查 V6_SCENARIO_TABLE（强队视角）
    2. AA/WW 特殊处理
    3. 应用 V65_OVERRIDES（主队视角）
    4. 否则转换强队视角→主队视角（强队=客队时）
    """
    key = (scene_code[0], scene_code[1])
    entry = V6_SCENARIO_TABLE.get(key)
    if not entry:
        return '未知', 0.0
    
    prediction, hit_rate = entry
    
    # AA/WW 主客区分
    if scene_code == 'AA':
        prediction = '胜平' if is_home_strong else '平胜'
    elif scene_code == 'WW':
        prediction = '胜平' if is_home_strong else '负胜'
    
    override_key = (scene_code, is_home_strong)
    if override_key in V65_OVERRIDES:
        prediction = V65_OVERRIDES[override_key]
    elif not is_home_strong:
        prediction = _STRONG_TO_HOME_CONVERT.get(prediction, prediction)
    
    return prediction, hit_rate

# 兼容旧代码
TABLE_HOME = {}
TABLE_AWAY = {}
for (a, b), (pred, rate) in V6_SCENARIO_TABLE.items():
    TABLE_HOME[(a, b)] = pred
    TABLE_AWAY[(a, b)] = _STRONG_TO_HOME_CONVERT.get(pred, pred)

OVERRIDE_V63 = {k: v.replace('', '+')[1:] if len(v) == 2 else v for k, v in V65_OVERRIDES.items()}
# 上面的转换有问题，直接手动构建兼容格式
OVERRIDE_V63 = {}
for (sc, ish), pred in V65_OVERRIDES.items():
    OVERRIDE_V63[(sc, ish)] = pred[0] + '+' + pred[1]

# 场景范畴
def get_category(scene):
    s365, sw = scene[0], scene[1]
    # 范畴一：两家都含强队胜方向(A/B/C)
    if s365 in 'ABC' and sw in 'ABC':
        return 1
    # 范畴三：两家都不含强队胜方向
    if s365 in 'WYZ' and sw in 'WYZ':
        return 3
    # 范畴二：一家含一家不含
    return 2

def get_confidence(scene):
    """返回信心等级"""
    strong = ['AB','AC','CC','CB','BB','AA','CA','AZ','BW','BY','CY','CZ','YA','YB','YC','ZB','ZC','WA','BZ','CW','WB','WY','YW','YZ','ZW','ZY','ZZ','WZ']
    medium = ['BC','ZA','WC','WW']
    weak = ['BA','AW','AY']
    if scene in strong:
        return '强信心'
    elif scene in medium:
        return '中等信心'
    elif scene in weak:
        return '弱信心'
    return '未知'

def get_favor_level(scene):
    """返回看好等级"""
    cat = get_category(scene)
    if cat == 1:
        return '看好'
    elif cat == 2:
        return '分歧'
    elif cat == 3:
        return '博冷'
    return '未知'

# ============================================================
# 6. 蛙跳检查
# ============================================================

def check_frog_jump(ah_list):
    """
    检查澳门蛙跳盘。
    返回: (is_frog, direction, latest_handicap_str) 
    direction: 'up'(升盘→看好上盘), 'down'(降盘→看好下盘), None
    """
    macau = get_macau_ah_from_list(ah_list)
    if not macau:
        return False, None, None
    
    init_h = macau.get('initial_handicap', '')
    latest_h = macau.get('latest_handicap', '')
    
    if not init_h or not latest_h:
        return False, None, None
    
    init_val = parse_handicap(init_h)
    latest_val = parse_handicap(latest_h)
    
    if init_val is None or latest_val is None:
        return False, None, None
    
    diff = latest_val - init_val
    
    # 蛙跳：连续跳两级（≥1.0级别）
    if diff >= 1.0:
        return True, 'up', latest_h
    elif diff <= -1.0:
        return True, 'down', latest_h
    
    return False, None, None

# ============================================================
# 7. 命中判定
# ============================================================

def check_hit(recommendation, score_h, score_a):
    """
    检查推荐是否命中。
    recommendation: '胜+平', '胜+负', '平+负', '负+胜', '平+胜', '负+平'等
    """
    # 确定实际结果
    if score_h > score_a:
        actual = '胜'
    elif score_h == score_a:
        actual = '平'
    else:
        actual = '负'
    
    rec = recommendation.replace('+', '').replace(' ', '')
    # rec可能是'胜平'、'胜负'、'平负'、'负胜'、'平胜'、'负平'
    # 标准化为两个选项的集合
    options = set()
    if '胜' in rec:
        options.add('胜')
    if '平' in rec:
        options.add('平')
    if '负' in rec:
        options.add('负')
    
    return actual in options

# ============================================================
# 8. Kelly≥1.0 规则
# ============================================================

def check_kelly_exclusion(b365_data, weide_data):
    """
    检查Kelly≥1.0排除规则。
    返回: 排除的方向列表
    """
    exclusions = []
    
    if weide_data:
        kw_h, kw_d, kw_a, _ = get_kelly_values(weide_data)
        if kw_h is not None and kw_h >= 1.0:
            exclusions.append('韦德胜K≥1.0→排除胜')
        if kw_a is not None and kw_a >= 1.0:
            exclusions.append('韦德负K≥1.0→排除负')
    
    if b365_data and weide_data:
        kh, _, ka, _ = get_kelly_values(b365_data)
        kw_h, _, kw_a, _ = get_kelly_values(weide_data)
        if kh is not None and kw_h is not None and kh >= 1.0 and kw_h >= 1.0:
            exclusions.append('两家胜K≥1.0→排除胜')
        if ka is not None and kw_a is not None and ka >= 1.0 and kw_a >= 1.0:
            exclusions.append('两家负K≥1.0→排除负')
    
    return exclusions

# ============================================================
# 9. 主流程
# ============================================================

def main():
    base_dir = '/Coze/Drive/私人助理小策/所有对话/主对话/fp-repo'
    data_dir = os.path.join(base_dir, 'data')
    
    # 加载赛果
    results = load_match_results(os.path.join(data_dir, 'match_results.json'))
    print(f"加载赛果: {len(results)} 场")
    
    # 按日期分组赛果
    results_by_date = defaultdict(list)
    for r in results:
        results_by_date[r['date']].append(r)
    
    dates = sorted(results_by_date.keys())
    print(f"日期范围: {dates[0]} - {dates[-1]}, 共 {len(dates)} 天")
    
    # 全部回测记录
    all_records = []
    matched_count = 0
    unmatched_count = 0
    frog_excluded = 0
    no_kelly_data = 0
    no_strong_team = 0
    x_signal = 0
    d_state_processed = 0
    
    # 统计（按场景+主客分组，key为"AA主"/"AA客"格式）
    scenario_stats = defaultdict(lambda: {'total': 0, 'hit': 0})
    category_stats = defaultdict(lambda: {'total': 0, 'hit': 0})
    confidence_stats = defaultdict(lambda: {'total': 0, 'hit': 0})
    favor_stats = defaultdict(lambda: {'total': 0, 'hit': 0})
    
    # 单选分析（按场景+主客分组）
    singles_stats = defaultdict(lambda: {'total': 0, 'primary_hit': 0, 'win_hit': 0, 'draw_hit': 0, 'lose_hit': 0})
    
    unmatched_log = []
    
    for date in dates:
        # 加载该日期的Kelly数据
        kelly_result = load_kelly_data(os.path.join(data_dir, '500com_daily'), date)
        if kelly_result is None:
            no_kelly_data += len(results_by_date[date])
            for r in results_by_date[date]:
                all_records.append({
                    'date': date, 'home': r['home'], 'away': r['away'],
                    'score_h': r['score_h'], 'score_a': r['score_a'],
                    'status': 'no_kelly_data',
                    'matched': False
                })
            continue
        
        fmt_type, kelly_data = kelly_result
        matches = kelly_data.get('matches', {})
        
        # 构建Kelly比赛索引
        kelly_matches = []
        if isinstance(matches, dict):
            for mid, m in matches.items():
                mn = m.get('match_name', '')
                if ' vs ' in mn:
                    parts = mn.split(' vs ')
                    kelly_matches.append({
                        'k_home': parts[0].strip(),
                        'k_away': parts[1].strip(),
                        'data': m,
                        'fmt': fmt_type
                    })
        elif isinstance(matches, list):
            for m in matches:
                h = m.get('home', '')
                a = m.get('away', '')
                if h and a:
                    kelly_matches.append({
                        'k_home': h,
                        'k_away': a,
                        'data': m,
                        'fmt': fmt_type
                    })
        
        # 匹配每场比赛
        for result in results_by_date[date]:
            matched = False
            for km in kelly_matches:
                if fuzzy_match(km['k_home'], result['home']) and fuzzy_match(km['k_away'], result['away']):
                    # 匹配成功
                    matched = True
                    matched_count += 1
                    
                    # 处理本场比赛
                    record = process_match(result, km, date)
                    all_records.append(record)
                    
                    # 更新统计
                    if record['status'] == 'valid':
                        sc = record['scenario']
                        ish = record['is_strong_home']
                        sc_key = sc + ('主' if ish else '客')
                        scenario_stats[sc_key]['total'] += 1
                        if record['hit']:
                            scenario_stats[sc_key]['hit'] += 1
                        
                        cat = record['category']
                        category_stats[cat]['total'] += 1
                        if record['hit']:
                            category_stats[cat]['hit'] += 1
                        
                        conf = record['confidence']
                        confidence_stats[conf]['total'] += 1
                        if record['hit']:
                            confidence_stats[conf]['hit'] += 1
                        
                        fav = record['favor_level']
                        favor_stats[fav]['total'] += 1
                        if record['hit']:
                            favor_stats[fav]['hit'] += 1
                        
                        # 单选分析
                        singles_stats[sc_key]['total'] += 1
                        if record['hit']:
                            singles_stats[sc_key]['primary_hit'] += 1
                        # 按方向分析
                        actual = record['actual_result']
                        singles_stats[sc_key]['win_hit'] += 1 if actual == '胜' else 0
                        singles_stats[sc_key]['draw_hit'] += 1 if actual == '平' else 0
                        singles_stats[sc_key]['lose_hit'] += 1 if actual == '负' else 0
                    
                    elif record['status'] == 'frog_jump':
                        frog_excluded += 1
                    elif record['status'] == 'x_signal':
                        x_signal += 1
                    elif record['status'] == 'no_strong_team':
                        no_strong_team += 1
                    
                    if record.get('d_state_365') or record.get('d_state_weide'):
                        d_state_processed += 1
                    
                    break
            
            if not matched:
                unmatched_count += 1
                unmatched_log.append(f"{date}: {result['home']} vs {result['away']}")
                record = {
                    'date': date, 'home': result['home'], 'away': result['away'],
                    'status': 'unmatched',
                    'matched': False
                }
                if 'score_h' in result:
                    record['score_h'] = result['score_h']
                    record['score_a'] = result['score_a']
                all_records.append(record)
    
    # 计算有效回测场次
    valid_records = [r for r in all_records if r.get('status') == 'valid']
    valid_count = len(valid_records)
    total_hits = sum(1 for r in valid_records if r['hit'])
    overall_hit_rate = total_hits / valid_count * 100 if valid_count > 0 else 0
    
    print(f"\n===== 回测完成 =====")
    print(f"总场次: {len(results)}")
    print(f"匹配成功: {matched_count}")
    print(f"匹配失败: {unmatched_count}")
    print(f"蛙跳排除: {frog_excluded}")
    print(f"X信号排除: {x_signal}")
    print(f"无强队: {no_strong_team}")
    print(f"无Kelly数据: {no_kelly_data}")
    print(f"有效回测: {valid_count}")
    print(f"D状态处理: {d_state_processed}")
    print(f"总命中: {total_hits}/{valid_count} = {overall_hit_rate:.1f}%")
    
    # 按场景统计（区分主客）
    print("\n===== 场景命中率（区分主客） =====")
    scenario_summary = {}
    for sc_key in sorted(scenario_stats.keys()):
        s = scenario_stats[sc_key]
        rate = s['hit'] / s['total'] * 100 if s['total'] > 0 else 0
        sc = sc_key[:2]
        cat = get_category(sc)
        conf = get_confidence(sc)
        print(f"  {sc_key}: {s['hit']}/{s['total']} = {rate:.1f}% (范畴{cat}, {conf})")
        scenario_summary[sc_key] = {
            'total': s['total'],
            'hit': s['hit'],
            'rate': round(rate, 1),
            'category': cat,
            'confidence': conf,
            'scenario': sc,
            'is_strong_home': '主' in sc_key
        }
    
    # 按范畴统计
    print("\n===== 范畴命中率 =====")
    category_summary = {}
    for cat in sorted(category_stats.keys()):
        s = category_stats[cat]
        rate = s['hit'] / s['total'] * 100 if s['total'] > 0 else 0
        print(f"  范畴{cat}: {s['hit']}/{s['total']} = {rate:.1f}%")
        category_summary[f'范畴{cat}'] = {
            'total': s['total'],
            'hit': s['hit'],
            'rate': round(rate, 1)
        }
    
    # 按信心等级统计
    print("\n===== 信心等级命中率 =====")
    confidence_summary = {}
    for conf in sorted(confidence_stats.keys()):
        s = confidence_stats[conf]
        rate = s['hit'] / s['total'] * 100 if s['total'] > 0 else 0
        print(f"  {conf}: {s['hit']}/{s['total']} = {rate:.1f}%")
        confidence_summary[conf] = {
            'total': s['total'],
            'hit': s['hit'],
            'rate': round(rate, 1)
        }
    
    # 单选分析（区分主客，单选必须从双选范围内选）
    print("\n===== 单选分析（区分主客，单选从双选范围内选） =====")
    singles_summary = {}
    for sc_key in sorted(singles_stats.keys()):
        s = singles_stats[sc_key]
        total = s['total']
        if total == 0:
            continue
        primary_rate = s['primary_hit'] / total * 100
        win_rate = s['win_hit'] / total * 100
        draw_rate = s['draw_hit'] / total * 100
        lose_rate = s['lose_hit'] / total * 100
        
        # 获取该场景的双选推荐
        recommendation = ''
        sc = sc_key[:2]
        ish = '主' in sc_key
        for r in all_records:
            if r.get('status') == 'valid' and r.get('scenario') == sc and r.get('is_strong_home') == ish:
                recommendation = r.get('recommendation', '')
                break
        
        # 单选必须从双选的两个方向中选命中率最高的那个（保证单选∈双选）
        dir_rates = {}
        if recommendation and recommendation != '未知':
            if '胜' in recommendation:
                dir_rates['胜'] = win_rate
            if '平' in recommendation:
                dir_rates['平'] = draw_rate
            if '负' in recommendation:
                dir_rates['负'] = lose_rate
        
        if dir_rates:
            best = max(dir_rates.items(), key=lambda x: x[1])
            best_single = best[0]
            best_single_rate = best[1]
        else:
            # 降级：从三个方向中选（仅当recommendation未知时）
            best = max([('胜', win_rate), ('平', draw_rate), ('负', lose_rate)], key=lambda x: x[1])
            best_single = best[0]
            best_single_rate = best[1]
        
        # 各方向>45%的
        good_directions = []
        if win_rate > 45:
            good_directions.append(f'胜({win_rate:.1f}%)')
        if draw_rate > 45:
            good_directions.append(f'平({draw_rate:.1f}%)')
        if lose_rate > 45:
            good_directions.append(f'负({lose_rate:.1f}%)')
        
        if good_directions or primary_rate > 45:
            print(f"  {sc_key}({total}场): 主选{primary_rate:.1f}% | 胜{win_rate:.1f}% 平{draw_rate:.1f}% 负{lose_rate:.1f}% | 最佳单选:{best_single}({best_single_rate:.1f}%) {'★' if good_directions else ''}")
            if good_directions:
                print(f"    >45%方向: {', '.join(good_directions)}")
        
        singles_summary[sc_key] = {
            'total': total,
            'primary_hit_rate': round(primary_rate, 1),
            'win_rate': round(win_rate, 1),
            'draw_rate': round(draw_rate, 1),
            'lose_rate': round(lose_rate, 1),
            'best_single': best_single,
            'best_single_rate': round(best_single_rate, 1),
            'good_directions': good_directions,
            'recommendation': recommendation,
        }
    
    # 保存JSON结果
    output = {
        'summary': {
            'total_matches': len(results),
            'matched': matched_count,
            'unmatched': unmatched_count,
            'frog_excluded': frog_excluded,
            'x_signal_excluded': x_signal,
            'no_strong_team': no_strong_team,
            'no_kelly_data': no_kelly_data,
            'd_state_processed': d_state_processed,
            'valid_backtest': valid_count,
            'total_hits': total_hits,
            'overall_hit_rate': round(overall_hit_rate, 1)
        },
        'by_scenario': scenario_summary,
        'by_category': category_summary,
        'by_confidence': confidence_summary,
        'by_favor_level': {k: {'total': v['total'], 'hit': v['hit'], 'rate': round(v['hit']/v['total']*100 if v['total']>0 else 0, 1)} for k, v in favor_stats.items()},
        'singles': singles_summary,
        'detail': all_records
    }
    
    output_path = os.path.join(base_dir, 'backtest_v65_2252.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nJSON结果已保存到: {output_path}")
    
    # 数据一致性校验
    print("\n===== 数据一致性校验 =====")
    consistency_ok = True
    problem_count = 0
    for sc_key in sorted(scenario_summary.keys()):
        rec = scenario_summary[sc_key]
        sin = singles_summary.get(sc_key)
        if not sin:
            continue
        
        recommendation = sin.get('recommendation', '')
        if not recommendation or recommendation == '未知':
            continue
        
        best_single = sin['best_single']
        best_single_rate = sin['best_single_rate']
        double_rate = rec['rate']
        
        # 检查单选是否在双选范围内
        if best_single not in recommendation:
            print(f"  ✗ {sc_key}: 单选={best_single}不在双选={recommendation}范围内")
            consistency_ok = False
            problem_count += 1
        
        # 检查单选命中率是否超过双选
        if best_single_rate > double_rate + 0.01:
            print(f"  ✗ {sc_key}: 单选命中率({best_single_rate}%) > 双选命中率({double_rate}%)")
            consistency_ok = False
            problem_count += 1
    
    if consistency_ok:
        print(f"  ✓ 所有{len(scenario_summary)}个场景数据一致性校验通过！")
    else:
        print(f"  ✗ 共发现 {problem_count} 个问题")
    
    # 生成HTML报告
    generate_html_report(output, base_dir)
    
    # 打印未匹配日志
    if unmatched_log:
        print(f"\n===== 未匹配场次 ({len(unmatched_log)}) =====")
        for log in unmatched_log[:20]:
            print(f"  {log}")
        if len(unmatched_log) > 20:
            print(f"  ... 共 {len(unmatched_log)} 条")
    
    return output


def process_match(result, km, date):
    """处理单场比赛，返回回测记录"""
    m = km['data']
    fmt = km['fmt']
    
    record = {
        'date': date,
        'home': result['home'],
        'away': result['away'],
        'k_home': km['k_home'],
        'k_away': km['k_away'],
        'matched': True,
        'status': 'valid'
    }
    
    # 检查是否有比分数据
    if 'score_h' not in result or 'score_a' not in result:
        record['status'] = 'no_score'
        record['reason'] = '缺少比分数据'
        return record
    
    score_h = result['score_h']
    score_a = result['score_a']
    
    # 确定实际结果
    if score_h > score_a:
        actual = '胜'
    elif score_h == score_a:
        actual = '平'
    else:
        actual = '负'
    
    record['score_h'] = score_h
    record['score_a'] = score_a
    record['actual_result'] = actual
    
    # 获取公司数据
    companies = m.get('companies', {})
    b365 = get_bet365(companies)
    weide = get_weide(companies)
    
    if not b365 or not weide:
        record['status'] = 'no_data'
        record['reason'] = '缺少365或韦德数据'
        return record
    
    # 确定强队方
    is_strong_home, strong_side = determine_strong_team(b365)
    if is_strong_home is None:
        record['status'] = 'no_strong_team'
        record['reason'] = '无法确定强队方'
        return record
    
    record['is_strong_home'] = is_strong_home
    record['strong_side'] = strong_side
    
    # 检查蛙跳
    ah_list = m.get('asian_handicap', [])
    if ah_list and isinstance(ah_list, list) and len(ah_list) > 0:
        is_frog, direction, latest_h = check_frog_jump(ah_list)
        if is_frog:
            record['status'] = 'frog_jump'
            record['frog_direction'] = direction
            record['frog_latest_handicap'] = latest_h
            record['hit'] = None  # 蛙跳盘不参与双选命中计算
            return record
    
    # 获取Kelly信号
    kh, kd, ka, payout_365 = get_kelly_values(b365)
    kw_h, kw_d, kw_a, payout_weide = get_kelly_values(weide)
    
    sig_365_raw = get_signal_from_kelly(kh, kd, ka, payout_365, is_strong_home)
    sig_weide_raw = get_signal_from_kelly(kw_h, kw_d, kw_a, payout_weide, is_strong_home)
    
    record['sig_365_raw'] = sig_365_raw
    record['sig_weide_raw'] = sig_weide_raw
    
    # 处理D状态
    sig_365 = sig_365_raw
    sig_weide = sig_weide_raw
    if sig_365 == 'D':
        sig_365 = resolve_d_state(kh, kd, ka, is_strong_home)
        record['d_state_365'] = True
    if sig_weide == 'D':
        sig_weide = resolve_d_state(kw_h, kw_d, kw_a, is_strong_home)
        record['d_state_weide'] = True
    
    record['sig_365'] = sig_365
    record['sig_weide'] = sig_weide
    
    # X信号排除
    if sig_365 == 'X' or sig_weide == 'X':
        record['status'] = 'x_signal'
        record['reason'] = f'X信号: 365={sig_365}, 韦德={sig_weide}'
        return record
    
    scene = sig_365 + sig_weide
    record['scenario'] = scene
    
    # 用统一逻辑获取推荐（主队视角，与 daily_predictions.py 一致）
    recommendation, base_hit_rate = get_recommendation(scene, is_strong_home)
    
    # 检查是否override
    override_key = (scene, is_strong_home)
    if override_key in V65_OVERRIDES:
        record['v65_override'] = True
        # 计算原始推荐（用于记录）
        orig_pred, _ = get_recommendation(scene, is_strong_home)
        record['original_recommendation'] = orig_pred
    
    record['recommendation'] = recommendation
    record['base_hit_rate'] = base_hit_rate
    record['category'] = get_category(scene)
    record['confidence'] = get_confidence(scene)
    record['favor_level'] = get_favor_level(scene)
    
    # Kelly≥1.0 排除
    exclusions = check_kelly_exclusion(b365, weide)
    record['kelly_exclusions'] = exclusions
    
    # 命中判定
    if recommendation != '未知':
        record['hit'] = check_hit(recommendation, score_h, score_a)
    else:
        record['hit'] = False
    
    return record


def generate_html_report(output, base_dir):
    """生成HTML报告"""
    s = output['summary']
    
    # 场景表格
    scenario_rows = []
    for sc, data in sorted(output['by_scenario'].items()):
        cat = data['category']
        conf = data['confidence']
        rate = data['rate']
        color = '#d4edda' if rate >= 80 else ('#fff3cd' if rate >= 70 else '#f8d7da')
        scenario_rows.append(f"""
        <tr style="background:{color}">
            <td>{sc}</td>
            <td>{data['hit']}/{data['total']}</td>
            <td><b>{rate}%</b></td>
            <td>范畴{cat}</td>
            <td>{conf}</td>
        </tr>""")
    
    # 范畴表格
    cat_rows = []
    for cat, data in sorted(output['by_category'].items()):
        cat_rows.append(f"""
        <tr>
            <td>{cat}</td>
            <td>{data['hit']}/{data['total']}</td>
            <td><b>{data['rate']}%</b></td>
        </tr>""")
    
    # 信心等级
    conf_rows = []
    for conf, data in sorted(output['by_confidence'].items()):
        conf_rows.append(f"""
        <tr>
            <td>{conf}</td>
            <td>{data['hit']}/{data['total']}</td>
            <td><b>{data['rate']}%</b></td>
        </tr>""")
    
    # 单选分析表格
    singles_rows = []
    for sc, data in sorted(output['singles'].items()):
        if data['total'] < 3:
            continue
        highlight = ''
        if data['primary_hit_rate'] > 45 or data['good_directions']:
            highlight = 'style="background:#d4edda"'
        singles_rows.append(f"""
        <tr {highlight}>
            <td>{sc}</td>
            <td>{data['total']}</td>
            <td>{data['primary_hit_rate']}%</td>
            <td>{data['win_rate']}%</td>
            <td>{data['draw_rate']}%</td>
            <td>{data['lose_rate']}%</td>
            <td><b>{data['best_single']}</b> ({data['best_single_rate']}%)</td>
            <td>{', '.join(data['good_directions']) if data['good_directions'] else '-'}</td>
        </tr>""")
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>V6.4策略回测报告 - 2252场</title>
<style>
    body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f5f5f5; }}
    .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
    h1 {{ color: #333; border-bottom: 3px solid #007bff; padding-bottom: 10px; }}
    h2 {{ color: #555; margin-top: 30px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: center; }}
    th {{ background: #007bff; color: white; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
    .summary-card {{ background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid #007bff; }}
    .summary-card h3 {{ margin: 0 0 5px 0; color: #666; font-size: 14px; }}
    .summary-card .value {{ font-size: 28px; font-weight: bold; color: #007bff; }}
    .note {{ color: #888; font-size: 12px; margin-top: 20px; }}
</style>
</head>
<body>
<div class="container">
<h1>⚽ V6.4策略完整回测报告</h1>
<p>回测日期范围: 20260721 - 20260815 | 策略版本: V6.4（含V6.3 Override + Kelly≥1.0规则）</p>

<div class="summary">
    <div class="summary-card">
        <h3>总场次</h3>
        <div class="value">{s['total_matches']}</div>
    </div>
    <div class="summary-card">
        <h3>匹配成功</h3>
        <div class="value">{s['matched']}</div>
    </div>
    <div class="summary-card">
        <h3>蛙跳排除</h3>
        <div class="value">{s['frog_excluded']}</div>
    </div>
    <div class="summary-card">
        <h3>有效回测</h3>
        <div class="value">{s['valid_backtest']}</div>
    </div>
    <div class="summary-card">
        <h3>总命中</h3>
        <div class="value">{s['total_hits']}</div>
    </div>
    <div class="summary-card" style="border-left-color: {'#28a745' if s['overall_hit_rate'] >= 80 else '#ffc107'}">
        <h3>总命中率</h3>
        <div class="value" style="color:{'#28a745' if s['overall_hit_rate'] >= 80 else '#ffc107'}">{s['overall_hit_rate']}%</div>
    </div>
</div>

<h2>📊 场景命中率</h2>
<table>
<tr><th>场景</th><th>命中/总计</th><th>命中率</th><th>范畴</th><th>信心等级</th></tr>
{''.join(scenario_rows)}
</table>

<h2>📂 范畴分析</h2>
<table>
<tr><th>范畴</th><th>命中/总计</th><th>命中率</th></tr>
{''.join(cat_rows)}
</table>

<h2>🎯 信心等级</h2>
<table>
<tr><th>信心等级</th><th>命中/总计</th><th>命中率</th></tr>
{''.join(conf_rows)}
</table>

<h2>⭐ 单选分析（高亮>45%的场景）</h2>
<table>
<tr><th>场景</th><th>场次</th><th>主选命中率</th><th>单选胜</th><th>单选平</th><th>单选负</th><th>最佳单选</th><th>>45%方向</th></tr>
{''.join(singles_rows)}
</table>

<p class="note">报告生成时间: 2026-08-15 | 策略版本: V6.4手动修正版 | 含V6.3 Override修正 + Kelly≥1.0排除规则</p>
</div>
</body>
</html>"""
    
    html_path = os.path.join(base_dir, 'backtest_v65_2252_report.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"HTML报告已保存到: {html_path}")


if __name__ == '__main__':
    main()