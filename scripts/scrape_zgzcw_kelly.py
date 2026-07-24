#!/usr/bin/env python3
"""
zgzcw.com (中国足彩网) 竞彩+北单 凯利指数抓取脚本 v2.0
- 从 live.zgzcw.com/jz/ 获取竞彩比赛列表（Playwright绕过WAF）
- 从 live.zgzcw.com/bd/ 获取北京单场比赛列表（Playwright绕过WAF）
- 从 fenxi.zgzcw.com 获取每场比赛的百家欧赔数据（Playwright绕过WAF）
- 提取目标公司（Bet365/韦德/立博）的凯利指数数据
- 输出JSON到 fp-repo/data/500com_daily/{YYYYMMDD}/zgzcw_kelly_data.json

用法：
    python3 fp-repo/scripts/scrape_zgzcw_kelly.py
    python3 fp-repo/scripts/scrape_zgzcw_kelly.py --match-ids 4465702,4465669
    python3 fp-repo/scripts/scrape_zgzcw_kelly.py --source jz       # 仅竞彩
    python3 fp-repo/scripts/scrape_zgzcw_kelly.py --source bd       # 仅北单
    python3 fp-repo/scripts/scrape_zgzcw_kelly.py --source all      # 竞彩+北单(默认)
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

# WAF等待参数
WAF_MAX_WAIT = 30       # 单页面等待WAF验证的最大秒数
WAF_CHECK_INTERVAL = 1  # 检查间隔秒数


def parse_args():
    parser = argparse.ArgumentParser(description='zgzcw.com 竞彩+北单 凯利指数抓取')
    parser.add_argument('--match-ids', type=str, default='',
                        help='指定比赛ID，逗号分隔。留空则从列表页自动获取')
    parser.add_argument('--source', type=str, default='all',
                        choices=['jz', 'bd', 'all'],
                        help='数据源: jz=竞彩, bd=北单, all=竞彩+北单(默认)')
    parser.add_argument('--output', type=str, default='',
                        help='指定输出JSON路径。留空则自动生成')
    return parser.parse_args()


# === Step 1: Playwright获取比赛列表 ===

async def _playwright_fetch_page(page, url, wait_for_selector='tr.matchTr',
                                  min_html_len=50000, label=''):
    """用Playwright加载页面，等待WAF验证通过后返回HTML

    Args:
        page: Playwright page对象
        url: 目标URL
        wait_for_selector: 等待出现的选择器（表示数据已加载）
        min_html_len: HTML最小长度阈值（低于此值视为WAF拦截）
        label: 日志标签

    Returns:
        HTML字符串，失败返回None
    """
    print(f"  Playwright加载 {label or url}...")
    try:
        await page.goto(url, timeout=30000, wait_until='domcontentloaded')
    except Exception as e:
        print(f"    ✗ 页面加载异常: {e}")
        return None

    # 等待WAF验证 + 数据渲染
    html = ''
    for attempt in range(WAF_MAX_WAIT):
        await asyncio.sleep(WAF_CHECK_INTERVAL)
        try:
            html = await page.content()
        except Exception:
            # 页面正在导航中（WAF跳转），继续等待
            continue

        # 检查是否被WAF拦截
        if 'The access is blocked' in html or '访问被拦截' in html:
            print(f"    ✗ WAF拦截 (418)，等待中... t={attempt+1}s")
            continue

        # 检查数据是否加载完成
        if wait_for_selector and wait_for_selector in html:
            print(f"    ✓ 数据加载完成 t={attempt+1}s, HTML长度={len(html)}")
            return html

        # 备用检查：HTML长度超过阈值
        if len(html) > min_html_len and 'blocked' not in html.lower():
            print(f"    ✓ HTML长度达标 t={attempt+1}s, len={len(html)}")
            return html

    # 超时后最后一次尝试
    try:
        html = await page.content()
    except Exception:
        return None

    if 'blocked' in html.lower() or len(html) < min_html_len:
        print(f"    ✗ WAF未通过或页面内容不足: len={len(html)}")
        return None

    print(f"    ⚠ 超时但返回内容: len={len(html)}")
    return html


def _parse_jz_match_list(html):
    """解析竞彩页面HTML，提取比赛列表

    竞彩页面 td 结构 (tr.matchTr):
    - tds[0]: 竞彩编号 (周四201 格式)
    - tds[1]: 联赛 (含span)
    - tds[2]: 赛事图标/标记
    - tds[3]: 比赛时间
    - tds[4]: 状态
    - tds[5]: 主队 (含a标签)
    - tds[6]: 比分
    - tds[7]: 客队 (含a标签)
    - tds[8+]: 赔率等

    返回 {match_id: {jingcai_id, league, match_time, home, away, source}}
    """
    soup = BeautifulSoup(html, 'html.parser')
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
        match_time = tds[3].get_text(strip=True) if len(tds) > 3 else ''

        # 主队名称
        home_a = tds[5].find('a') if len(tds) > 5 else None
        home = home_a.get_text(strip=True) if home_a else ''
        if not home and len(tds) > 5:
            home = tds[5].get_text(strip=True)

        # 客队名称
        away_a = tds[7].find('a') if len(tds) > 7 else None
        away = away_a.get_text(strip=True) if away_a else ''
        if not away and len(tds) > 7:
            away = tds[7].get_text(strip=True)

        matches[match_id] = {
            'match_name': f'{home} vs {away}',
            'home': home,
            'away': away,
            'league': league,
            'match_time': match_time,
            'jingcai_id': jingcai_id,
            'source': 'jz',
        }

    return matches


def _parse_bd_match_list(html):
    """解析北单页面HTML，提取比赛列表

    北单页面 td 结构 (tr.matchTr) — 与竞彩类似但有差异:
    - tds[0]: 北单编号 (纯数字，如 "4"、"58")
    - tds[1]: 联赛 (含span)
    - tds[2]: 赛事图标/标记
    - tds[3]: 比赛时间
    - tds[4]: 状态
    - tds[5]: 主队 (含a标签)
    - tds[6]: 比分
    - tds[7]: 客队 (含a标签)
    - tds[8+]: SP值等

    注: 北单页面结构可能与竞彩有差异，解析时做容错处理

    返回 {match_id: {beidan_id, league, match_time, home, away, source}}
    """
    soup = BeautifulSoup(html, 'html.parser')
    matches = {}

    for tr in soup.find_all('tr', class_='matchTr'):
        match_id = tr.get('matchid', '')
        if not match_id:
            continue

        tds = tr.find_all('td')
        if len(tds) < 8:
            continue

        # 北单编号 (纯数字)
        beidan_text = tds[0].get_text(strip=True)
        bd_match = re.search(r'\d+', beidan_text)
        beidan_id = bd_match.group() if bd_match else beidan_text

        # 联赛名称 — 尝试多种位置
        league = ''
        # 优先从 tds[1] 的 span 中取
        if len(tds) > 1:
            league_span = tds[1].find('span')
            if league_span:
                league = league_span.get_text(strip=True)
            else:
                # 如果没有span，直接取td文本
                league = tds[1].get_text(strip=True)

        # 比赛时间 — 尝试多个位置
        match_time = ''
        for ti in [3, 2, 4]:
            if len(tds) > ti:
                candidate = tds[ti].get_text(strip=True)
                # 时间格式通常包含冒号，如 "01:30" 或 "7/25 01:30"
                if ':' in candidate or re.match(r'\d{1,2}:\d{2}', candidate):
                    match_time = candidate
                    break
        if not match_time and len(tds) > 3:
            match_time = tds[3].get_text(strip=True)

        # 主队 — 尝试多个位置
        home = ''
        for hi in [5, 4, 6]:
            if len(tds) > hi:
                home_a = tds[hi].find('a')
                if home_a:
                    home = home_a.get_text(strip=True)
                    break
        if not home and len(tds) > 5:
            home = tds[5].get_text(strip=True)

        # 客队 — 尝试多个位置
        away = ''
        for ai in [7, 6, 8]:
            if len(tds) > ai:
                away_a = tds[ai].find('a')
                if away_a:
                    away = away_a.get_text(strip=True)
                    break
        if not away and len(tds) > 7:
            away = tds[7].get_text(strip=True)

        matches[match_id] = {
            'match_name': f'{home} vs {away}',
            'home': home,
            'away': away,
            'league': league,
            'match_time': match_time,
            'jingcai_id': '',  # 北单无竞彩编号
            'beidan_id': beidan_id,
            'source': 'bd',
        }

    return matches


async def fetch_match_list_playwright(source='all'):
    """用Playwright从 live.zgzcw.com 获取竞彩+北单比赛列表

    策略:
    1. 启动Playwright浏览器
    2. 先访问 www.zgzcw.com 建立WAF cookie
    3. 分别加载竞彩(jz)和北单(bd)页面
    4. 等待WAF验证通过后解析HTML
    5. 按match_id去重合并

    Args:
        source: 'jz'=仅竞彩, 'bd'=仅北单, 'all'=竞彩+北单

    Returns:
        {match_id: {match_name, home, away, league, match_time, jingcai_id, beidan_id, source}}
    """
    from playwright.async_api import async_playwright

    print("[1/3] 获取比赛列表 (Playwright)...")

    all_matches = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await browser.new_context(
            user_agent=HEADERS['User-Agent'],
            viewport={'width': 1920, 'height': 1080},
        )
        await context.add_init_script(ANTI_DETECT_SCRIPT)
        page = await context.new_page()

        # 先访问主站建立WAF cookie（有助于后续子域名通过验证）
        print("  预热: 访问 www.zgzcw.com 建立 WAF cookie...")
        try:
            await page.goto('https://www.zgzcw.com/', timeout=20000,
                            wait_until='domcontentloaded')
            await asyncio.sleep(3)
            cookie_count = len(await context.cookies())
            print(f"  预热完成, cookie数={cookie_count}")
        except Exception as e:
            print(f"  预热失败(非致命): {e}")

        # --- 竞彩比赛列表 ---
        if source in ('jz', 'all'):
            print("\n  --- 竞彩 (jz) ---")
            jz_html = await _playwright_fetch_page(
                page,
                'https://live.zgzcw.com/jz/',
                wait_for_selector='tr.matchTr',
                min_html_len=50000,
                label='竞彩列表'
            )
            if jz_html:
                jz_matches = _parse_jz_match_list(jz_html)
                print(f"  竞彩: 找到 {len(jz_matches)} 场比赛")
                for mid, info in list(jz_matches.items())[:3]:
                    print(f"    {info['jingcai_id']} {info['match_name']} ({info['league']})")
                all_matches.update(jz_matches)
            else:
                print("  竞彩: ✗ 获取失败（WAF拦截或页面加载异常）")

        # --- 北单比赛列表 ---
        if source in ('bd', 'all'):
            print("\n  --- 北单 (bd) ---")
            bd_html = await _playwright_fetch_page(
                page,
                'https://live.zgzcw.com/bd/',
                wait_for_selector='tr.matchTr',
                min_html_len=50000,
                label='北单列表'
            )
            if bd_html:
                bd_matches = _parse_bd_match_list(bd_html)
                print(f"  北单: 找到 {len(bd_matches)} 场比赛")
                for mid, info in list(bd_matches.items())[:3]:
                    bd_id = info.get('beidan_id', '')
                    print(f"    北单{bd_id} {info['match_name']} ({info['league']})")
                # 去重：如果竞彩已有同一match_id，保留竞彩信息（更完整），补充北单编号
                for mid, info in bd_matches.items():
                    if mid in all_matches:
                        # 已有竞彩记录，仅补充beidan_id
                        all_matches[mid]['beidan_id'] = info.get('beidan_id', '')
                        all_matches[mid]['source'] = 'jz+bd'
                    else:
                        all_matches[mid] = info
            else:
                print("  北单: ✗ 获取失败（WAF拦截或页面加载异常）")

        await browser.close()

    # 汇总
    jz_count = sum(1 for m in all_matches.values() if m.get('source', '') in ('jz', 'jz+bd'))
    bd_only_count = sum(1 for m in all_matches.values() if m.get('source', '') == 'bd')
    both_count = sum(1 for m in all_matches.values() if m.get('source', '') == 'jz+bd')
    print(f"\n  合计: {len(all_matches)} 场比赛 (竞彩{jz_count}场含{both_count}场兼北单, 纯北单{bd_only_count}场)")

    return all_matches


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

        # 先访问fenxi子域名首页建立WAF cookie
        print("  预热: 访问 fenxi.zgzcw.com 建立 WAF cookie...")
        try:
            await page.goto('http://fenxi.zgzcw.com/', timeout=15000,
                            wait_until='domcontentloaded')
            await asyncio.sleep(3)
        except Exception as e:
            print(f"  预热失败(非致命): {e}")

        for i, mid in enumerate(match_ids):
            info = match_info.get(mid, {})
            src = info.get('source', '')
            bd_id = info.get('beidan_id', '')
            jc_id = info.get('jingcai_id', '')
            label = f"{mid}"
            if jc_id:
                label += f" [{jc_id}]"
            if bd_id:
                label += f" [北单{bd_id}]"

            print(f"  [{i+1}/{len(match_ids)}] {label}...", end=' ', flush=True)
            try:
                companies = await scrape_single_match(page, mid)
            except Exception as e:
                print(f"✗ 异常: {e}")
                companies = None

            if companies:
                results[mid] = {
                    'match_name': info.get('match_name', ''),
                    'league': info.get('league', ''),
                    'match_time': info.get('match_time', ''),
                    'jingcai_id': info.get('jingcai_id', ''),
                    'beidan_id': info.get('beidan_id', ''),
                    'source': src,
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
    html = ''
    for attempt in range(WAF_MAX_WAIT):
        await asyncio.sleep(WAF_CHECK_INTERVAL)
        try:
            html = await page.content()
        except Exception:
            # 页面正在导航中（WAF跳转），继续等待
            continue

        # 检查WAF拦截
        if 'The access is blocked' in html or '访问被拦截' in html:
            continue

        # 检查数据加载完成
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

    ⚠️ 铁律：严禁使用赔率反算Kelly指数和赔付率，只从页面data属性直接读取
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

        # 凯利指数 td[12,13,14] — 直接从页面读取，严禁反算
        kelly = [_get_data_float(tds[i]) for i in [12, 13, 14]]

        # 赔付率 td[15] — 直接从页面读取，严禁反算
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
                               'league': '', 'match_time': '', 'jingcai_id': '',
                               'beidan_id': '', 'source': 'manual'}
    else:
        match_info = await fetch_match_list_playwright(source=args.source)
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
    jz_new = sum(1 for m in results.values() if m.get('source', '') in ('jz', 'jz+bd'))
    bd_new = sum(1 for m in results.values() if 'bd' in m.get('source', ''))
    print(f"\n{'='*50}")
    print(f"总计: {len(results)}场比赛 (竞彩{jz_new}, 含北单{bd_new}), "
          f"{total_companies}家公司数据, {target_count}条目标公司")
    return output


if __name__ == '__main__':
    asyncio.run(run())
