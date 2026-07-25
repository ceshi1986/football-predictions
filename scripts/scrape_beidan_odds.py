#!/usr/bin/env python3
"""
北单赔率抓取脚本 v1.0
- 从 zgzcw.com 北单投注页面抓取当前期全部北单比赛的欧赔数据
- 页面URL: https://cp.zgzcw.com/lottery/bdplayvsforJsp.action?lotteryId=250
- 页面为server-rendered HTML，无需Playwright
- 输出JSON到 fp-repo/data/500com_daily/{YYYYMMDD}/beidan_odds.json
- 输出格式兼容 daily_predictions.py 的赔率加载逻辑

页面结构：
- 按日期分组(table#hide_box_N)，每个日期一个表格
- 每场比赛一行(tr)，11个td
- td[0]: 编号, td[1]: 联赛, td[2]: 状态+时间, td[3]: 主队(tn属性), td[5]: 客队(tn属性)
- td[7]: 数据链接(newplayid=比赛ID), td[8]: 欧赔(3个span)

用法：
    python3 fp-repo/scripts/scrape_beidan_odds.py
    python3 fp-repo/scripts/scrape_beidan_odds.py --date 20260726
    python3 fp-repo/scripts/scrape_beidan_odds.py --output /path/to/output.json
    python3 fp-repo/scripts/scrape_beidan_odds.py --upcoming   # 仅未开赛比赛
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

# === 配置 ===
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "500com_daily")
BEIDAN_URL = "https://cp.zgzcw.com/lottery/bdplayvsforJsp.action?lotteryId=250"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://cp.zgzcw.com/',
}

# 请求间隔(秒)，避免触发反爬
REQUEST_INTERVAL = 2


def parse_args():
    parser = argparse.ArgumentParser(description='北单赔率抓取脚本 v1.0')
    parser.add_argument('--date', type=str, default='',
                        help='指定输出日期(YYYYMMDD)，默认今天')
    parser.add_argument('--output', type=str, default='',
                        help='指定输出JSON路径，留空则自动生成')
    parser.add_argument('--upcoming', action='store_true',
                        help='仅输出未开赛的比赛（已开赛/已完场的跳过）')
    parser.add_argument('--verbose', action='store_true',
                        help='详细输出每场比赛信息')
    return parser.parse_args()


def fetch_beidan_page(url=BEIDAN_URL, retries=3):
    """获取北单投注页面HTML

    Args:
        url: 目标URL
        retries: 重试次数

    Returns:
        HTML字符串，失败返回None
    """
    for attempt in range(retries):
        try:
            print(f"[FETCH] 获取北单页面 (attempt {attempt+1}/{retries})...")
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.encoding = 'utf-8'

            if resp.status_code == 200:
                html = resp.text
                if len(html) < 10000:
                    print(f"  ✗ 页面内容过短 ({len(html)} bytes)，可能被拦截")
                    time.sleep(3)
                    continue
                print(f"  ✓ 页面获取成功: {len(html)} bytes")
                return html
            else:
                print(f"  ✗ HTTP {resp.status_code}")
                time.sleep(3)
        except requests.RequestException as e:
            print(f"  ✗ 请求异常: {e}")
            time.sleep(3)

    print("  ❌ 获取北单页面失败")
    return None


def parse_beidan_html(html):
    """解析北单投注页面HTML，提取所有比赛数据

    页面结构：
    - 日期分组: div.tz-t + table#hide_box_N
    - 比赛行: 11个td
      td[0] (wh-1): 编号, inner <a> has number
      td[1] (wh-2): 联赛, inner <span> has league name
      td[2] (wh-3): 状态+时间
        - 已完场: <span class="red">比分</span> + hidden spans
        - 未开赛: <span class="red">VS</span> + hidden spans with match time
      td[3] (wh-4): 主队, tn=主队名, inner <a> has name
      td[4] (wh-5): 比分 or "VS"
      td[5] (wh-6): 客队, tn=客队名, inner <a> has name
      td[6] (wh-7): 展开链接
      td[7] (wh-8): 数据链接, newplayid=比赛ID
      td[8] (wh-9): 欧赔(3个span: 胜/平/负)
      td[9] (wh-10): 欧赔2(3个span)
      td[10] (wh-11): 欧赔3(3个span)

    Returns:
        list of dict, 每场比赛一个字典
    """
    soup = BeautifulSoup(html, 'html.parser')
    matches = []

    # 提取期号信息
    period = ''
    for ta in soup.find_all('textarea'):
        text = ta.get_text(strip=True)
        m = re.search(r'issue["\s:]+(\d+)', text)
        if m:
            period = m.group(1)
            break

    # 提取日期分组
    # 每个日期: div.tz-t -> table#hide_box_N
    date_divs = soup.find_all('div', class_='tz-t')

    for date_div in date_divs:
        # 解析日期文本: "2026-07-25星期六64场比赛隐藏"
        date_text = date_div.get_text(strip=True)
        date_match = re.match(r'(\d{4}-\d{2}-\d{2})', date_text)
        if not date_match:
            continue
        match_date = date_match.group(1).replace('-', '')  # 20260725
        match_date_iso = date_match.group(1)  # 2026-07-25

        # 找到紧随其后的数据表格
        table = date_div.find_next_sibling('table')
        if not table:
            continue

        # 解析表格中的比赛行
        for tr in table.find_all('tr'):
            tds = tr.find_all('td', recursive=False)
            if len(tds) < 9:
                continue  # 跳过分隔行和空行

            try:
                match = _parse_match_row(tds, match_date, match_date_iso)
                if match:
                    matches.append(match)
            except Exception as e:
                # 单行解析失败不影响其他行
                print(f"  ⚠ 行解析异常: {e}")
                continue

    return matches, period


def _parse_match_row(tds, match_date, match_date_iso):
    """解析单行比赛数据

    Args:
        tds: 该行的所有td元素
        match_date: 日期字符串 YYYYMMDD
        match_date_iso: 日期字符串 YYYY-MM-DD

    Returns:
        dict or None
    """
    # === 编号 ===
    td0 = tds[0]
    # 编号在 <a> 标签内（<a>文本是正确编号，td文本是编号重复如"33"->3, "2929"->29）
    a0 = td0.find('a')
    beidan_id = a0.get_text(strip=True) if a0 else td0.get_text(strip=True)

    # === 联赛 ===
    td1 = tds[1]
    league = td1.get('title', '') or td1.get_text(strip=True)

    # === 状态和时间 ===
    td2 = tds[2]
    status = 'unknown'
    match_time = ''

    # 检查状态
    status_span = td2.find('span', class_='red')
    if status_span:
        status_text = status_span.get_text(strip=True)
        if status_text == 'VS':
            status = 'upcoming'
        elif re.match(r'\d+:\d+', status_text):
            status = 'finished'
        else:
            status = 'live'

    # 提取比赛时间（从隐藏的span中）
    for span in td2.find_all('span'):
        title = span.get('title', '')
        # 格式: "比赛时间:2026-07-24 23:30"
        time_match = re.search(r'比赛时间:(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', title)
        if time_match:
            match_time = time_match.group(1).strip()
            break

    # 如果没有比赛时间，尝试从截期时间推算
    if not match_time:
        for span in td2.find_all('span'):
            title = span.get('title', '')
            cutoff_match = re.search(r'截期时间:(\d{2}:\d{2})', title)
            if cutoff_match:
                cutoff_time = cutoff_match.group(1)
                # 如果截期时间在22:00之后，可能是次日比赛
                match_time = f"{match_date_iso} {cutoff_time}"
                break

    # 如果仍然没有时间，用日期填充
    if not match_time:
        match_time = match_date_iso

    # === 主队 ===
    td3 = tds[3]
    home = td3.get('tn', '')  # tn属性有干净的队名
    if not home:
        home_a = td3.find('a')
        home = home_a.get_text(strip=True) if home_a else td3.get_text(strip=True)
    # 清理排名后缀 [16]
    home = re.sub(r'\[\d+\]$', '', home).strip()

    # === 客队 ===
    td5 = tds[5] if len(tds) > 5 else None
    away = ''
    if td5:
        away = td5.get('tn', '')
        if not away:
            away_a = td5.find('a')
            away = away_a.get_text(strip=True) if away_a else td5.get_text(strip=True)
        # 清理排名前缀 [5]
        away = re.sub(r'^\[\d+\]', '', away).strip()

    # === 比赛ID (newplayid) ===
    match_id = ''
    if len(tds) > 7:
        td7 = tds[7]
        match_id = td7.get('newplayid', '')

    # === 欧赔 ===
    # 从 td[8] 的3个span中提取
    odds = _parse_odds_from_td(tds[8] if len(tds) > 8 else None)

    # 如果第一组赔率为空，尝试 td[9] 和 td[10]
    if not odds:
        for idx in [9, 10]:
            if len(tds) > idx:
                odds = _parse_odds_from_td(tds[idx])
                if odds:
                    break

    if not odds:
        return None  # 无赔率数据，跳过

    return {
        'beidan_id': beidan_id,
        'league': league,
        'match_date': match_date,
        'match_time': match_time,
        'home': home,
        'away': away,
        'status': status,
        'match_id': match_id,
        'odds': odds,
        'source': '北单',
    }


def _parse_odds_from_td(td):
    """从td元素中的3个span提取欧赔（胜/平/负）

    Args:
        td: BeautifulSoup td元素

    Returns:
        dict {"w": float, "d": float, "l": float} or None
    """
    if not td:
        return None

    spans = td.find_all('span')
    if len(spans) < 3:
        return None

    try:
        w = float(spans[0].get_text(strip=True))
        d = float(spans[1].get_text(strip=True))
        l = float(spans[2].get_text(strip=True))

        # 验证赔率有效性
        if w <= 1.0 or d <= 1.0 or l <= 1.0:
            return None

        return {"w": w, "d": d, "l": l}
    except (ValueError, IndexError):
        return None


def filter_upcoming(matches):
    """过滤出未开赛的比赛

    Args:
        matches: 全部比赛列表

    Returns:
        未开赛比赛列表
    """
    upcoming = []
    for m in matches:
        if m['status'] == 'upcoming':
            upcoming.append(m)
        elif m['status'] == 'finished':
            # 已完场但可能有赔率数据，保留（用于历史参考）
            pass
        elif m['status'] == 'unknown':
            # 未知状态，如果有赔率则保留
            if m.get('odds'):
                upcoming.append(m)
    return upcoming


def run():
    """主流程"""
    args = parse_args()

    # 确定输出日期
    date_str = args.date or datetime.now().strftime('%Y%m%d')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 确定输出路径
    if args.output:
        out_path = args.output
    else:
        out_path = os.path.join(OUTPUT_DIR, date_str, 'beidan_odds.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    print(f"{'='*60}")
    print(f"北单赔率抓取 v1.0")
    print(f"日期: {date_str}  输出: {out_path}")
    print(f"{'='*60}")

    # Step 1: 获取页面
    html = fetch_beidan_page()
    if not html:
        print("❌ 无法获取北单页面，退出")
        sys.exit(1)

    # Step 2: 解析HTML
    print(f"\n[PARSE] 解析北单页面...")
    matches, period = parse_beidan_html(html)

    if not matches:
        print("❌ 未解析到任何比赛数据")
        sys.exit(1)

    # 统计
    total = len(matches)
    upcoming = [m for m in matches if m['status'] == 'upcoming']
    finished = [m for m in matches if m['status'] == 'finished']
    with_odds = [m for m in matches if m.get('odds')]

    print(f"  期号: {period}")
    print(f"  总计: {total} 场比赛")
    print(f"  未开赛: {len(upcoming)} 场, 已完场: {len(finished)} 场")
    print(f"  有赔率: {len(with_odds)} 场")

    # 按联赛统计
    by_league = {}
    for m in matches:
        lg = m.get('league', '未知')
        if lg not in by_league:
            by_league[lg] = []
        by_league[lg].append(m)

    print(f"\n  联赛分布:")
    for lg, ms in sorted(by_league.items(), key=lambda x: -len(x[1])):
        odds_count = sum(1 for m in ms if m.get('odds'))
        upcoming_count = sum(1 for m in ms if m['status'] == 'upcoming')
        print(f"    {lg}: {len(ms)}场 (有赔率{odds_count}, 未开赛{upcoming_count})")

    # Step 3: 过滤（可选）
    if args.upcoming:
        matches = filter_upcoming(matches)
        print(f"\n[FILTER] 仅保留未开赛: {len(matches)} 场")

    # Step 4: 输出
    output = {
        'date': date_str,
        'scrape_time': now_str,
        'source': 'zgzcw.com/北单',
        'period': period,
        'total_matches': len(matches),
        'url': BEIDAN_URL,
        'matches': matches,
    }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 已保存 {len(matches)} 场北单赔率 → {out_path}")

    # Step 5: 示例输出
    if args.verbose and matches:
        print(f"\n{'='*60}")
        print("前10场比赛:")
        for m in matches[:10]:
            odds_str = ''
            if m.get('odds'):
                o = m['odds']
                odds_str = f"  欧赔: {o['w']:.2f} / {o['d']:.2f} / {o['l']:.2f}"
            print(f"  北单{m['beidan_id']:>3s} {m['league']:6s} "
                  f"{m['home']} vs {m['away']}  "
                  f"{m['status']}{odds_str}")

    return output


if __name__ == '__main__':
    run()
