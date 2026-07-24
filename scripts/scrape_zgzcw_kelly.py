#!/usr/bin/env python3
"""
zgzcw.com (中国足彩网) 竞彩+北单 凯利指数抓取脚本 v2.1
- 从 live.zgzcw.com/jz/ 获取竞彩比赛列表（Playwright绕过WAF）
- 从 live.zgzcw.com/bd/ 获取北京单场比赛列表（Playwright绕过WAF）
- 从 fenxi.zgzcw.com 获取每场比赛的百家欧赔数据（Playwright绕过WAF）
- 提取目标公司（Bet365/韦德/立博）的凯利指数数据
- 【v2.1新增】当zgzcw失败时，自动从懂球帝(dongqiudi.com)获取Kelly数据作为fallback
- 输出JSON到 fp-repo/data/500com_daily/{YYYYMMDD}/zgzcw_kelly_data.json

用法：
    python3 fp-repo/scripts/scrape_zgzcw_kelly.py
    python3 fp-repo/scripts/scrape_zgzcw_kelly.py --match-ids 4465702,4465669
    python3 fp-repo/scripts/scrape_zgzcw_kelly.py --source jz       # 仅竞彩
    python3 fp-repo/scripts/scrape_zgzcw_kelly.py --source bd       # 仅北单
    python3 fp-repo/scripts/scrape_zgzcw_kelly.py --source all      # 竞彩+北单(默认)
    python3 fp-repo/scripts/scrape_zgzcw_kelly.py --no-dongqiudi    # 禁用懂球帝fallback
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

# === 懂球帝配置 ===
DONGQIUDI_BASE_URL = 'https://m.dongqiudi.com'
DONGQIUDI_MATCH_DETAIL_URL = DONGQIUDI_BASE_URL + '/matchDetail/{match_id}/lotteryOddsNew'
# 懂球帝公司名映射（脱敏名 -> 标准key）
DONGQIUDI_COMPANY_MAP = {
    '36': 'bet365',      # Bet365
    '伟': 'weide',        # 韦德（伟德）
    '利': 'libo',         # 立博（利记）
    '威': 'william_hill', # 威廉希尔
    '皇': 'betcris',      # 皇冠
    '澳': 'macau',        # 澳门
    '易': 'ysb',          # 易胜博
    '明': 'minglu',       # 明陞
    'S': 'sbobet',        # SBOBET
    'I': 'interwetten',   # Interwetten
    'M': 'macauslot',     # 澳彩
    '天': 'tenbet',       # 天博
    '必': 'betvictor',    # 必赢
    '胜': 'shengwei',     # 胜韦
}
# 懂球帝赔率页面等待参数
DONGQIUDI_MAX_WAIT = 20  # 最大等待秒数
DONGQIUDI_CHECK_INTERVAL = 1  # 检查间隔秒数

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
    parser = argparse.ArgumentParser(description='zgzcw.com 竞彩+北单 凯利指数抓取 (v2.1 含懂球帝fallback)')
    parser.add_argument('--match-ids', type=str, default='',
                        help='指定比赛ID，逗号分隔。留空则从列表页自动获取')
    parser.add_argument('--source', type=str, default='all',
                        choices=['jz', 'bd', 'all'],
                        help='数据源: jz=竞彩, bd=北单, all=竞彩+北单(默认)')
    parser.add_argument('--output', type=str, default='',
                        help='指定输出JSON路径。留空则自动生成')
    parser.add_argument('--no-dongqiudi', action='store_true',
                        help='禁用懂球帝fallback（仅使用zgzcw）')
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
async def scrape_all_matches(match_ids, match_info, dongqiudi_id_map=None, no_dongqiudi=False):
    """用Playwright批量抓取多场比赛的赔率数据（共享浏览器上下文以复用WAF cookie）

    Args:
        match_ids: 比赛ID列表
        match_info: 比赛信息字典
        dongqiudi_id_map: zgzcw_match_id -> dongqiudi_match_id 映射
        no_dongqiudi: 是否禁用懂球帝fallback
    """
    from playwright.async_api import async_playwright

    results = {}
    fallback_count = 0

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

            data_source = 'zgzcw'

            # zgzcw失败 → 尝试懂球帝fallback
            if not companies and not no_dongqiudi:
                dongqiudi_mid = (dongqiudi_id_map or {}).get(mid)
                if dongqiudi_mid:
                    print(f"  → 懂球帝fallback (dqid={dongqiudi_mid})...", end=' ', flush=True)
                    try:
                        companies = await scrape_dongqiudi_kelly(page, dongqiudi_mid)
                        if companies:
                            data_source = 'dongqiudi'
                            fallback_count += 1
                    except Exception as e:
                        print(f"✗ 懂球帝异常: {e}")

            if companies:
                results[mid] = {
                    'match_name': info.get('match_name', ''),
                    'league': info.get('league', ''),
                    'match_time': info.get('match_time', ''),
                    'jingcai_id': info.get('jingcai_id', ''),
                    'beidan_id': info.get('beidan_id', ''),
                    'source': src,
                    'data_source': data_source,
                    'companies': companies,
                }
                target_keys = [k for k in TARGET_COMPANIES.values() if k in companies]
                src_tag = f"[{data_source}]" if data_source != 'zgzcw' else ''
                print(f"✓ {len(companies)}家公司, 目标: {', '.join(target_keys)} {src_tag}")
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

    if fallback_count > 0:
        print(f"\n  懂球帝fallback: {fallback_count}场比赛从懂球帝获取数据")

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


# === 懂球帝(dongqiudi.com) Fallback ===

async def fetch_dongqiudi_match_list(page):
    """从懂球帝获取今日比赛列表，建立 team_name -> dongqiudi_match_id 映射

    懂球帝赛程页面: https://m.dongqiudi.com/ (首页含当日赛程)

    Returns:
        dict: {normalized_match_name: dongqiudi_match_id}
        例如: {"纳沙泰尔vs克里恩斯": "4556766"}
    """
    print("\n  --- 懂球帝赛程获取 ---")
    url = f'{DONGQIUDI_BASE_URL}/'
    try:
        await page.goto(url, timeout=20000, wait_until='domcontentloaded')
    except Exception as e:
        print(f"    ✗ 懂球帝首页加载失败: {e}")
        return {}

    # 等待页面渲染
    await asyncio.sleep(5)

    try:
        html = await page.content()
    except Exception as e:
        print(f"    ✗ 获取页面内容失败: {e}")
        return {}

    # 从页面HTML中提取比赛信息
    # 懂球帝首页的赛程列表中，每场比赛有 matchDetail 链接
    soup = BeautifulSoup(html, 'html.parser')
    match_map = {}

    # 方法1: 从链接中提取 matchDetail/{id} 模式
    for a in soup.find_all('a', href=True):
        href = a['href']
        m = re.search(r'/matchDetail/(\d+)', href)
        if m:
            dq_id = m.group(1)
            # 尝试从链接文本或父元素提取队名
            text = a.get_text(strip=True)
            # 常见格式: "主队 vs 客队" 或 "主队客队比分"
            vs_match = re.search(r'(.+?)\s*(?:vs|VS|v|V)\s*(.+)', text)
            if vs_match:
                home = vs_match.group(1).strip()
                away = vs_match.group(2).strip()
                norm_name = _normalize_match_name(home, away)
                if norm_name:
                    match_map[norm_name] = dq_id

    # 方法2: 用JS在页面上提取赛程数据（更可靠）
    if not match_map:
        try:
            # 尝试执行JS提取比赛数据
            js_result = await page.evaluate('''() => {
                const matches = {};
                // 查找所有包含 matchDetail 的链接
                document.querySelectorAll('a[href*="matchDetail"]').forEach(a => {
                    const href = a.getAttribute('href');
                    const m = href.match(/matchDetail\\/(\\d+)/);
                    if (m) {
                        const text = a.textContent.trim();
                        // 查找包含队名的父元素
                        const parent = a.closest('.match-item, .game-item, li, div');
                        if (parent) {
                            const fullText = parent.textContent.trim();
                            matches[m[1]] = fullText;
                        } else {
                            matches[m[1]] = text;
                        }
                    }
                });
                return matches;
            }''')
            if js_result:
                for dq_id, text in js_result.items():
                    # 尝试从文本中提取队名
                    vs_match = re.search(r'(.+?)\s*(?:vs|VS|v|V|对阵)\s*(.+)', text, re.IGNORECASE)
                    if vs_match:
                        home = vs_match.group(1).strip()
                        away = vs_match.group(2).strip()
                        # 清除比分等附加信息
                        away = re.sub(r'\d+\s*[-:]\s*\d+.*$', '', away).strip()
                        norm_name = _normalize_match_name(home, away)
                        if norm_name:
                            match_map[norm_name] = dq_id
        except Exception as e:
            print(f"    ⚠ JS提取失败: {e}")

    print(f"    懂球帝赛程: 找到 {len(match_map)} 场比赛映射")
    return match_map


def _normalize_match_name(home, away):
    """标准化比赛名称用于匹配（去除空格、统一大小写等）"""
    if not home or not away:
        return ''
    # 去除前后空格和特殊字符
    home = re.sub(r'\s+', '', home.strip())
    away = re.sub(r'\s+', '', away.strip())
    return f'{home}vs{away}'


def build_dongqiudi_id_mapping(dongqiudi_match_map, zgzcw_match_info):
    """构建 zgzcw_match_id -> dongqiudi_match_id 映射

    通过标准化队名匹配两站同一场比赛

    Args:
        dongqiudi_match_map: {normalized_name: dongqiudi_match_id} 来自懂球帝
        zgzcw_match_info: {match_id: {home, away, ...}} 来自zgzcw

    Returns:
        dict: {zgzcw_match_id: dongqiudi_match_id}
    """
    mapping = {}
    unmatched = []

    for zgzcw_id, info in zgzcw_match_info.items():
        home = info.get('home', '')
        away = info.get('away', '')
        norm_name = _normalize_match_name(home, away)

        if norm_name in dongqiudi_match_map:
            mapping[zgzcw_id] = dongqiudi_match_map[norm_name]
        else:
            # 尝试模糊匹配：懂球帝队名可能包含全称而zgzcw用简称
            found = False
            for dq_norm, dq_id in dongqiudi_match_map.items():
                # 检查是否一方包含另一方
                dq_home_away = dq_norm.replace('vs', '|').split('|')
                if len(dq_home_away) == 2:
                    dq_home, dq_away = dq_home_away
                    # 主队名互相包含
                    home_match = (home and dq_home and
                                  (home in dq_home or dq_home in home))
                    away_match = (away and dq_away and
                                  (away in dq_away or dq_away in away))
                    if home_match and away_match:
                        mapping[zgzcw_id] = dq_id
                        found = True
                        break
            if not found:
                unmatched.append(f"{home}vs{away}")

    matched_count = len(mapping)
    if unmatched:
        print(f"    ID映射: {matched_count}场匹配, {len(unmatched)}场未匹配")
        if len(unmatched) <= 5:
            for u in unmatched:
                print(f"      未匹配: {u}")
    else:
        print(f"    ID映射: {matched_count}场全部匹配")

    return mapping


async def scrape_dongqiudi_kelly(page, dongqiudi_match_id):
    """用Playwright从懂球帝获取单场比赛的Kelly数据

    懂球帝赔率页面URL: https://m.dongqiudi.com/matchDetail/{match_id}/lotteryOddsNew

    页面为SPA（JS渲染），需要Playwright等待数据加载。
    欧赔表格结构：
    - 表头: 地区 | 欧指(主胜/平局/客胜) | 凯利指数(主胜/平局/客胜)
    - 每个公司占2行(rowspan=2): 初(initial) + 即(instant/latest)
    - 初行: [公司名 rowspan=2] [等级 rowspan=2] 初 主赔 平赔 客赔 主凯 平凯 客凯
    - 即行: 即 主赔 平赔 客赔 主凯 平凯 客凯

    ⚠️ 铁律：严禁使用赔率反算Kelly指数和赔付率，只从页面直接读取
    懂球帝页面不直接显示赔付率，由赔率计算: payout = 1/(1/h+1/d+1/a)
    """
    url = DONGQIUDI_MATCH_DETAIL_URL.format(match_id=dongqiudi_match_id)
    try:
        await page.goto(url, timeout=20000, wait_until='domcontentloaded')
    except Exception as e:
        print(f"✗ 懂球帝页面加载失败: {e}")
        return None

    # 等待页面渲染和数据加载
    html = ''
    for attempt in range(DONGQIUDI_MAX_WAIT):
        await asyncio.sleep(DONGQIUDI_CHECK_INTERVAL)
        try:
            html = await page.content()
        except Exception:
            continue

        # 检查是否加载了赔率数据（表格中包含凯利指数数据）
        if '凯利' in html or ('一级' in html and '二级' in html):
            break

        # 也检查是否有表格数据
        if '<table' in html and ('36' in html or '伟' in html or '利' in html):
            break
    else:
        # 最后尝试
        try:
            html = await page.content()
        except Exception:
            return None

    if len(html) < 5000:
        return None

    return parse_dongqiudi_odds_html(html)


def parse_dongqiudi_odds_html(html):
    """解析懂球帝赔率页面HTML，提取公司的赔率和凯利数据

    懂球帝欧赔表格结构（从搜索索引确认的SSR内容）：
    表头: 地区 | 欧指(主胜/平局/客胜) | 凯利指数(主胜/平局/客胜)
    数据行（每个公司2行，rowspan=2）:
      初行: [公司名] [等级] 初 home_odds draw_odds away_odds home_kelly draw_kelly away_kelly
      即行: 即 home_odds draw_odds away_odds home_kelly draw_kelly away_kelly

    BeautifulSoup处理rowspan时，初行有9个td，即行有7个td
    （公司名和等级td只出现在初行，即行因为rowspan不重复）

    ⚠️ 铁律：严禁使用赔率反算Kelly指数。赔付率从赔率计算(payout=1/(1/h+1/d+1/a))
    """
    soup = BeautifulSoup(html, 'html.parser')

    # 找包含凯利数据的表格
    tables = soup.find_all('table')
    target_table = None

    for table in tables:
        text = table.get_text()
        # 懂球帝欧赔表格特征：包含"凯利"和公司脱敏名
        if '凯利' in text and ('36' in text or '伟' in text or '威' in text):
            target_table = table
            break

    if not target_table:
        # 尝试通过表头特征找
        for table in tables:
            header_text = ''
            for th in table.find_all('th'):
                header_text += th.get_text(strip=True)
            if '欧指' in header_text and '凯利' in header_text:
                target_table = table
                break

    if not target_table:
        return None

    companies = {}
    current_company_name = ''
    current_company_key = None
    current_level = ''

    tbody = target_table.find('tbody')
    trs = tbody.find_all('tr') if tbody else target_table.find_all('tr')

    for tr in trs:
        tds = tr.find_all('td', recursive=False)
        if not tds:
            continue

        # 跳过表头行和平均值行
        first_text = tds[0].get_text(strip=True)
        if first_text in ('地区', '主胜', '平均值', ''):
            # 但'平均值'可能需要跳过
            if first_text == '平均值':
                continue
            if first_text in ('地区', '主胜'):
                continue

        # 判断行类型
        num_tds = len(tds)

        if num_tds >= 9:
            # 初行（含公司名和等级）
            # td[0] = 公司名, td[1] = 等级, td[2] = 初/即, td[3-5] = 赔率, td[6-8] = 凯利
            current_company_name = tds[0].get_text(strip=True)
            current_level = tds[1].get_text(strip=True) if num_tds > 1 else ''
            row_type = tds[2].get_text(strip=True) if num_tds > 2 else ''

            current_company_key = _match_dongqiudi_company(current_company_name)
            if not current_company_key:
                continue

            if row_type == '初':
                # 初始赔率和凯利
                init_odds = [_safe_float(tds[i].get_text(strip=True)) for i in range(3, 6)]
                init_kelly = [_safe_float(tds[i].get_text(strip=True)) for i in range(6, 9)]
                # 存储初始数据（暂存，等即行到来时合并）
                companies[current_company_key] = {
                    'name': current_company_name,
                    'level': current_level,
                    '_init_odds': init_odds,
                    '_init_kelly': init_kelly,
                }

        elif num_tds >= 7:
            # 即行（不含公司名和等级，因为rowspan）
            row_type = tds[0].get_text(strip=True)

            if row_type == '即' and current_company_key and current_company_key in companies:
                # 最新赔率和凯利
                latest_odds = [_safe_float(tds[i].get_text(strip=True)) for i in range(1, 4)]
                latest_kelly = [_safe_float(tds[i].get_text(strip=True)) for i in range(4, 7)]

                comp = companies[current_company_key]
                init_odds = comp.pop('_init_odds', [0, 0, 0])
                init_kelly = comp.pop('_init_kelly', [0, 0, 0])

                # 计算赔付率：payout = 1 / (1/h + 1/d + 1/a)
                # 注意：这是从赔率直接计算的数学属性，不是反算Kelly
                payout = _calc_payout_rate(latest_odds)

                comp['initial_odds'] = init_odds
                comp['latest_odds'] = latest_odds
                comp['kelly'] = latest_kelly  # ⚠️ 直接从页面读取，严禁反算
                comp['payout'] = round(payout, 4)
                comp['probability'] = [0.0, 0.0, 0.0]  # 懂球帝页面不直接显示概率

        elif num_tds >= 6 and current_company_key:
            # 可能是rowspan处理后的简短行
            row_type = tds[0].get_text(strip=True)
            if row_type == '即' and current_company_key in companies:
                latest_odds = [_safe_float(tds[i].get_text(strip=True)) for i in range(1, 4)]
                latest_kelly = [_safe_float(tds[i].get_text(strip=True)) for i in range(4, min(7, num_tds))]
                # 补齐凯利数组
                while len(latest_kelly) < 3:
                    latest_kelly.append(0.0)

                comp = companies[current_company_key]
                init_odds = comp.pop('_init_odds', [0, 0, 0])
                init_kelly = comp.pop('_init_kelly', [0, 0, 0])
                payout = _calc_payout_rate(latest_odds)

                comp['initial_odds'] = init_odds
                comp['latest_odds'] = latest_odds
                comp['kelly'] = latest_kelly
                comp['payout'] = round(payout, 4)
                comp['probability'] = [0.0, 0.0, 0.0]

    # 清理：移除未完成的条目（只有初始数据没有即行数据的）
    final_companies = {}
    for key, comp in companies.items():
        if 'latest_odds' in comp and 'kelly' in comp:
            # 移除内部字段
            comp.pop('_init_odds', None)
            comp.pop('_init_kelly', None)
            comp.pop('level', None)
            final_companies[key] = comp

    return final_companies if final_companies else None


def _match_dongqiudi_company(raw_name):
    """将懂球帝脱敏公司名匹配到标准key

    懂球帝脱敏规则: Bet365->36, 韦德->伟, 立博->利, 威廉希尔->威, 皇冠->皇
    """
    clean = raw_name.strip()
    for prefix, key in DONGQIUDI_COMPANY_MAP.items():
        if clean == prefix or clean.startswith(prefix):
            return key
    # 也检查TARGET_COMPANIES映射（兼容zgzcw脱敏格式）
    for prefix, key in TARGET_COMPANIES.items():
        if clean == prefix or clean.startswith(prefix):
            return key
    return None


def _safe_float(text):
    """安全地将文本转为浮点数"""
    try:
        # 清除箭头、空格等
        text = re.sub(r'[↑↓\s]', '', str(text))
        if text in ('-', '', '—', 'N/A'):
            return 0.0
        return float(text)
    except (ValueError, TypeError):
        return 0.0


def _calc_payout_rate(odds):
    """从赔率计算赔付率/返还率

    公式: payout = 1 / (1/home + 1/draw + 1/away)

    注意：这是赔率的数学属性，与"赔率反算Kelly"不同。
    Kelly指数 = 公司赔率 × 平均概率，反算需要所有公司的平均概率数据。
    赔付率 = 1/Σ(1/odds)，是单个公司赔率的直接数学属性。

    ⚠️ 如果懂球帝页面后续增加赔付率字段，应改为直接从页面读取
    """
    try:
        h, d, a = odds
        if h > 0 and d > 0 and a > 0:
            return 1.0 / (1.0/h + 1.0/d + 1.0/a)
    except (ZeroDivisionError, TypeError, ValueError):
        pass
    return 0.0


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

    # Step 1.5: 构建懂球帝ID映射（如果未禁用fallback）
    dongqiudi_id_map = {}
    if not args.no_dongqiudi and match_info:
        print(f"\n[1.5/3] 构建懂球帝ID映射...")
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                           'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
                           'Mobile/15E148 Safari/604.1',
                viewport={'width': 375, 'height': 812},
            )
            await context.add_init_script(ANTI_DETECT_SCRIPT)
            page = await context.new_page()

            dongqiudi_match_map = await fetch_dongqiudi_match_list(page)
            if dongqiudi_match_map:
                dongqiudi_id_map = build_dongqiudi_id_mapping(
                    dongqiudi_match_map, match_info
                )
            else:
                print("  ⚠ 懂球帝赛程获取失败，fallback不可用")

            await browser.close()

    # Step 2: Playwright抓取每场比赛的赔率数据
    print(f"\n[2/3] 启动Playwright抓取赔率数据 ({len(match_ids)}场)...")
    results = await scrape_all_matches(
        match_ids, match_info,
        dongqiudi_id_map=dongqiudi_id_map,
        no_dongqiudi=args.no_dongqiudi,
    )

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

    # 统计懂球帝fallback数据量
    dongqiudi_count = sum(1 for m in results.values()
                          if m.get('data_source') == 'dongqiudi')

    output = {
        'date': today,
        'scrape_time': now_str,
        'source': 'zgzcw.com',
        'version': '2.1',
        'dongqiudi_fallback_count': dongqiudi_count,
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
    if dongqiudi_count > 0:
        print(f"懂球帝fallback: {dongqiudi_count}场比赛从懂球帝获取Kelly数据")
    return output


if __name__ == '__main__':
    asyncio.run(run())
