#!/usr/bin/env python3
"""
500万网凯利指数抓取脚本 (Playwright + requests混合版) v1.1
功能：抓取500.com竞彩Kelly数据，反检测优先Playwright，requests快速通道备选
数据源：
  - trade.500.com/jczq/ (竞彩比赛列表)
  - odds.500.com/fenxi/ouzhi-{id}.shtml (欧赔Kelly数据)
  - live.500.com/weekfixture.php (备选赛事列表)

输出（zgzcw格式兼容，daily_predictions.py直接消费）：
  - zgzcw_kelly_data.json (zgzcw格式，source标记为500.com)
  - kelly_data_full.json (500万网详细格式)
  - snapshots/ (时间戳快照)

用法：
    python3 fp-repo/codeact/scripts/scrape_500com_kelly.py
    python3 fp-repo/codeact/scripts/scrape_500com_kelly.py --match-ids 1234567,1234568
    python3 fp-repo/codeact/scripts/scrape_500com_kelly.py --no-github
    python3 fp-repo/codeact/scripts/scrape_500com_kelly.py --use-requests  # 纯requests模式(快速)
"""

import asyncio
import json
import os
import sys
import re
import time
import base64
import argparse
import requests as req_lib
import aiohttp
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# === 配置 ===
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # fp-repo/
DATA_DIR = os.path.join(BASE_DIR, "data", "500com_daily")

# Playwright浏览器参数（反自动化检测）
BROWSER_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--no-sandbox',
    '--disable-web-security',
    '--disable-features=IsolateOrigins,site-per-process',
]

