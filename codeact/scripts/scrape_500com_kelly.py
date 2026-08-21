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
                        help='使用纯requests模式（更快，无反检测）')
    parser.add_argument('--no-headless', action='store_true',
                        help='显示浏览器窗口（调试用）')
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

    soup = BeautifulSoup(html, 'html.parser')
    matches = {}
    table = soup.find('table', id='vs_table')
    if not table:
        print("  ⚠️ 未找到vs_table")
        return {}

    rows = table.find_all('tr', class_='vs_lines')
    for row in rows:
        try:
            tds = row.find_all('td')
            if len(tds) < 7:
                continue

            # td[0] = 北单序号 (1, 2, 3...)
            bd_num = tds[0].get_text(strip=True)
            if not bd_num.isdigit():
                continue

            # td[1] = 联赛
            league = tds[1].get_text(strip=True)

            # td[2] = 比赛时间
            match_time = tds[2].get_text(strip=True)

            # td[3] = 主队 [排名]队名
            home_raw = tds[3].get_text(strip=True)
            home = re.sub(r'\[\d+\]', '', home_raw).strip()

            # td[5] = 客队 队名[排名]
            away_raw = tds[5].get_text(strip=True)
            away = re.sub(r'\[\d+\]', '', away_raw).strip()

            # 找欧赔链接
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
        print(f"    {mid}: {minfo['home']} vs {minfo['away']} ({minfo['league']}) [{minfo['fixture_id']}]")
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


async def scrape_all_matches(fixture_ids, match_info_map, use_requests_mode=False):
    """批量抓取比赛数据"""
    print(f"\n[2/4] 抓取赔率数据 ({len(fixture_ids)}场, {'requests模式' if use_requests_mode else 'Playwright模式'})...")
    results = {}

    if use_requests_mode:
        # requests快速通道
        session = req_lib.Session()
        for i, fid in enumerate(fixture_ids):
            m_info = match_info_map.get(fid, {})
            print(f"  [{i+1}/{len(fixture_ids)}] fixture={fid} "
                  f"{m_info.get('home','')}-{m_info.get('away','')} ...", end=' ', flush=True)

            html = fetch_page_with_requests(fid)
            if html:
                parsed = parse_ouzhi_html(html, fid, m_info)
                if parsed and parsed.get('companies'):
                    results[fid] = parsed
                    n_target = len([k for k in TARGET_COMPANIES if k in parsed['companies']])
                    print(f"✓ {len(parsed['companies'])}家公司, {n_target}家目标")
                else:
                    print("✗ 解析无数据")
            else:
                print("✗ 无HTML")

            time.sleep(0.3)
    else:
        # Playwright模式
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
                        results[fid] = parsed
                        n_target = len([k for k in TARGET_COMPANIES if k in parsed['companies']])
                        print(f"✓ {len(parsed['companies'])}家公司, {n_target}家目标")
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
        matches_dict[fid] = {
            'match_name': data.get('match_name', ''),
            'home': data.get('home', ''),
            'away': data.get('away', ''),
            'league': data.get('league', ''),
            'match_time': data.get('match_time', ''),
            'jingcai_id': data.get('jingcai_id', ''),
            'beidan_id': data.get('beidan_id', ''),
            'source': '500.com',
            'data_source': '500com_playwright',
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

        print(f"  共 {len(fixture_ids)} 场赛事 (竞彩{len(jc_matches)} + 北单新增{bd_count}，含兼售)")

    # Step 2: 抓取数据
    use_requests_mode = args.use_requests
    results = await scrape_all_matches(fixture_ids, match_info_map, use_requests_mode)

    if not results:
        print("\n  ❌ 未抓取到任何数据，退出")
        sys.exit(1)

    # Step 3: 格式转换与保存
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
