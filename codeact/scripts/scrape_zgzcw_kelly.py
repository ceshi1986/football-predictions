#!/usr/bin/env python3
"""
zgzcw.com (中国足彩网) 竞彩凯利指数抓取脚本 v1.1
- 从 live.zgzcw.com 获取竞彩比赛列表（含竞彩编号）
- 从 fenxi.zgzcw.com 获取每场比赛的百家欧赔数据（Playwright绕过WAF）
- 提取目标公司（Bet365/韦德/立博）的凯利指数数据
- 输出JSON到 fp-repo/data/500com_daily/{YYYYMMDD}/zgzcw_kelly_data.json

用法：
    python3 fp-repo/scripts/scrape_zgzcw_kelly.py
    python3 fp-repo/scripts/scrape_zgzcw_kelly.py --match-ids 4465702,4465669
"""
import asyncio
import json
import os
import re
import sys
import argparse
import time
import requests
from datetime import datetime
from bs4 import BeautifulSoup

# === 配置 ===
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "500com_daily")
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

# 目标公司映射：页面显示名(去掉末尾*) -> 标准key
TARGET_COMPANIES = {
    '36': 'bet365',
    '韦': 'weide',
    '立': 'libo',
}

# 全量公司映射（可扩展）
ALL_COMPANY_MAP = {
    '36': 'bet365',
    '韦': 'weide',
    '立': 'libo',
    '威': 'william_hill',
    '澳': 'macau',
    '易': 'ysb',
}

# Playwright浏览器参数（绕过WAF反自动化检测）
BROWSER_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--no-sandbox',
    '--disable-web-security',
]