ANTI_DETECT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
window.chrome = {runtime: {}};
"""

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://odds.500.com/',
}

# 500万网公司ID -> 标准key
CID_TO_KEY = {
    '3': 'bet365',
    '6': 'weide',
    '2': 'libo',
    '293': 'william_hill',
    '5': 'macau',
    '9': 'ysb',
    '1': 'china_sports',
}

# 目标公司（下游daily_predictions.py需要的4家）
TARGET_COMPANIES = {'bet365', 'weide', 'libo', 'william_hill'}

# 500万网公司ID -> 中文名
CID_TO_NAME = {
    '3': 'Bet365', '6': '韦德', '2': '立博', '293': '威廉希尔',
    '5': '澳门', '9': '易胜博', '1': '竞彩官方',
}

# 亚盘盘口名称 -> 数值（主队视角，受让为负）
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


def parse_handicap_value(h_str):
    """解析亚盘盘口字符串为数值（主队视角，受让为负）。"""
    if not h_str:
        return None
    h_str = re.sub(r'[↑↓]', '', str(h_str)).strip()
    is_reverse = False
    if h_str.startswith('受'):
        is_reverse = True
        h_str = h_str[1:]
    val = HANDICAP_MAP.get(h_str)
    if val is None:
        return None
    return -val if is_reverse else val


def _parse_handicap_path_data(text):
    """解析亚盘变化历史JSON文本为path列表（公共逻辑）。"""
    try:
        data = json.loads(text)
    except Exception:
        return None
    if not isinstance(data, list) or not data:
        return []
    path = []
    for row in data:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
        if len(tds) < 4:
            continue
        home_water = _safe_float(re.sub(r'<[^>]+>', '', tds[0]))
        handicap_str = re.sub(r'<[^>]+>', '', tds[1]).replace('&nbsp;', ' ').strip()
        away_water = _safe_float(re.sub(r'<[^>]+>', '', tds[2]))
        t = tds[3].strip()
        val = parse_handicap_value(handicap_str)
        if val is not None:
            path.append({
                'val': val,
                'time': t,
                'home_water': home_water,
                'away_water': away_water,
                'str': handicap_str,
            })
    path.reverse()
    return path


async def fetch_macau_handicap_path_async(session, fixture_id):
    """【异步版】抓取澳门亚盘完整变化历史，使用aiohttp，不阻塞事件循环。"""
    url = 'https://odds.500.com/fenxi1/inc/yazhiajax.php'
    params = {'fid': str(fixture_id), 'id': '5', 't': str(int(time.time() * 1000)), 'r': '0'}
    hdrs = {
        **HEADERS,
        'Referer': f'https://odds.500.com/fenxi/yazhi-{fixture_id}.shtml',
        'X-Requested-With': 'XMLHttpRequest',
    }
    for attempt in range(2):
        try:
            async with session.get(url, params=params, headers=hdrs,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    await asyncio.sleep(0.5)
                    continue
                raw = await resp.read()
                text = raw.decode('gbk', errors='replace')
                result = _parse_handicap_path_data(text)
                if result is not None:
                    return result
        except Exception:
            await asyncio.sleep(0.5)
    return []


def fetch_macau_handicap_path(fixture_id):
    """抓取澳门亚盘完整变化历史（时间顺序，早→晚）。【同步版，Playwright模式用】"""
    url = f'https://odds.500.com/fenxi1/inc/yazhiajax.php'
    params = {'fid': str(fixture_id), 'id': '5', 't': str(int(time.time() * 1000)), 'r': '0'}
    for attempt in range(3):
        try:
            resp = req_lib.get(url, params=params, headers={
                **HEADERS,
                'Referer': f'https://odds.500.com/fenxi/yazhi-{fixture_id}.shtml',
                'X-Requested-With': 'XMLHttpRequest',
            }, timeout=10)
            if resp.status_code != 200:
                time.sleep(1)
                continue
            text = resp.content.decode('gbk', errors='replace')
            result = _parse_handicap_path_data(text)
            if result is not None:
                return result
        except Exception:
            time.sleep(1)
    return []


def _parse_macau_handicap_html(html, fixture_id):
    """解析澳门亚盘HTML页面，提取初盘/即时盘口数据（公共解析逻辑）。
    返回 {'initial_handicap_str', 'latest_handicap_str', ..., 'handicap_path': None} 或 None。
    注意：返回的 handicap_path 为 None，需要调用者另行填充。
    """
    soup = BeautifulSoup(html, 'html.parser')
    macau_tr = None
    for tr in soup.find_all('tr'):
        a = tr.find('a', href=re.compile(r'yazhi\.php\?cid=5(?:&|$)'))
        if a:
            macau_tr = tr
            break
    if not macau_tr:
        return None

    tds = macau_tr.find_all('td', recursive=False)
    if len(tds) < 6:
        return None

    def _parse_handicap_td(td):
        """从td中提取(主队水位, 盘口字符串, 客队水位)。"""
        text = td.get_text(separator='\n', strip=True)
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        filtered = []
        for l in lines:
            if re.match(r'^\d+$', l):
                continue
            if l in ('升', '降'):
                continue
            filtered.append(l)
        if len(filtered) < 3:
            return None, None, None
        home_water = _safe_float(filtered[0])
        handicap_str = filtered[1]
        away_water = _safe_float(filtered[-1])
        return home_water, handicap_str, away_water

    lw_home, latest_str, lw_away = _parse_handicap_td(tds[2])
    iw_home, init_str, iw_away = _parse_handicap_td(tds[4])

    if not init_str or not latest_str:
        return None

    init_val = parse_handicap_value(init_str)
    latest_val = parse_handicap_value(latest_str)
    if init_val is None or latest_val is None:
        return None

    return {
        'initial_handicap_str': init_str,
        'latest_handicap_str': latest_str,
        'initial_handicap_val': init_val,
        'latest_handicap_val': latest_val,
        'initial_water_home': iw_home,
        'initial_water_away': iw_away,
        'latest_water_home': lw_home,
        'latest_water_away': lw_away,
        'handicap_path': None,
        'handicap_path_degraded': False,
        '_init_water': iw_home, '_init_str': init_str,
        '_latest_water': lw_home, '_latest_str': latest_str,
        '_init_val': init_val, '_latest_val': latest_val,
    }


def _finalize_handicap_result(parsed, handicap_path):
    """填充handicap_path并清理临时字段。"""
    if not handicap_path:
        iw_home = parsed.pop('_init_water')
        init_str = parsed.pop('_init_str')
        init_val = parsed.pop('_init_val')
        lw_home = parsed.pop('_latest_water')
        latest_str = parsed.pop('_latest_str')
        latest_val = parsed.pop('_latest_val')
        parsed['handicap_path'] = [
            {'val': init_val, 'time': '', 'home_water': iw_home, 'away_water': parsed.get('initial_water_away'), 'str': init_str},
            {'val': latest_val, 'time': '', 'home_water': lw_home, 'away_water': parsed.get('latest_water_away'), 'str': latest_str},
        ]
        parsed['handicap_path_degraded'] = True
    else:
        parsed.pop('_init_water', None)
        parsed.pop('_init_str', None)
        parsed.pop('_init_val', None)
        parsed.pop('_latest_water', None)
        parsed.pop('_latest_str', None)
        parsed.pop('_latest_val', None)
        parsed['handicap_path'] = handicap_path
    return parsed


async def fetch_macau_asian_handicap_async(session, fixture_id):
    """【异步版】抓取澳门亚盘初盘、即时盘口及完整变化路径。使用aiohttp，不阻塞事件循环。"""
    url = f'https://odds.500.com/fenxi/yazhi-{fixture_id}.shtml'
    try:
        async with session.get(url, headers=HEADERS,
                               timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status != 200:
                return None
            raw = await resp.read()
            html = raw.decode('gb2312', errors='replace')
        if len(html) < 5000:
            return None
    except Exception:
        return None

    parsed = _parse_macau_handicap_html(html, fixture_id)
    if not parsed:
        return None

    handicap_path = await fetch_macau_handicap_path_async(session, fixture_id)
    return _finalize_handicap_result(parsed, handicap_path)


def fetch_macau_asian_handicap(fixture_id):
    """抓取澳门亚盘初盘、即时盘口及完整变化路径。【同步版，Playwright模式用】"""
    url = f'https://odds.500.com/fenxi/yazhi-{fixture_id}.shtml'
    try:
        resp = req_lib.get(url, headers=HEADERS, timeout=8)
        if resp.status_code != 200:
            return None
        html = resp.content.decode('gb2312', errors='replace')
        if len(html) < 5000:
            return None
    except Exception:
        return None

    parsed = _parse_macau_handicap_html(html, fixture_id)
    if not parsed:
        return None

    handicap_path = fetch_macau_handicap_path(fixture_id)
    return _finalize_handicap_result(parsed, handicap_path)

# GitHub配置
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GITHUB_REPO = 'ceshi1986/football-predictions'
GITHUB_API = f'https://api.github.com/repos/{GITHUB_REPO}/contents'


def parse_args():
    parser = argparse.ArgumentParser(description='500万网Kelly指数抓取')
    parser.add_argument('--match-ids', type=str, default='',
                        help='指定500万网赛事ID，逗号分隔')
    parser.add_argument('--output', type=str, default='',
                        help='指定输出路径')
    parser.add_argument('--no-github', action='store_true',
                        help='不推送GitHub')
    parser.add_argument('--use-requests', action='store_true',
                        help='使用纯requests模式（更快，并发）')
    parser.add_argument('--no-headless', action='store_true',
                        help='显示浏览器窗口（调试用）')
    parser.add_argument('--concurrency', type=int, default=10,
                        help='requests模式下的并发数(默认10)')
    parser.add_argument('--timeout', type=int, default=0,
                        help='脚本整体超时秒数，0=不限制')
    return parser.parse_args()


# ============================================================
# 第一步：获取竞彩比赛列表
# ============================================================

def fetch_match_list_from_trade():
    """从 trade.500.com/jczq/ 获取竞彩比赛列表"""
    print("[1/4] 获取竞彩比赛列表 (trade.500.com)...")
    url = 'https://trade.500.com/jczq/'
    try:
        resp = req_lib.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  ⚠️ HTTP {resp.status_code}，尝试备选列表源")
            return {}
        html = resp.content.decode('gbk', errors='replace')
    except Exception as e:
        print(f"  ⚠️ 请求失败: {e}，尝试备选列表源")
        return {}

    soup = BeautifulSoup(html, 'html.parser')
    matches = {}

    for row in soup.find_all('tr'):
        try:
            td_no = row.find('td', class_='td-no')
            if not td_no:
                continue
            match_id_text = td_no.get_text(strip=True)
            if not re.match(r'^[周][一二三四五六日]\d{3}$', match_id_text):
                continue

            td_evt = row.find('td', class_='td-evt')
            league = td_evt.get_text(strip=True) if td_evt else ''

            td_endtime = row.find('td', class_='td-endtime')
            match_time = td_endtime.get_text(strip=True) if td_endtime else ''

            td_team = row.find('td', class_='td-team')
            team_text = td_team.get_text(strip=True) if td_team else ''

            home, away = '', ''
            if 'VS' in team_text or 'vs' in team_text:
                parts = re.split(r'VS|vs', team_text, maxsplit=1)
                if len(parts) == 2:
                    home = re.sub(r'\[\d+\]', '', parts[0]).strip()
                    away = re.sub(r'\[\d+\]', '', parts[1]).strip()

            fixture_id = None
            odds_link = row.find('a', href=re.compile(r'odds\.500\.com/fenxi/ouzhi-\d+'))
            if odds_link:
                href = odds_link.get('href', '')
                m = re.search(r'ouzhi-(\d+)', href)
                if m:
                    fixture_id = m.group(1)
            if not fixture_id:
                row_html = str(row)
                m = re.search(r'ouzhi-(\d+)', row_html)
                if m:
                    fixture_id = m.group(1)

            if fixture_id:
                matches[match_id_text] = {
                    'fixture_id': fixture_id,
                    'jingcai_id': match_id_text,
                    'league': league,
                    'match_time': match_time,
                    'home': home,
                    'away': away,
                }
        except Exception:
            continue

    print(f"  找到 {len(matches)} 场竞彩比赛")
    for mid, minfo in list(matches.items())[:3]:
        print(f"    {mid}: {minfo['home']} vs {minfo['away']} ({minfo['league']}) [{minfo['fixture_id']}]")
    return matches


def fetch_live_jingcai_matches():
    """从 live.500.com 获取正在进行/已完赛的竞彩比赛（这些比赛在trade.500.com已下架）。
    live页 tr 属性 order=5NNN(周五)/6NNN(周六)/0NNN(周日)，fid=赔率页fixture_id。
    """
    print("[1/4 补充] 获取live.500.com已开赛竞彩比赛...")
    url = 'https://live.500.com/'
    day_map = {'5': '周五', '6': '周六', '0': '周日', '1': '周一',
               '2': '周二', '3': '周三', '4': '周四'}
    try:
        resp = req_lib.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  ⚠️ HTTP {resp.status_code}")
            return {}
        html = resp.content.decode('gbk', errors='replace')
    except Exception as e:
        print(f"  ⚠️ 请求失败: {e}")
        return {}

    soup = BeautifulSoup(html, 'html.parser')
    matches = {}
    for tr in soup.find_all('tr'):
        try:
            fid = tr.get('fid')
            order = tr.get('order', '')
            gy = tr.get('gy', '')
            if not fid or not order or len(order) != 4 or not order[1:].isdigit():
                continue
            day_cn = day_map.get(order[0])
            if not day_cn:
                continue
            jc_id = f"{day_cn}{order[1:]}"
            parts = gy.split(',')
            league = parts[0] if len(parts) >= 1 else ''
            home = parts[1] if len(parts) >= 2 else ''
            away = parts[2] if len(parts) >= 3 else ''
            # trade列表已有的就不重复
            if jc_id in matches:
                continue
            matches[jc_id] = {
                'fixture_id': fid,
                'jingcai_id': jc_id,
                'league': league,
                'home': home,
                'away': away,
                'match_time': '',
                'from_live': True,
            }
        except Exception:
            continue
    print(f"  live页找到 {len(matches)} 场已开赛竞彩比赛")
    for mid, minfo in list(matches.items())[:3]:
        print(f"    {mid}: {minfo['home']} vs {minfo['away']} ({minfo['league']}) [{minfo['fixture_id']}]")
    return matches


def fetch_beidan_list():
    """从 trade.500.com/bjdc/ 获取北京单场比赛列表"""
    print("[1/4] 获取北单列表 (trade.500.com/bjdc/)...")
    url = 'https://trade.500.com/bjdc/'
    try:
        resp = req_lib.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  ⚠️ HTTP {resp.status_code}")
            return {}
        html = resp.content.decode('gbk', errors='replace')
    except Exception as e:
        print(f"  ⚠️ 请求失败: {e}")
        return {}

    from datetime import datetime, timedelta
    soup = BeautifulSoup(html, 'html.parser')
    matches = {}
    table = soup.find('table', id='vs_table')
    if not table:
        print("  ⚠️ 未找到vs_table")
        return {}

    # 北单页面按日期分组（id="switch_for_YYYY-MM-DD"）
    # 销售时间 10:00 - 次日10:00，凌晨0-10点的比赛归前一天销售日
    all_trs = table.find_all('tr')
    current_date = None
    for row in all_trs:
        # 检查是否日期切换行
        row_id = row.get('id', '')
        dm = re.match(r'switch_for_(\d{4}-\d{2}-\d{2})', row_id)
        if dm:
            current_date = dm.group(1)
            continue

        if 'vs_lines' not in (row.get('class') or []):
            continue
        if not current_date:
            continue

        try:
            tds = row.find_all('td')
            if len(tds) < 7:
                continue

            bd_num = tds[0].get_text(strip=True)
            if not bd_num.isdigit():
                continue

            league = tds[1].get_text(strip=True)
            time_text = tds[2].get_text(strip=True)  # e.g. "17:50"
            home_raw = tds[3].get_text(strip=True)
            home = re.sub(r'\[\d+\]', '', home_raw).strip()
            away_raw = tds[5].get_text(strip=True)
            away = re.sub(r'\[\d+\]', '', away_raw).strip()

            # 组装完整比赛时间 MM-DD HH:MM
            # 日期按北单销售日规则：比赛时间≥10:00用current_date，<10:00归次日
            try:
                date_obj = datetime.strptime(current_date, '%Y-%m-%d')
                hour_min = datetime.strptime(time_text, '%H:%M')
                if hour_min.hour < 10:
                    date_obj = date_obj + timedelta(days=1)
                match_time = date_obj.strftime('%m-%d') + ' ' + time_text
            except Exception:
                match_time = time_text

            fixture_id = None
            link = row.find('a', href=re.compile(r'odds\.500\.com/fenxi/ouzhi-\d+'))
            if link:
                m = re.search(r'ouzhi-(\d+)', link.get('href', ''))
                if m:
                    fixture_id = m.group(1)

            if fixture_id and home and away:
                bd_id = f'北单{int(bd_num):03d}'
                matches[bd_id] = {
                    'fixture_id': fixture_id,
                    'beidan_id': bd_id,
                    'jingcai_id': '',
                    'league': league,
                    'match_time': match_time,
                    'home': home,
                    'away': away,
                }
        except Exception:
            continue

    print(f"  找到 {len(matches)} 场北单比赛")
    for mid, minfo in list(matches.items())[:3]:
        print(f"    {mid}: {minfo['home']} vs {minfo['away']} ({minfo['league']}) {minfo['match_time']} [{minfo['fixture_id']}]")
    return matches


def fetch_match_list_from_weekfixture():
    """从 live.500.com/weekfixture.php 获取赛事列表（备选）"""
    print("[1/4 备选] 获取赛事列表 (live.500.com)...")
    url = 'https://live.500.com/weekfixture.php'
    try:
        resp = req_lib.get(url, headers=HEADERS, timeout=30)
        text = resp.content.decode('utf-8', errors='replace')
        match_ids = []
        seen = set()
        for m in re.finditer(r'fenxi/(?:shuju|ouzhi)-(\d+)\.shtml', text):
            mid = m.group(1)
            if mid not in seen:
                seen.add(mid)
                match_ids.append(mid)
        print(f"  找到 {len(match_ids)} 场赛事")
        return match_ids
    except Exception as e:
        print(f"  ⚠️ 获取失败: {e}")
        return []


# ============================================================
# 第二步：抓取欧赔页面（requests快速通道 / Playwright反检测）
# ============================================================

def fetch_page_with_requests(fixture_id):
    """用requests获取欧赔页面（快速通道）"""
    url = f'https://odds.500.com/fenxi/ouzhi-{fixture_id}.shtml'
    try:
        resp = req_lib.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        html = resp.content.decode('gb2312', errors='replace')
        if len(html) > 10000:
            return html
    except Exception:
        pass
    return None


async def fetch_page_with_playwright(page, fixture_id):
    """用Playwright获取欧赔页面（反检测）"""
    url = f'https://odds.500.com/fenxi/ouzhi-{fixture_id}.shtml'
    try:
        await page.goto(url, timeout=20000, wait_until='domcontentloaded')
        await asyncio.sleep(1)
        html = await page.content()
        if len(html) > 10000:
            return html
    except Exception:
        pass
    return None


async def scrape_all_matches(fixture_ids, match_info_map, use_requests_mode=False, concurrency=10):
    """批量抓取比赛数据

    Args:
        use_requests_mode: True=纯requests并发模式(更快)，False=Playwright反检测模式
        concurrency: requests模式下的并发数
    """
    print(f"\n[2/4] 抓取赔率数据 ({len(fixture_ids)}场, "
          f"{'requests并发('+str(concurrency)+')模式' if use_requests_mode else 'Playwright模式'})...")
    results = {}

    if use_requests_mode:
        # requests并发模式（aiohttp + asyncio.Semaphore，全异步无阻塞）
        sem = asyncio.Semaphore(concurrency)
        completed = 0
        total = len(fixture_ids)
        lock = asyncio.Lock()

        async def _scrape_one(session, fid):
            nonlocal completed
            m_info = match_info_map.get(fid, {})
            async with sem:
                try:
                    # 抓取欧赔HTML（纯异步aiohttp，不阻塞）
                    url = f'https://odds.500.com/fenxi/ouzhi-{fid}.shtml'
                    async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            async with lock:
                                completed += 1
                            return None, fid, m_info
                        raw = await resp.read()
                        html = raw.decode('gb2312', errors='replace')
                    if len(html) < 10000:
                        async with lock:
                            completed += 1
                        return None, fid, m_info

                    # CPU密集解析放到executor（解析是纯CPU操作，很快）
                    loop = asyncio.get_event_loop()
                    parsed = await loop.run_in_executor(
                        None, parse_ouzhi_html, html, fid, m_info
                    )
                    if not parsed or not parsed.get('companies'):
                        async with lock:
                            completed += 1
                        return None, fid, m_info

                    # 澳门亚盘（全异步aiohttp版本，不再阻塞线程池）
                    ah = await fetch_macau_asian_handicap_async(session, fid)
                    if ah and 'macau' in parsed['companies']:
                        parsed['companies']['macau'].update(ah)
                        parsed['macau_asian_handicap'] = ah

                    n_target = len([k for k in TARGET_COMPANIES if k in parsed['companies']])
                    ah_tag = ' +亚盘' if ah else ''
                    async with lock:
                        completed += 1
                        c = completed
                    print(f"  [{c}/{total}] fixture={fid} "
                          f"{m_info.get('home','')}-{m_info.get('away','')} "
                          f"✓ {len(parsed['companies'])}家, {n_target}目标{ah_tag}",
                          flush=True)
                    return parsed, fid, m_info

                except Exception as e:
                    async with lock:
                        completed += 1
                        c = completed
                    print(f"  [{c}/{total}] fixture={fid} ✗ 异常:{e}", flush=True)
                    return None, fid, m_info

        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        connector = aiohttp.TCPConnector(limit=concurrency * 2)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            # 为每个任务包装超时保护（单个任务最多25秒）
            async def _with_timeout(task_coro, fid):
                try:
                    return await asyncio.wait_for(task_coro, timeout=25)
                except asyncio.TimeoutError:
                    print(f"  [超时] fixture={fid} 超过25秒，跳过")
                    return None, fid, match_info_map.get(fid, {})
            
            tasks = [_with_timeout(_scrape_one(session, fid), fid) for fid in fixture_ids]
            results_list = await asyncio.gather(*tasks)

        for parsed, fid, m_info in results_list:
            if parsed:
                results[fid] = parsed
    else:
        # Playwright模式（单页顺序，但反检测能力强）
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=BROWSER_ARGS
            )
            context = await browser.new_context(
                user_agent=HEADERS['User-Agent'],
                viewport={'width': 1920, 'height': 1080},
                locale='zh-CN',
            )
            await context.add_init_script(ANTI_DETECT_SCRIPT)
            page = await context.new_page()

            # 先访问首页建立cookie
            try:
                await page.goto('https://odds.500.com/', timeout=15000)
                await asyncio.sleep(1)
            except Exception:
                pass

            pw_failures = 0
            for i, fid in enumerate(fixture_ids):
                m_info = match_info_map.get(fid, {})
                print(f"  [{i+1}/{len(fixture_ids)}] fixture={fid} "
                      f"{m_info.get('home','')}-{m_info.get('away','')} ...", end=' ', flush=True)

                html = await fetch_page_with_playwright(page, fid)

                # Playwright失败时回退到requests
                if not html:
                    pw_failures += 1
                    html = fetch_page_with_requests(fid)
                    if html:
                        print("(fallback-requests)", end=' ')

                if html:
                    parsed = parse_ouzhi_html(html, fid, m_info)
                    if parsed and parsed.get('companies'):
                        # 抓取澳门亚盘（蛙跳盘检测用）
                        ah = fetch_macau_asian_handicap(fid)
                        if ah and 'macau' in parsed['companies']:
                            parsed['companies']['macau'].update(ah)
                            parsed['macau_asian_handicap'] = ah
                        results[fid] = parsed
                        n_target = len([k for k in TARGET_COMPANIES if k in parsed['companies']])
                        ah_tag = ' +亚盘' if ah else ''
                        print(f"✓ {len(parsed['companies'])}家公司, {n_target}家目标{ah_tag}")
                    else:
                        print("✗ 解析无数据")
                else:
                    print("✗ 无数据")

                await asyncio.sleep(0.3)

            if pw_failures > 3:
                print(f"  ⚠️ Playwright失败{pw_failures}次，后续切换到requests模式")

            await browser.close()

    print(f"\n  成功: {len(results)}/{len(fixture_ids)} 场")
    return results


# ============================================================
# 第三步：解析HTML
# ============================================================

def parse_ouzhi_html(html, fixture_id, match_info):
    """解析500万网欧赔页面

    HTML结构：
    - table#datatb > tr[xls='row'][id='{cid}'] 每行一个公司
    - 每行内嵌4个 table.pl_table_data：
      - [0]: 赔率 (tr0=初始, tr1=即时)
      - [1]: 概率
      - [2]: 返还率
      - [3]: 凯利指数 (tr0=初始, tr1=即时)
    """
    soup = BeautifulSoup(html, 'html.parser')

    # 提取对阵信息
    home = match_info.get('home', '')
    away = match_info.get('away', '')
    league = match_info.get('league', '')
    match_time = match_info.get('match_time', '')

    if not home or not away:
        team_links = soup.find_all('a', href=re.compile(r'/team/\d+/'))
        seen = set()
        for a in team_links:
            t = a.get_text(strip=True)
            if t and t not in seen and len(t) >= 2:
                if not home:
                    home = t; seen.add(t)
                elif t != home and not away:
                    away = t; break

    if not league:
        for a in soup.find_all('a', href=re.compile(r'liansai\.500\.com/zuqiu-\d+')):
            t = a.get_text(strip=True)
            if t and len(t) < 30:
                league = t; break
        if not league:
            m = re.search(r'(\d{2}[\u4e00-\u9fff]+(?:第\d+轮|资格赛|分组赛|附加赛))', html)
            if m: league = m.group(1)

    if not match_time:
        tm = re.search(r'比赛时间\s*([\d-]+\s+[\d:]+)', html)
        if tm: match_time = tm.group(1)

    # 统一时间格式为 MM-DD HH:MM（去掉年份前缀，与前端解析一致）
    if match_time:
        tm_fmt = re.match(r'^\d{4}-(\d{2}-\d{2}\s+\d{2}:\d{2})', match_time)
        if tm_fmt:
            match_time = tm_fmt.group(1)

    companies_zgzcw = {}
    companies_500com = {}

    # 方法1: datatb表格解析
    table = soup.find('table', id='datatb')
    if table:
        rows = table.find_all('tr', attrs={'xls': 'row'})
        for row in rows:
            cid = row.get('id', '')
            if cid not in CID_TO_KEY:
                continue

            company_key = CID_TO_KEY[cid]
            company_name = CID_TO_NAME.get(cid, '')
            td_company = row.find('td', class_='tb_plgs')
            if td_company:
                title = td_company.get('title', '')
                if title:
                    company_name = title

            pl_tables = row.find_all('table', class_='pl_table_data')
            if len(pl_tables) < 4:
                continue

            # 表0: 赔率
            odds_trs = pl_tables[0].find_all('tr')
            init_odds = []
            instant_odds = []
            if len(odds_trs) >= 1:
                init_odds = [_safe_float(td.get_text(strip=True)) for td in odds_trs[0].find_all('td')[:3]]
            if len(odds_trs) >= 2:
                instant_odds = [_safe_float(td.get_text(strip=True)) for td in odds_trs[1].find_all('td')[:3]]

            # 表1: 概率
            prob_trs = pl_tables[1].find_all('tr')
            instant_prob = []
            if len(prob_trs) >= 2:
                instant_prob = [_safe_float(td.get_text(strip=True)) for td in prob_trs[1].find_all('td')[:3]]

            # 表2: 返还率
            ret_trs = pl_tables[2].find_all('tr')
            payout = 0.0
            if len(ret_trs) >= 2:
                ret_td = ret_trs[1].find('td')
                if ret_td:
                    ret_text = ret_td.get_text(strip=True)
                    payout = _safe_float(ret_text)
                    if payout > 1:
                        payout = payout / 100.0

            # 表3: 凯利指数
            kelly_trs = pl_tables[3].find_all('tr')
            instant_kelly = [0.0, 0.0, 0.0]
            if len(kelly_trs) >= 2:
                instant_kelly = [_safe_float(td.get_text(strip=True)) for td in kelly_trs[1].find_all('td')[:3]]
            elif len(kelly_trs) >= 1:
                instant_kelly = [_safe_float(td.get_text(strip=True)) for td in kelly_trs[0].find_all('td')[:3]]

            # 数据校验
            valid_odds = all(x > 1 for x in instant_odds) if instant_odds else False
            valid_kelly = all(0.3 < k < 2.0 for k in instant_kelly if k > 0)
            if not valid_odds or not valid_kelly:
                continue

            # zgzcw兼容格式
            companies_zgzcw[company_key] = {
                'name': company_name,
                'initial_odds': init_odds if all(x > 0 for x in init_odds) else instant_odds[:],
                'latest_odds': instant_odds,
                'probability': instant_prob,
                'kelly': instant_kelly,
                'payout': round(payout, 4),
            }

            # 500万网详细格式
            companies_500com[company_name] = [{
                'odds_h': instant_odds[0] if len(instant_odds) > 0 else 0,
                'odds_d': instant_odds[1] if len(instant_odds) > 1 else 0,
                'odds_a': instant_odds[2] if len(instant_odds) > 2 else 0,
                'payout': round(payout, 4),
                'kelly_h': round(instant_kelly[0], 2),
                'kelly_d': round(instant_kelly[1], 2),
                'kelly_a': round(instant_kelly[2], 2),
            }]

    # 方法2: 备用（通过锚链接）
    if not companies_zgzcw:
        companies_zgzcw, companies_500com = _parse_alt_method(soup)

    if not companies_zgzcw:
        return None

    return {
        'match_name': f'{home} vs {away}',
        'home': home,
        'away': away,
        'league': league,
        'match_time': match_time,
        'jingcai_id': match_info.get('jingcai_id', ''),
        'beidan_id': match_info.get('beidan_id', ''),
        'fixture_id': fixture_id,
        'companies': companies_zgzcw,
        'companies_500com': companies_500com,
    }


def _parse_alt_method(soup):
    """备用解析：通过ouzhi_same锚链接定位公司行"""
    companies_zgzcw = {}
    companies_500com = {}

    for a in soup.find_all('a', href=re.compile(r'ouzhi_same\.php')):
        cm = re.search(r'cid=(\d+)', a.get('href', ''))
        if not cm:
            continue
        cid = cm.group(1)
        if cid not in CID_TO_KEY:
            continue

        tr = a.find_parent('tr')
        if not tr:
            continue
        tds = tr.find_all('td', recursive=False)
        if len(tds) < 5:
            continue

        td2_nums = re.findall(r'[\d.]+', tds[2].get_text())
        if len(td2_nums) < 6:
            continue

        init_odds = [float(td2_nums[0]), float(td2_nums[1]), float(td2_nums[2])]
        instant_odds = [float(td2_nums[3]), float(td2_nums[4]), float(td2_nums[5])]

        td4_text = tds[4].get_text()
        parts = td4_text.split('%')
        if len(parts) < 3:
            continue
        try:
            payout = float(parts[1].strip()) / 100.0
        except:
            continue

        kelly_nums = re.findall(r'[\d.]+', parts[2])
        if len(kelly_nums) < 6:
            continue
        instant_kelly = [float(kelly_nums[-3]), float(kelly_nums[-2]), float(kelly_nums[-1])]

        if not (0.3 < instant_kelly[0] < 2.0 and 0.3 < instant_kelly[1] < 2.0 and 0.3 < instant_kelly[2] < 2.0):
            continue
        if not (0.80 < payout < 1.0):
            continue

        company_key = CID_TO_KEY.get(cid, '')
        company_name = CID_TO_NAME.get(cid, tds[1].get_text(strip=True))

        companies_zgzcw[company_key] = {
            'name': company_name,
            'initial_odds': init_odds,
            'latest_odds': instant_odds,
            'probability': [],
            'kelly': instant_kelly,
            'payout': round(payout, 4),
        }
        companies_500com[company_name] = [{
            'odds_h': instant_odds[0], 'odds_d': instant_odds[1], 'odds_a': instant_odds[2],
            'payout': round(payout, 4),
            'kelly_h': round(instant_kelly[0], 2), 'kelly_d': round(instant_kelly[1], 2), 'kelly_a': round(instant_kelly[2], 2),
        }]

    return companies_zgzcw, companies_500com


def _safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        s = str(val).strip().replace('%', '').replace('↑', '').replace('↓', '')
        if s in ('', '-', '--', 'N/A'):
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


# ============================================================
# 第四步：格式转换与保存
# ============================================================

def build_zgzcw_output(results, date_str, scrape_time):
    """构建zgzcw兼容格式（daily_predictions.py的_load_kelly_zgzcw_data直接消费）"""
    matches_dict = {}
    for fid, data in results.items():
        ds = data.get('data_source', '500com_playwright')
        matches_dict[fid] = {
            'match_name': data.get('match_name', ''),
            'home': data.get('home', ''),
            'away': data.get('away', ''),
            'league': data.get('league', ''),
            'match_time': data.get('match_time', ''),
            'jingcai_id': data.get('jingcai_id', ''),
            'beidan_id': data.get('beidan_id', ''),
            'source': '500.com',
            'data_source': ds,
            'companies': data.get('companies', {}),
            'asian_handicap': None,
        }

    return {
        'date': date_str,
        'scrape_time': scrape_time,
        'source': 'zgzcw.com',  # 兼容标记
        'version': '500com_v1',
        'dongqiudi_fallback_count': 0,
        'total_matches': len(matches_dict),
        'matches': matches_dict,
    }


def build_500com_output(results, date_str, scrape_time):
    """构建500万网详细格式（daily_predictions.py的_load_kelly_500com_data直接消费）"""
    matches_list = []
    for fid, data in results.items():
        matches_list.append({
            'id': f'match_{fid}',
            'league': data.get('league', ''),
            'home': data.get('home', ''),
            'away': data.get('away', ''),
            'match_time': data.get('match_time', ''),
            'companies': data.get('companies_500com', {}),
        })

    total_companies = sum(len(m['companies']) for m in matches_list)
    return {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'source': '500.com',
        'scrape_time': scrape_time,
        'matches': matches_list,
        'total_matches': len(matches_list),
        'total_companies': total_companies,
        'skipped': 0,
    }


def save_all_data(zgzcw_output, output_500com, date_str):
    """保存所有数据文件"""
    out_dir = os.path.join(DATA_DIR, date_str)
    os.makedirs(out_dir, exist_ok=True)

    zgzcw_path = os.path.join(out_dir, 'zgzcw_kelly_data.json')
    with open(zgzcw_path, 'w', encoding='utf-8') as f:
        json.dump(zgzcw_output, f, ensure_ascii=False, indent=2)

    kelly_full_path = os.path.join(out_dir, 'kelly_data_full.json')
    with open(kelly_full_path, 'w', encoding='utf-8') as f:
        json.dump(output_500com, f, ensure_ascii=False, indent=2)

    data_500com_path = os.path.join(out_dir, '500com_kelly_data.json')
    with open(data_500com_path, 'w', encoding='utf-8') as f:
        json.dump(output_500com, f, ensure_ascii=False, indent=2)

    # 快照
    snapshot_dir = os.path.join(out_dir, 'snapshots')
    os.makedirs(snapshot_dir, exist_ok=True)
    time_str = datetime.now().strftime('%H%M%S')

    snapshot_z = os.path.join(snapshot_dir, f'zgzcw_kelly_data_{time_str}.json')
    with open(snapshot_z, 'w', encoding='utf-8') as f:
        json.dump(zgzcw_output, f, ensure_ascii=False, indent=2)

    snapshot_5 = os.path.join(snapshot_dir, f'500com_kelly_snapshot_{time_str}.json')
    with open(snapshot_5, 'w', encoding='utf-8') as f:
        json.dump(output_500com, f, ensure_ascii=False, indent=2)

    print(f"\n[3/4] 数据已保存:")
    print(f"  zgzcw格式: {zgzcw_path}")
    print(f"  500com格式: {kelly_full_path}")
    print(f"  快照: {snapshot_z}")

    return zgzcw_path, kelly_full_path


# ============================================================
# 第五步：GitHub推送
# ============================================================

def push_to_github(files_to_push, date_str):
    print(f"\n[4/4] 推送GitHub...")
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }
    commit_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    success = True

    for local_path, repo_path in files_to_push:
        if not os.path.exists(local_path):
            print(f"  ✗ 文件不存在: {local_path}")
            success = False
            continue

        with open(local_path, 'rb') as f:
            content_b64 = base64.b64encode(f.read()).decode('utf-8')

        url = f'{GITHUB_API}/{repo_path}'
        sha = None
        try:
            check_resp = req_lib.get(url, headers=headers, timeout=10)
            if check_resp.status_code == 200:
                sha = check_resp.json().get('sha')
        except Exception:
            pass

        payload = {
            'message': f'📊 500万Kelly数据 {date_str} - {commit_time}',
            'content': content_b64,
        }
        if sha:
            payload['sha'] = sha

        try:
            resp = req_lib.put(url, headers=headers, json=payload, timeout=30)
            if resp.status_code in (200, 201):
                print(f"  ✓ {repo_path}")
            else:
                print(f"  ✗ {repo_path} -> HTTP {resp.status_code}: {resp.text[:200]}")
                success = False
        except Exception as e:
            print(f"  ✗ {repo_path} -> {e}")
            success = False

    return success


# ============================================================
# 主流程
# ============================================================

async def run():
    args = parse_args()

    now = datetime.now()
    date_str = now.strftime('%Y%m%d')
    scrape_time = now.strftime('%Y-%m-%d %H:%M:%S')

    print(f"{'='*60}")
    print(f"  500万网Kelly抓取 v1.1 (Playwright+requests混合)")
    print(f"  时间: {scrape_time}")
    print(f"{'='*60}\n")

    # Step 1: 获取比赛列表
    fixture_ids = []
    match_info_map = {}

    if args.match_ids:
        fixture_ids = [m.strip() for m in args.match_ids.split(',') if m.strip()]
        match_info_map = {fid: {} for fid in fixture_ids}
        print(f"[1/4] 使用指定的 {len(fixture_ids)} 场赛事ID")
    else:
        # 竞彩
        jc_matches = fetch_match_list_from_trade()
        for mid, minfo in jc_matches.items():
            fid = minfo['fixture_id']
            if fid not in match_info_map:
                fixture_ids.append(fid)
                match_info_map[fid] = minfo

        # 补充已开赛/已完赛竞彩（trade页已下架，从live.500.com获取）
        live_matches = fetch_live_jingcai_matches()
        live_added = 0
        for mid, minfo in live_matches.items():
            if mid in jc_matches:
                continue  # trade列表已有
            fid = minfo['fixture_id']
            if fid not in match_info_map:
                fixture_ids.append(fid)
                match_info_map[fid] = minfo
                live_added += 1
            else:
                # fid已存在（可能是北单），补充竞彩编号
                match_info_map[fid]['jingcai_id'] = mid
        if live_added:
            print(f"  live补充 {live_added} 场已开赛竞彩")

        # 北单
        bd_matches = fetch_beidan_list()
        bd_count = 0
        for mid, minfo in bd_matches.items():
            fid = minfo['fixture_id']
            if fid not in match_info_map:
                fixture_ids.append(fid)
                match_info_map[fid] = minfo
                bd_count += 1
            else:
                # 同一场比赛竞彩和北单都有，补充beidan_id
                match_info_map[fid]['beidan_id'] = minfo.get('beidan_id', '')

        if len(fixture_ids) < 5:
            print("  竞彩+北单列表不足，补充weekfixture...")
            extra_ids = fetch_match_list_from_weekfixture()
            existing = set(fixture_ids)
            for eid in extra_ids:
                if eid not in existing:
                    fixture_ids.append(eid)
                    match_info_map[eid] = {'fixture_id': eid}
                    existing.add(eid)

        if not fixture_ids:
            print("  ❌ 未获取到赛事ID，退出")
            sys.exit(1)

        print(f"  共 {len(fixture_ids)} 场赛事 (竞彩在售{len(jc_matches)}+已开赛{live_added} + 北单新增{bd_count}，含兼售)")

    # Step 2: 抓取数据（支持并发和超时）
    use_requests_mode = args.use_requests
    concurrency = args.concurrency if use_requests_mode else 1
    scrape_coro = scrape_all_matches(fixture_ids, match_info_map, use_requests_mode, concurrency)

    if args.timeout and args.timeout > 0:
        try:
            results = await asyncio.wait_for(scrape_coro, timeout=args.timeout)
        except asyncio.TimeoutError:
            print(f"\n  ⚠️ 抓取阶段超时({args.timeout}s)，提前结束")
            # results会是空的，但下面可能已存部分结果——这里只能整体失败
            print("  ❌ 超时，未产出完整数据，退出")
            sys.exit(1)
    else:
        results = await scrape_coro

    if not results:
        print("\n  ❌ 未抓取到任何数据，退出")
        sys.exit(1)

    # Step 3: 合并旧数据（保留已开赛/已完赛场次的凯利数据和竞彩/北单编号，避免重新抓取时丢失）
    zgzcw_path_old = os.path.join(DATA_DIR, date_str, 'zgzcw_kelly_data.json')
    snap_dir = os.path.join(DATA_DIR, date_str, 'snapshots')

    def _load_old_json(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            om = d.get('matches', {})
            if isinstance(om, list):
                return {str(m.get('fixture_id', i)): m for i, m in enumerate(om)}
            elif isinstance(om, dict):
                return {str(k): v for k, v in om.items()}
        except Exception:
            return {}
        return {}

    # Gather historical matches from current file + all snapshots (newest first)
    # This allows recovering jingcai_id/beidan_id that may have been lost in recent scrapes
    old_sources = []
    if os.path.exists(zgzcw_path_old):
        old_sources.append(('current', _load_old_json(zgzcw_path_old)))
    if os.path.isdir(snap_dir):
        snap_files = sorted(
            [f for f in os.listdir(snap_dir) if f.startswith('kelly_snapshot_') and f.endswith('.json')],
            reverse=True
        )
        for sf in snap_files[:5]:  # look at last 5 snapshots
            old_sources.append((sf, _load_old_json(os.path.join(snap_dir, sf))))

    # Build a unified historical lookup: key by team name pair, value has jingcai_id/beidan_id/companies
    def _norm_name(s):
        return (s or '').strip().replace(' ', '')

    def _name_key(m):
        return (_norm_name(m.get('home', '')), _norm_name(m.get('away', '')))

    def _names_match(a, b):
        if a == b:
            return True
        for i in (0, 1):
            x, y = a[i], b[i]
            if not x or not y:
                continue
            if x == y or x.startswith(y) or y.startswith(x):
                oa, ob = a[1 - i], b[1 - i]
                if oa and ob and (oa == ob or oa.startswith(ob) or ob.startswith(oa)):
                    return True
        return False

    # Collect all historical match records (for full-match retention)
    hist_matches = {}  # fid -> record (newest wins for duplicate fids)
    hist_name_records = []  # list of (name_key, record), newest first

    def _merge_hist_record(existing, m):
        """Given two records for the same match, keep the one with better metadata."""
        if existing is None:
            return m
        # Prefer one with jingcai_id
        if not existing.get('jingcai_id') and m.get('jingcai_id'):
            return m
        if existing.get('jingcai_id') and not m.get('jingcai_id'):
            return existing
        # Prefer more companies
        if len(m.get('companies', {})) > len(existing.get('companies', {})):
            return m
        return existing

    for src_name, src_matches in old_sources:
        for fid, m in src_matches.items():
            if not m.get('home') or not m.get('away'):
                continue
            # newest source first, so don't overwrite
            if fid not in hist_matches:
                hist_matches[fid] = m
            nk = _name_key(m)
            # Find if an existing name record refers to the same match via prefix
            found_idx = -1
            for i, (enk, erec) in enumerate(hist_name_records):
                if _names_match(nk, enk):
                    found_idx = i
                    break
            if found_idx >= 0:
                enk, erec = hist_name_records[found_idx]
                hist_name_records[found_idx] = (enk, _merge_hist_record(erec, m))
            else:
                hist_name_records.append((nk, m))

    hist_by_name = dict(hist_name_records)

    # Build fuzzy name index
    hist_name_list = hist_name_records

    def _find_hist(nm):
        nnk = _name_key(nm)
        # exact
        if nnk in hist_by_name:
            return hist_by_name[nnk]
        # fuzzy prefix
        for nk, hm in hist_name_list:
            if _names_match(nnk, nk):
                return hm
        return None

    id_restored = 0
    kept_count = 0
    matched_hist_fids = set()

    # 3a. Restore jingcai_id/beidan_id for matches present in new scrape
    for nfid, nm in results.items():
        hm = _find_hist(nm)
        if hm is not None:
            matched_hist_fids.add(nfid)
            # track which hist fids match (fuzzy)
            for hfid, hhm in hist_matches.items():
                if _names_match(_name_key(nm), _name_key(hhm)):
                    matched_hist_fids.add(hfid)
            changed = False
            if not nm.get('jingcai_id') and hm.get('jingcai_id'):
                nm['jingcai_id'] = hm['jingcai_id']
                changed = True
            if not nm.get('beidan_id') and hm.get('beidan_id'):
                nm['beidan_id'] = hm['beidan_id']
                changed = True
            # 保护handicap_path：区分"抓取失败降级"和"真实数据变化"
            # - 新数据path_degraded=True → API失败降级为2节点假路径 → 保留旧长路径
            # - 新数据path_degraded=False → API成功返回的真实路径 → 接受新数据（即使更短）
            old_macau = hm.get('companies', {}).get('macau', {})
            new_macau = nm.get('companies', {}).get('macau', {})
            if old_macau and new_macau:
                old_path = old_macau.get('handicap_path', [])
                new_path = new_macau.get('handicap_path', [])
                new_is_degraded = new_macau.get('handicap_path_degraded', False)
                if new_is_degraded and len(old_path) > len(new_path) and old_path:
                    # 抓取失败降级：保留旧的完整路径
                    new_macau['handicap_path'] = old_path
                    new_macau['handicap_path_degraded'] = False  # 恢复后标记为可信
                    # 同步更新initial/latest（如果旧的更完整）
                    if old_macau.get('initial_handicap_str') and not new_macau.get('initial_handicap_str'):
                        for k in ['initial_handicap_str', 'latest_handicap_str', 'initial_handicap_val', 'latest_handicap_val',
                                   'initial_water_home', 'initial_water_away', 'latest_water_home', 'latest_water_away']:
                            if old_macau.get(k) is not None:
                                new_macau[k] = old_macau[k]
                    changed = True
                elif not new_is_degraded and len(new_path) <= len(old_path):
                    # API成功返回但路径没变长/变短了：真实数据变化，正常接受
                    pass  # 新数据已经是正确的，不需要额外处理
            if changed:
                id_restored += 1

    # 3b. Retain historical matches completely missing from new scrape (by fid and name)
    new_name_keys = [_name_key(nm) for nm in results.values()]
    for hfid, hm in hist_matches.items():
        if hfid in results:
            continue
        if hfid in matched_hist_fids:
            continue
        hnk = _name_key(hm)
        if any(_names_match(hnk, nnk) for nnk in new_name_keys):
            continue
        results[hfid] = {
            'match_name': hm.get('match_name', ''),
            'home': hm.get('home', ''),
            'away': hm.get('away', ''),
            'league': hm.get('league', ''),
            'match_time': hm.get('match_time', ''),
            'jingcai_id': hm.get('jingcai_id', ''),
            'beidan_id': hm.get('beidan_id', ''),
            'companies': hm.get('companies', {}),
            'fixture_id': hfid,
            'source': '500.com',
            'data_source': '500com_merged',
        }
        kept_count += 1

    if id_restored > 0 or kept_count > 0:
        print(f"  📦 合并旧数据: 恢复编号{id_restored}场 + 保留旧{kept_count}场 = {len(results)}场")

    # Step 3.5: 格式转换与保存
    zgzcw_output = build_zgzcw_output(results, date_str, scrape_time)
    output_500com = build_500com_output(results, date_str, scrape_time)
    zgzcw_path, kelly_full_path = save_all_data(zgzcw_output, output_500com, date_str)

    # Step 4: GitHub推送
    if not args.no_github:
        files_to_push = [
            (zgzcw_path, f'data/500com_daily/{date_str}/zgzcw_kelly_data.json'),
            (kelly_full_path, f'data/500com_daily/{date_str}/kelly_data_full.json'),
        ]
        push_to_github(files_to_push, date_str)
    else:
        print("\n[4/4] 跳过GitHub推送")

    # 统计
    total_companies = sum(len(m['companies']) for m in results.values())
    target_count = sum(1 for m in results.values()
                       for k in TARGET_COMPANIES if k in m['companies'])
    print(f"\n{'='*60}")
    print(f"  ✅ 完成!")
    print(f"  比赛: {len(results)} 场")
    print(f"  公司: {total_companies} 条")
    print(f"  目标公司: {target_count} 条 (bet365/weide/libo/william_hill)")
    print(f"{'='*60}")

    return zgzcw_output


if __name__ == '__main__':
    asyncio.run(run())
