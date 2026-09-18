#!/usr/bin/env python3
"""
每日自动更新回测主表 backtest_master_table_dedup.json

从Kelly数据中提取已完赛比赛（有365+韦德Kelly + 有赛果），
按 V6.9 策略（72 子组策略表 _V67_STRATEGY）判定场景与推荐，
去重后追加到回测主表，并推送GitHub。

参数：
  sys.argv[1] - result_mode: display_only / notify / no_reply
  sys.argv[2] - date: YYYYMMDD，可选，默认昨天
"""

import asyncio
import json
import os
import re
import sys
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from codeact_sdk import CodeActSDK

# ============================================================
# 配置常量
# ============================================================

# 脚本工作目录（fp-repo 相对路径）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# codeact/scripts -> codeact -> fp-repo
FP_REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DATA_DIR = os.path.join(FP_REPO_DIR, "data")
KELLY_DAILY_DIR = os.path.join(DATA_DIR, "500com_daily")
MASTER_TABLE_PATH = os.path.join(FP_REPO_DIR, "backtest_master_table_dedup.json")
MATCH_RESULTS_PATH = os.path.join(DATA_DIR, "match_results.json")

# ============================================================
# V6.9 策略核心逻辑（与 daily_predictions.py 的 _V67_STRATEGY 保持一致）
# 72 子组策略表：(scenario_code, is_home_strong) → 主队视角双选
# ============================================================

V69_STRATEGY = {
    ('AA', True):  '胜平', ('AA', False): '负平',
    ('AB', True):  '平胜', ('AB', False): '负平',
    ('AC', True):  '胜平', ('AC', False): '胜平',
    ('AW', True):  '胜负', ('AW', False): '平负',
    ('AY', True):  '胜平', ('AY', False): '平胜',
    ('AZ', True):  '负平', ('AZ', False): '负胜',
    ('BA', True):  '胜负', ('BA', False): '平负',
    ('BB', True):  '胜负', ('BB', False): '负胜',
    ('BC', True):  '胜平', ('BC', False): '负胜',
    ('BW', True):  '胜平', ('BW', False): '负胜',
    ('BY', True):  '胜平', ('BY', False): '平负',
    ('BZ', True):  '胜负', ('BZ', False): '胜平',
    ('CA', True):  '胜负', ('CA', False): '负胜',
    ('CB', True):  '胜平', ('CB', False): '平负',
    ('CC', True):  '胜负', ('CC', False): '平负',
    ('CW', True):  '胜负', ('CW', False): '负平',
    ('CY', True):  '胜平', ('CY', False): '平负',
    ('CZ', True):  '胜负', ('CZ', False): '胜负',
    ('WA', True):  '胜平', ('WA', False): '平负',
    ('WB', True):  '胜平', ('WB', False): '平负',
    ('WC', True):  '胜平', ('WC', False): '负胜',
    ('WW', True):  '胜平', ('WW', False): '平负',
    ('WY', True):  '胜平', ('WY', False): '负胜',
    ('WZ', True):  '胜负', ('WZ', False): '胜平',
    ('YA', True):  '胜负', ('YA', False): '胜负',
    ('YB', True):  '胜平', ('YB', False): '平负',
    ('YC', True):  '胜负', ('YC', False): '负平',
    ('YW', True):  '胜平', ('YW', False): '胜平',
    ('YY', True):  '平胜', ('YY', False): '平负',
    ('YZ', True):  '负胜', ('YZ', False): '负平',
    ('ZA', True):  '胜平', ('ZA', False): '负胜',
    ('ZB', True):  '胜平', ('ZB', False): '平负',
    ('ZC', True):  '胜负', ('ZC', False): '胜负',
    ('ZW', True):  '胜平', ('ZW', False): '胜负',
    ('ZY', True):  '平负', ('ZY', False): '胜平',
    ('ZZ', True):  '胜负', ('ZZ', False): '胜负',
}