# 反自动化检测的JS注入脚本
ANTI_DETECT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
"""


def parse_args():
    parser = argparse.ArgumentParser(description='zgzcw.com 竞彩凯利指数抓取')
    parser.add_argument('--match-ids', type=str, default='',
                        help='指定比赛ID，逗号分隔。留空则从竞彩列表页自动获取')
    parser.add_argument('--output', type=str, default='',
                        help='指定输出JSON路径。留空则自动生成')
    return parser.parse_args()


# === Step 1: 获取竞彩比赛列表 ===
def fetch_match_list():
    """从 live.zgzcw.com/jz/ 获取竞彩比赛列表
    返回 {match_id: {jingcai_id, league, match_time, home, away}}
    """
    print("[1/3] 获取竞彩比赛列表...")
    url = 'https://live.zgzcw.com/jz/'
    resp = requests.get(url, headers=HEADERS, timeout=15)
    text = resp.content.decode('utf-8', errors='replace')
    soup = BeautifulSoup(text, 'html.parser')

    matches = {}
    for tr in soup.find_all('tr', class_='matchTr'):
        match_id = tr.get('matchid', '')
        if not match_id:
            continue

        tds = tr.find_all('td')
        if len(tds) < 8:
            continue

        # 竞彩编号 (周四201 格式)
        jingcai_text = tds[0].get_text(strip=True)
        jc_match = re.search(r'周[一二三四五六日]\d{3}', jingcai_text)
        jingcai_id = jc_match.group() if jc_match else ''

        # 联赛名称
        league = ''
        league_span = tds[1].find('span')
        if league_span:
            league = league_span.get_text(strip=True)

        # 比赛时间
        match_time_td = tds[3]
        match_time = match_time_td.get_text(strip=True)

        # 主队名称
        home_a = tds[5].find('a')
        home = home_a.get_text(strip=True) if home_a else ''

        # 客队名称
        away_a = tds[7].find('a')
        away = away_a.get_text(strip=True) if away_a else ''

        matches[match_id] = {
            'match_name': f'{home} vs {away}',
            'home': home,
            'away': away,
            'league': league,
            'match_time': match_time,
            'jingcai_id': jingcai_id,
        }

    print(f"  找到 {len(matches)} 场竞彩比赛")
    for mid, info in list(matches.items())[:3]:
        print(f"    {info['jingcai_id']} {info['match_name']} ({info['league']})")
    return matches


# === Step 2: Playwright抓取赔率数据 ===
async def scrape_all_matches(match_ids, match_info):
    """用Playwright批量抓取多场比赛的赔率数据（共享浏览器上下文以复用WAF cookie）"""
    from playwright.async_api import async_playwright

    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await browser.new_context(
            user_agent=HEADERS['User-Agent'],
            viewport={'width': 1920, 'height': 1080},
        )
        # 注入反自动化检测脚本
        await context.add_init_script(ANTI_DETECT_SCRIPT)
        page = await context.new_page()

        for i, mid in enumerate(match_ids):
            print(f"  [{i+1}/{len(match_ids)}] 抓取比赛 {mid}...", end=' ', flush=True)
            try:
                companies = await scrape_single_match(page, mid)
            except Exception as e:
                print(f"✗ 异常: {e}")
                companies = None

            if companies:
                results[mid] = {
                    'match_name': match_info[mid].get('match_name', ''),
                    'league': match_info[mid].get('league', ''),
                    'match_time': match_info[mid].get('match_time', ''),
                    'jingcai_id': match_info[mid].get('jingcai_id', ''),
                    'companies': companies,
                }
                target_keys = [k for k in TARGET_COMPANIES.values() if k in companies]
                print(f"✓ {len(companies)}家公司, 目标: {', '.join(target_keys)}")
                for ck in target_keys:
                    cd = companies[ck]
                    print(f"    {ck}({cd['name']}): "
                          f"赔率={cd['latest_odds']} "
                          f"凯利={cd['kelly']} "
                          f"赔付={cd['payout']}")
            else:
                print("✗ 无数据")

            # 短暂延迟避免被限流
            if i < len(match_ids) - 1:
                await asyncio.sleep(1.5)

        await browser.close()

    return results


async def scrape_single_match(page, match_id):
    """用Playwright加载单场比赛的赔率页面并解析"""
    url = f'http://fenxi.zgzcw.com/{match_id}/bjop'
    await page.goto(url, timeout=20000)
    # 等待WAF验证 + 数据渲染（通常需要10-15秒）
    for attempt in range(20):
        await asyncio.sleep(1)
        try:
            html = await page.content()
        except Exception:
            # 页面正在导航中（WAF跳转），继续等待
            continue
        if 'bf-tab-02' in html or ('36*' in html and len(html) > 100000):
            break
    else:
        # 最后一次尝试获取内容
        try:
            html = await page.content()
        except Exception:
            return None

    if len(html) < 50000:
        return None

    return parse_odds_html(html)


def parse_odds_html(html):
    """解析赔率页面HTML，提取所有公司的赔率/概率/凯利数据
    
    HTML表格结构 (table.bf-tab-02)，每行一个公司：
    - td[0]: 序号/checkbox
    - td[1]: 公司名（脱敏显示，如 "36*", "韦*"）
    - td[2-4]: 初始赔率（data属性=精确值）
    - td[5-7]: 最新赔率（data属性=精确值）
    - td[8]: 更新时间指示
    - td[9-11]: 概率（data属性=百分比值）
    - td[12-14]: 凯利指数（data属性=精确值）
    - td[15]: 赔付率（data属性=精确值）
    - td[16]: 历史链接（主/客/同）
    """
    soup = BeautifulSoup(html, 'html.parser')

    # 找主表格
    table = soup.find('table', class_='bf-tab-02')
    if not table:
        data_main = soup.find(id='data-body')
        if data_main:
            table = data_main.find('table')
    if not table:
        return None

    tbody = table.find('tbody')
    trs = (tbody.find_all('tr') if tbody else table.find_all('tr'))

    companies = {}
    for tr in trs:
        tds = tr.find_all('td', recursive=False)
        if len(tds) < 16:
            continue

        # 公司名
        raw_name = tds[1].get_text(strip=True).strip()
        if not raw_name or raw_name in ('平均欧赔', '官方(胜平负)'):
            continue

        # 初始赔率 td[2,3,4] - 优先从data属性取值
        init_odds = [_get_data_float(tds[i]) for i in [2, 3, 4]]

        # 最新赔率 td[5,6,7]
        latest_odds = [_get_data_float(tds[i]) for i in [5, 6, 7]]

        # 概率 td[9,10,11]
        probability = [_get_data_float(tds[i]) for i in [9, 10, 11]]

        # 凯利指数 td[12,13,14]
        kelly = [_get_data_float(tds[i]) for i in [12, 13, 14]]

        # 赔付率 td[15]
        payout = _get_data_float(tds[15])

        # 匹配公司名
        company_key = match_company(raw_name)
        if company_key:
            companies[company_key] = {
                'name': raw_name,
                'initial_odds': init_odds,
                'latest_odds': latest_odds,
                'probability': probability,
                'kelly': kelly,
                'payout': round(payout, 4),
            }

    return companies if companies else None


def _get_data_float(td):
    """从td元素提取数值，优先data属性"""
    try:
        data = td.get('data', '')
        if data:
            return float(data)
        text = td.get_text(strip=True)
        # 清除趋势箭头
        text = re.sub(r'[↑↓]', '', text)
        return float(text) if text else 0.0
    except (ValueError, AttributeError):
        return 0.0


def match_company(raw_name):
    """将页面显示的公司名匹配到标准key
    页面公司名被脱敏（末尾*号替代），去掉末尾*号后按前缀匹配
    返回 None 表示非目标公司（跳过）
    """
    clean = raw_name.rstrip('*').strip()
    for prefix, key in TARGET_COMPANIES.items():
        if clean.startswith(prefix) or clean == prefix:
            return key
    return None


# === 主流程 ===
async def run():
    args = parse_args()
    today = datetime.now().strftime('%Y%m%d')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 确定输出路径
    if args.output:
        out_path = args.output
    else:
        out_path = os.path.join(OUTPUT_DIR, today, 'zgzcw_kelly_data.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # Step 1: 获取比赛列表
    if args.match_ids:
        match_ids = [m.strip() for m in args.match_ids.split(',') if m.strip()]
        print(f"[1/3] 使用指定的 {len(match_ids)} 场比赛ID")
        match_info = {}
        for mid in match_ids:
            match_info[mid] = {'match_name': '', 'home': '', 'away': '',
                               'league': '', 'match_time': '', 'jingcai_id': ''}
    else:
        match_info = fetch_match_list()
        if not match_info:
            print("  ❌ 未获取到比赛列表，退出")
            sys.exit(1)
        match_ids = list(match_info.keys())

    # Step 2: Playwright抓取每场比赛的赔率数据
    print(f"\n[2/3] 启动Playwright抓取赔率数据 ({len(match_ids)}场)...")
    results = await scrape_all_matches(match_ids, match_info)

    # Step 3: 合并旧数据（未抓到的比赛保留上次数据）
    print(f"\n[3/3] 保存数据...")
    merged_results = dict(results)  # 本次抓到的比赛
    kept_count = 0
    if os.path.exists(out_path):
        try:
            with open(out_path, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
            old_matches = old_data.get('matches', {})
            for mid, mdata in old_matches.items():
                if mid not in merged_results:
                    merged_results[mid] = mdata
                    kept_count += 1
                    print(f"  📌 保留旧数据: {mdata.get('match_name', mid)} (本次未抓取到)")
        except Exception as e:
            print(f"  ⚠️ 读取旧数据失败: {e}")

    output = {
        'date': today,
        'scrape_time': now_str,
        'source': 'zgzcw.com',
        'total_matches': len(merged_results),
        'matches': merged_results,
    }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  ✅ {len(results)}场新数据 + {kept_count}场旧数据 = {len(merged_results)}场 → {out_path}")

    # 统计
    total_companies = sum(len(m['companies']) for m in results.values())
    target_count = sum(1 for m in results.values()
                       for k in TARGET_COMPANIES.values() if k in m['companies'])
    print(f"\n{'='*50}")
    print(f"总计: {len(results)}场比赛, {total_companies}家公司数据, {target_count}条目标公司")
    return output


if __name__ == '__main__':
    asyncio.run(run())