def normalize_name(name):
    """标准化队名"""
    if not name:
        return ""
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'（.*?）', '', name)
    name = re.sub(r'^\d+\.\s*', '', name)
    name = re.sub(r'\d+', '', name)
    name = re.sub(r'[↑↓→]', '', name)
    name = name.strip()
    return name


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
    if edit_distance(k, r) < 3:
        return True
    k_words = set(k.split())
    r_words = set(r.split())
    common = k_words & r_words
    if common:
        for w in common:
            if len(w) >= 2:
                return True
    return False


def get_company_kelly(companies, key):
    """从companies中提取指定公司的Kelly数据。兼容两种格式。"""
    if key in companies:
        c = companies[key]
        if isinstance(c, dict):
            return c
        if isinstance(c, list) and len(c) > 0:
            return c[0]
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


def determine_strong_team(bet365_data):
    """根据365最新赔率确定强队方。胜赔低=主队强，负赔低=客队强。"""
    if not bet365_data:
        return None, None
    odds_h = bet365_data.get('latest_odds', bet365_data.get('odds_h', [0, 0, 0]))
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

    # 尝试转数值
    try:
        h = float(h)
        a = float(a)
    except (TypeError, ValueError):
        return None, None

    if h <= 0 or a <= 0:
        return None, None

    if h < a:
        return True, 'home'
    elif a < h:
        return False, 'away'
    else:
        return None, None


def get_kelly_values(company_data):
    """提取Kelly三值和返还率。兼容多种格式。"""
    if not company_data:
        return None, None, None, None

    # kelly数组格式 (zgzcw): [kelly_h, kelly_d, kelly_a]
    kelly_arr = company_data.get('kelly', None)
    payout = company_data.get('payout', None)

    if isinstance(kelly_arr, list) and len(kelly_arr) >= 3:
        kh = kelly_arr[0]
        kd = kelly_arr[1]
        ka = kelly_arr[2]
        try:
            return float(kh), float(kd), float(ka), float(payout) if payout is not None else None
        except (TypeError, ValueError):
            pass

    # kelly_h/kelly_d/kelly_a 独立字段格式 (kelly_data_full)
    kh = company_data.get('kelly_h')
    kd = company_data.get('kelly_d')
    ka = company_data.get('kelly_a')
    if kh is not None and kd is not None and ka is not None:
        try:
            return float(kh), float(kd), float(ka), float(payout) if payout is not None else None
        except (TypeError, ValueError):
            pass

    # instant_kelly 格式 (500com_kelly_data.json)
    inst_k = company_data.get('instant_kelly')
    if isinstance(inst_k, dict):
        def _get_k(d, key):
            v = d.get(key)
            if isinstance(v, dict):
                return v.get('value')
            return v
        kh = _get_k(inst_k, 'win')
        kd = _get_k(inst_k, 'draw')
        ka = _get_k(inst_k, 'lose')
        ret = company_data.get('instant_return')
        if ret and isinstance(ret, str):
            ret = ret.replace('%', '')
        if kh is not None and kd is not None and ka is not None:
            try:
                p = float(ret) / 100 if ret else None
                return float(kh), float(kd), float(ka), p
            except (TypeError, ValueError):
                pass

    return None, None, None, None


def get_signal_from_kelly(kh, kd, ka, payout, is_strong_home):
    """从Kelly值获取强队视角信号字母。返回: A/B/C/Y/Z/W/D/X"""
    if kh is None or kd is None or ka is None or payout is None:
        return 'X'

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

    if is_strong_home:
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
    """处理D状态（三方向全看好），按13种情形映射。"""
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


def get_recommendation(scene_code, is_home_strong):
    """获取场景推荐（主队视角），直接查 V6.9 72 子组策略表。"""
    prediction = V69_STRATEGY.get((scene_code, is_home_strong))
    if prediction is None:
        return '未知', 0.0
    return prediction, 0.0


def check_hit(recommendation, score_h, score_a):
    """判断推荐是否命中（主队视角）。"""
    if score_h > score_a:
        actual = '胜'
    elif score_h == score_a:
        actual = '平'
    else:
        actual = '负'
    return actual in recommendation


# ============================================================
# 数据加载与处理
# ============================================================

def load_match_results(date):
    """加载某日期的赛果数据，优先从每日目录读取，兜底全局文件"""
    results = []
    
    # 1. 优先从每日目录读取 match_results.json
    daily_path = os.path.join(KELLY_DAILY_DIR, date, 'match_results.json')
    if os.path.exists(daily_path):
        try:
            with open(daily_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 每日目录的 match_results.json 格式：{date, generated_at, total, results}
            # results 可能是 list 或 dict
            if isinstance(data, dict):
                results_data = data.get('results', [])
                if isinstance(results_data, list):
                    results.extend(results_data)
                elif isinstance(results_data, dict):
                    # dict 格式：{"主队|客队": {比赛信息}}
                    for key, match_info in results_data.items():
                        if isinstance(match_info, dict):
                            results.append(match_info)
            elif isinstance(data, list):
                results.extend(data)
        except Exception as e:
            print(f"[警告] 读取每日赛果失败 {daily_path}: {e}")
    
    # 2. 兜底：从全局 match_results.json 读取该日期的赛果
    if not results and os.path.exists(MATCH_RESULTS_PATH):
        try:
            with open(MATCH_RESULTS_PATH, 'r', encoding='utf-8') as f:
                all_data = json.load(f)
            if isinstance(all_data, list):
                # 过滤出该日期的赛果
                for item in all_data:
                    if item.get('date') == date:
                        results.append(item)
        except Exception as e:
            print(f"[警告] 读取全局赛果失败: {e}")
    
    return results


def load_kelly_data(date, github_token=None):
    """加载某日期的Kelly数据，500万win500优先（铁律），其次zgzcw兜底"""
    date_dir = os.path.join(KELLY_DAILY_DIR, date)
    
    # 确保日期目录存在
    if not os.path.isdir(date_dir):
        os.makedirs(date_dir, exist_ok=True)
    
    # 【铁律】优先 500万 win500_data.json
    w500_path = os.path.join(date_dir, 'win500_data.json')
    if not os.path.exists(w500_path) and github_token:
        # 本地缺失时尝试从 GitHub 拉取
        print(f"[500万] 本地缺失 {date}，尝试从GitHub拉取...")
        ok = fetch_win500_from_github(date, github_token)
        if not ok:
            print(f"[500万] GitHub拉取失败 {date}")
    
    if os.path.exists(w500_path):
        try:
            with open(w500_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ('win500', data)
        except Exception as e:
            print(f"[警告] win500_data.json 读取失败: {e}")
    
    # 兜底：zgzcw_kelly_data.json
    z_path = os.path.join(date_dir, 'zgzcw_kelly_data.json')
    if os.path.exists(z_path):
        with open(z_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return ('zgzcw', data)
    
    # 最后：kelly_data_full / 500com_kelly_data
    k_path = os.path.join(date_dir, 'kelly_data_full.json')
    if os.path.exists(k_path):
        with open(k_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return ('full', data)
    
    f_path = os.path.join(date_dir, '500com_kelly_data.json')
    if os.path.exists(f_path):
        with open(f_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return ('500com', data)
    
    return None, None


def fetch_win500_from_github(date, token):
    """从GitHub拉取指定日期的 win500_data.json"""
    import base64
    import requests
    
    repo = 'ceshi1986/football-predictions'
    api_url = f'https://api.github.com/repos/{repo}/contents/data/500com_daily/{date}/win500_data.json?ref=main'
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
    }
    
    try:
        resp = requests.get(api_url, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"[GitHub] 拉取失败 {date}: HTTP {resp.status_code}")
            return False
        
        data = resp.json()
        content_b64 = data.get('content', '')
        if not content_b64:
            print(f"[GitHub] 拉取失败 {date}: 无content字段")
            return False
        
        content = base64.b64decode(content_b64).decode('utf-8')
        
        # 保存到本地
        date_dir = os.path.join(KELLY_DAILY_DIR, date)
        os.makedirs(date_dir, exist_ok=True)
        local_path = os.path.join(date_dir, 'win500_data.json')
        with open(local_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"[GitHub] 拉取成功 {date} -> {local_path}")
        return True
    except Exception as e:
        print(f"[GitHub] 拉取异常 {date}: {e}")
        return False


def fetch_match_results_from_github(date, token):
    """从GitHub拉取指定日期的 match_results.json（如果存在）"""
    import base64
    import requests
    
    repo = 'ceshi1986/football-predictions'
    api_url = f'https://api.github.com/repos/{repo}/contents/data/500com_daily/{date}/match_results.json?ref=main'
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
    }
    
    try:
        resp = requests.get(api_url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return False
        
        data = resp.json()
        content_b64 = data.get('content', '')
        if not content_b64:
            return False
        
        content = base64.b64decode(content_b64).decode('utf-8')
        
        date_dir = os.path.join(KELLY_DAILY_DIR, date)
        os.makedirs(date_dir, exist_ok=True)
        local_path = os.path.join(date_dir, 'match_results.json')
        with open(local_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"[GitHub] 拉取赛果成功 {date}")
        return True
    except Exception:
        return False


def build_kelly_index(fmt_type, kelly_data):
    """构建Kelly比赛索引列表，返回 [{k_home, k_away, data, fmt}]"""
    matches = kelly_data.get('matches', {})
    result = []

    if isinstance(matches, dict):
        for mid, m in matches.items():
            mn = m.get('match_name', '')
            if ' vs ' in mn:
                parts = mn.split(' vs ')
                result.append({
                    'k_home': parts[0].strip(),
                    'k_away': parts[1].strip(),
                    'data': m,
                    'fmt': fmt_type,
                    'mid': mid,
                })
    elif isinstance(matches, list):
        for m in matches:
            h = m.get('home', '')
            a = m.get('away', '')
            if h and a:
                result.append({
                    'k_home': h,
                    'k_away': a,
                    'data': m,
                    'fmt': fmt_type,
                    'mid': m.get('id', ''),
                })

    return result


def load_master_table():
    """加载回测主表"""
    if not os.path.exists(MASTER_TABLE_PATH):
        return {'detail': []}
    with open(MASTER_TABLE_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_master_table(data):
    """保存回测主表"""
    os.makedirs(os.path.dirname(MASTER_TABLE_PATH), exist_ok=True)
    with open(MASTER_TABLE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_dedup_key(date, home, away):
    """生成去重key"""
    return f"{date}|{normalize_name(home)}|{normalize_name(away)}"


def process_match(result, km, date_str):
    """处理单场比赛，返回回测主表记录格式，或None表示跳过。"""
    m = km['data']
    companies = m.get('companies', {})

    # 必须同时有365和韦德
    b365 = get_bet365(companies)
    weide = get_weide(companies)
    if not b365 or not weide:
        return None, '缺少365或韦德数据'

    # 确定强队方
    is_strong_home, strong_side = determine_strong_team(b365)
    if is_strong_home is None:
        return None, '无法确定强队方'

    # 获取Kelly值
    kh, kd, ka, payout_365 = get_kelly_values(b365)
    kw_h, kw_d, kw_a, payout_weide = get_kelly_values(weide)

    if None in (kh, kd, ka, payout_365) or None in (kw_h, kw_d, kw_a, payout_weide):
        return None, 'Kelly数据不完整'

    # 获取信号
    sig_365_raw = get_signal_from_kelly(kh, kd, ka, payout_365, is_strong_home)
    sig_weide_raw = get_signal_from_kelly(kw_h, kw_d, kw_a, payout_weide, is_strong_home)

    # 处理D状态
    sig_365 = sig_365_raw
    sig_weide = sig_weide_raw
    if sig_365 == 'D':
        sig_365 = resolve_d_state(kh, kd, ka, is_strong_home)
    if sig_weide == 'D':
        sig_weide = resolve_d_state(kw_h, kw_d, kw_a, is_strong_home)

    # X信号排除
    if sig_365 == 'X' or sig_weide == 'X':
        return None, f'X信号: 365={sig_365}, 韦德={sig_weide}'

    # 构建场景代码
    scenario = sig_365 + sig_weide

    # 赛果判定
    score_h = result.get('score_h')
    score_a = result.get('score_a')
    if score_h is None or score_a is None:
        return None, '缺少比分'

    if score_h > score_a:
        res = '胜'
    elif score_h == score_a:
        res = '平'
    else:
        res = '负'

    # 子组
    subgroup = f"{scenario}{'主' if is_strong_home else '客'}"

    # V6.9 推荐与命中
    prediction, _ = get_recommendation(scenario, is_strong_home)
    hit = check_hit(prediction, score_h, score_a) if prediction != '未知' else None

    record = {
        'date': date_str,
        'home': result['home'],
        'away': result['away'],
        'score_h': score_h,
        'score_a': score_a,
        'result': res,
        'scenario': scenario,
        'strong': '',
        'is_strong_home': is_strong_home,
        'subgroup': subgroup,
        'sig_365': sig_365,
        'sig_weide': sig_weide,
        'sig_365_raw': sig_365_raw,
        'sig_weide_raw': sig_weide_raw,
        'prediction': prediction,
        'pred_type': 'V6.9',
        'hit': hit,
    }

    return record, None


def push_to_github_api(commit_msg):
    """通过GitHub API推送回测主表文件（避免git命令网络问题）"""
    try:
        import base64

        # 从 git config 中提取 token 和 repo
        config_path = os.path.join(FP_REPO_DIR, '.git', 'config')
        token = None
        repo_path = None
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config_text = f.read()
            # 提取 url
            import re
            m = re.search(r'url = https://([^@]+)@github\.com/(.+?)\.git', config_text)
            if m:
                token = m.group(1)
                repo_path = m.group(2)

        if not token or not repo_path:
            # 回退到环境变量或默认值
            return False, '无法从git配置获取token和repo信息'

        if not os.path.exists(MASTER_TABLE_PATH):
            return False, '回测主表文件不存在'

        with open(MASTER_TABLE_PATH, 'rb') as f:
            content_b64 = base64.b64encode(f.read()).decode('utf-8')

        api_url = f'https://api.github.com/repos/{repo_path}/contents/backtest_master_table_dedup.json'
        headers = {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json',
        }

        # 获取现有文件的 sha
        sha = None
        try:
            import requests
            resp = requests.get(api_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                sha = resp.json().get('sha')
        except Exception:
            pass

        payload = {
            'message': commit_msg,
            'content': content_b64,
        }
        if sha:
            payload['sha'] = sha

        resp = requests.put(api_url, headers=headers, json=payload, timeout=30)
        if resp.status_code in (200, 201):
            return True, '推送成功'
        else:
            return False, f'API返回 {resp.status_code}: {resp.text[:200]}'

    except ImportError:
        return False, '缺少requests库'
    except Exception as e:
        return False, f'GitHub推送异常: {str(e)}'


# ============================================================
# 主流程
# ============================================================

def get_github_token():
    """从git config中提取GitHub token"""
    try:
        config_path = os.path.join(FP_REPO_DIR, '.git', 'config')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config_text = f.read()
            m = re.search(r'url = https://([^@]+)@github\.com/(.+?)\.git', config_text)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def parse_date_range(date_arg):
    """解析日期参数，支持单日期和日期范围
    单日期: 20260904
    日期范围: 20260904-20260918
    返回: [date1, date2, ...]
    """
    if not date_arg:
        yesterday = datetime.now() - timedelta(days=1)
        return [yesterday.strftime('%Y%m%d')]
    
    if '-' in date_arg:
        parts = date_arg.split('-')
        if len(parts) == 2:
            start_date = datetime.strptime(parts[0], '%Y%m%d')
            end_date = datetime.strptime(parts[1], '%Y%m%d')
            dates = []
            current = start_date
            while current <= end_date:
                dates.append(current.strftime('%Y%m%d'))
                current += timedelta(days=1)
            return dates
    
    return [date_arg]


async def main():
    result_mode = sys.argv[1] if len(sys.argv) > 1 else "display_only"
    date_arg = sys.argv[2] if len(sys.argv) > 2 else None

    sdk = CodeActSDK()

    try:
        # 解析日期范围
        target_dates = parse_date_range(date_arg)
        is_batch_mode = len(target_dates) > 1
        
        print(f"[参数] result_mode={result_mode}, dates={target_dates[0]}{'...' if is_batch_mode else ''} (共{len(target_dates)}天)")
        
        # 获取 GitHub token
        github_token = get_github_token()
        if github_token:
            print(f"[GitHub] Token已加载")
        else:
            print(f"[GitHub] 未找到Token，无法从GitHub拉取数据")

        # 加载回测主表，构建去重索引
        master = load_master_table()
        detail = master.get('detail', [])
        existing_keys = set()
        for d in detail:
            key = make_dedup_key(d.get('date', ''), d.get('home', ''), d.get('away', ''))
            existing_keys.add(key)

        print(f"[主表] 当前 {len(detail)} 场，已加载去重索引")

        # 批量处理每个日期
        total_added = 0
        daily_stats = []
        
        for target_date in target_dates:
            print(f"\n{'='*50}")
            print(f"[处理] {target_date}")
            print(f"{'='*50}")
            
            # 1. 加载赛果
            day_results = load_match_results(target_date)
            print(f"[赛果] {target_date} 共 {len(day_results)} 场已完赛比赛")

            if not day_results:
                daily_stats.append({
                    'date': target_date,
                    'added': 0,
                    'total_results': 0,
                    'reason': '无赛果数据'
                })
                continue

            # 2. 加载Kelly数据（500万优先）
            fmt_type, kelly_data = load_kelly_data(target_date, github_token)
            if kelly_data is None:
                daily_stats.append({
                    'date': target_date,
                    'added': 0,
                    'total_results': len(day_results),
                    'reason': '无Kelly数据'
                })
                print(f"[Kelly] {target_date} 未找到Kelly数据，跳过")
                continue

            kelly_matches = build_kelly_index(fmt_type, kelly_data)
            print(f"[Kelly] 来源={fmt_type}, 共 {len(kelly_matches)} 场比赛")

            # 3. 匹配并处理每场比赛
            new_records = []
            skip_stats = Counter()
            matched_count = 0

            for r in day_results:
                # 确保赛果记录有必要的字段
                if 'home' not in r or 'away' not in r or 'score_h' not in r or 'score_a' not in r:
                    skip_stats['赛果字段缺失'] += 1
                    continue
                
                # 在Kelly数据中找匹配
                matched_km = None
                for km in kelly_matches:
                    if fuzzy_match(km['k_home'], r['home']) and fuzzy_match(km['k_away'], r['away']):
                        matched_km = km
                        break

                if not matched_km:
                    skip_stats['kelly未匹配'] += 1
                    continue

                matched_count += 1

                # 去重检查
                dedup_key = make_dedup_key(target_date, r['home'], r['away'])
                if dedup_key in existing_keys:
                    skip_stats['已在主表中'] += 1
                    continue

                # 处理比赛
                record, reason = process_match(r, matched_km, target_date)
                if record is None:
                    skip_stats[reason or '处理失败'] += 1
                    continue

                new_records.append(record)
                existing_keys.add(dedup_key)

            print(f"[匹配] 赛果匹配Kelly: {matched_count}/{len(day_results)}")
            print(f"[新增] 有效新增: {len(new_records)} 场")
            if skip_stats:
                print(f"[跳过] {dict(skip_stats)}")

            # 4. 追加到主表
            if new_records:
                detail.extend(new_records)
                master['detail'] = detail
                total_added += len(new_records)
                print(f"[累计] 新增 {len(new_records)} 场，总计 {len(detail)} 场")

            daily_stats.append({
                'date': target_date,
                'added': len(new_records),
                'total_results': len(day_results),
                'matched': matched_count,
                'skipped': dict(skip_stats),
                'kelly_source': fmt_type,
                'kelly_count': len(kelly_matches)
            })

        # 5. 保存并推送
        if total_added > 0:
            save_master_table(master)
            print(f"\n[保存] 主表已更新，当前共 {len(detail)} 场")

            # 推送GitHub
            date_range_str = f"{target_dates[0]}~{target_dates[-1]}" if is_batch_mode else target_dates[0]
            commit_msg = f"update backtest_master: +{total_added} ({date_range_str})"
            git_ok, git_msg = push_to_github_api(commit_msg)
            print(f"[GitHub] {git_msg}")
        else:
            git_ok, git_msg = True, '无新增数据，无需推送'
            print(f"\n[GitHub] {git_msg}")

        # 6. 计算命中率
        if total_added > 0:
            # 计算整体命中率
            hit_count = 0
            total_with_result = 0
            for r in detail:
                if r.get('hit') is not None:
                    total_with_result += 1
                    if r.get('hit'):
                        hit_count += 1
            hit_rate = hit_count / total_with_result * 100 if total_with_result > 0 else 0.0
        else:
            hit_count = 0
            hit_rate = 0.0

        # 7. 组装结果消息
        msg_lines = []
        if is_batch_mode:
            msg_lines.append(f"📊 回测主表批量补跑完成")
            msg_lines.append(f"日期范围: {target_dates[0]} ~ {target_dates[-1]}")
            msg_lines.append(f"新增: {total_added} 场 | 总场次: {len(detail)} 场")
            msg_lines.append(f"整体命中率: {hit_rate:.1f}%")
            msg_lines.append("")
            msg_lines.append("每日明细:")
            for stat in daily_stats:
                status = "✓" if stat['added'] > 0 else "○"
                reason = f" ({stat.get('reason', '')})" if stat.get('reason') else ""
                msg_lines.append(f"  {status} {stat['date']}: +{stat['added']} 场{reason}")
        else:
            target_date = target_dates[0]
            stat = daily_stats[0] if daily_stats else {}
            if total_added > 0:
                msg_lines.append(f"✅ 回测主表更新完成（{target_date}）")
                msg_lines.append(f"新增 {total_added} 场 | 总场次 {len(detail)} 场")
                msg_lines.append(f"整体命中率: {hit_rate:.1f}%")
            else:
                reason = stat.get('reason', '无数据')
                msg_lines.append(f"ℹ️ {target_date} 无可新增的回测数据（{reason}）")

        if git_ok and total_added > 0:
            msg_lines.append(f"GitHub推送: 成功")
        elif total_added > 0:
            msg_lines.append(f"GitHub推送: 失败（{git_msg}）")

        message = '\n'.join(msg_lines)

        # result_mode 映射
        if result_mode == "auto":
            actual_mode = "display_only" if total_added > 0 else "no_reply"
        else:
            actual_mode = result_mode

        data_payload = {
            "date_range": f"{target_dates[0]}~{target_dates[-1]}",
            "dates_processed": len(target_dates),
            "added": total_added,
            "total": len(detail),
            "hit_rate": round(hit_rate, 2),
            "daily_stats": daily_stats,
            "git_status": git_msg,
        }

        await sdk.submit_result(
            result_mode=actual_mode,
            status="success",
            message=message,
            data=data_payload,
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        await sdk.submit_result(
            result_mode="notify",
            status="error",
            message=f"更新回测主表失败: {str(e)}",
            data={"error_type": type(e).__name__},
        )


if __name__ == "__main__":
    asyncio.run(main())
