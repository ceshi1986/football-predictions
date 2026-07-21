#!/usr/bin/env python3
"""
500.com 全量凯利数据抓取脚本 v4
修复：按TD精确解析payout和kelly值（解决部分公司嵌套表格导致全行nums索引错位）
"""
import json, os, re, time, requests
from bs4 import BeautifulSoup
from datetime import datetime

OUTPUT_DIR = "/app/data/所有对话/主对话/football-predictions/data/500com_daily"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}
CID_MAP = {
    "2":"立博","3":"Bet365","5":"澳门","6":"韦德","9":"易胜博","4":"Interwetten",
    "293":"威廉希尔","11":"Bwin","14":"Coral","16":"12bet","18":"必发","67":"Unibet",
    "280":"皇冠","122":"香港马会","127":"Interwetten2","140":"Mansion88","275":"SkyBet",
    "291":"Unibet2","502":"18Bet","651":"Ladbrokes","863":"10Bet","1055":"Pinnacle",
    "1259":"Betfair","1487":"888Sport","1488":"Dafabet",
}
KEY_COMPANIES = {"3":"Bet365","6":"韦德","2":"立博","5":"澳门","293":"威廉希尔"}
JINGCAI_EXTRA_IDS = ["1446632","1427652","1427657","1440674","1440672","1449796","1440677"]

def get_match_ids(session):
    match_ids = []
    try:
        resp = session.get('https://live.500.com/weekfixture.php', headers=HEADERS, timeout=30)
        text = resp.content.decode('utf-8', errors='replace')
        seen = set()
        for m in re.finditer(r'fenxi/(?:shuju|ouzhi)-(\d+)\.shtml', text):
            mid = m.group(1)
            if mid not in seen:
                seen.add(mid)
                match_ids.append(mid)
    except Exception as e:
        print(f"  获取赛事列表失败: {e}")
    return match_ids

def parse_company_row(tr, cid):
    tds = tr.find_all('td', recursive=False)
    if len(tds) < 5:
        return None
    td2_nums = re.findall(r'[\d.]+', tds[2].get_text())
    if len(td2_nums) < 3:
        return None
    odds_h, odds_d, odds_a = float(td2_nums[0]), float(td2_nums[1]), float(td2_nums[2])
    td4_text = tds[4].get_text()
    parts = td4_text.split('%')
    if len(parts) < 3:
        return None
    try:
        payout = float(parts[0].strip()) / 100.0
    except:
        return None
    kelly_nums = re.findall(r'[\d.]+', parts[2])
    if len(kelly_nums) < 6:
        return None
    kelly_h, kelly_d, kelly_a = float(kelly_nums[0]), float(kelly_nums[1]), float(kelly_nums[2])
    if not (0.3 < kelly_h < 2.0 and 0.3 < kelly_d < 2.0 and 0.3 < kelly_a < 2.0):
        return None
    if not (0.80 < payout < 1.0):
        return None
    comp_name = CID_MAP.get(cid, tds[1].get_text(strip=True))
    return {'name': comp_name, 'data': [{'odds_h': odds_h, 'odds_d': odds_d, 'odds_a': odds_a,
            'payout': round(payout, 4), 'kelly_h': round(kelly_h, 2),
            'kelly_d': round(kelly_d, 2), 'kelly_a': round(kelly_a, 2)}]}

def parse_ouzhi_page(session, match_id):
    url = f'https://odds.500.com/fenxi/ouzhi-{match_id}.shtml'
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        text = resp.content.decode('gb2312', errors='replace')
    except Exception as e:
        return None, str(e)
    soup = BeautifulSoup(text, 'html.parser')
    team_links = soup.find_all('a', href=re.compile(r'/team/\d+/'))
    home, away = '', ''
    seen = set()
    for a in team_links:
        t = a.get_text(strip=True)
        if t and t not in seen and len(t) >= 2:
            if not home: home = t; seen.add(t)
            elif t != home and not away: away = t; break
    league = ''
    for a in soup.find_all('a', href=re.compile(r'liansai\.500\.com/zuqiu-\d+')):
        t = a.get_text(strip=True)
        if t and len(t) < 30: league = t; break
    if not league:
        m = re.search(r'(\d{2}[\u4e00-\u9fff]+(?:第\d+轮|资格赛|分组赛|附加赛|半决赛|决赛|第一圈|第二圈))', text)
        if m: league = m.group(1)
    match_time = ''
    tm = re.search(r'比赛时间\s*([\d-]+\s+[\d:]+)', text)
    if tm: match_time = tm.group(1)
    companies = {}
    for a in soup.find_all('a', href=re.compile(r'ouzhi_same\.php')):
        cm = re.search(r'cid=(\d+)', a.get('href', ''))
        if not cm: continue
        tr = a.find_parent('tr')
        if not tr: continue
        r = parse_company_row(tr, cm.group(1))
        if r: companies[r['name']] = r['data']
    if not companies: return None, "no data"
    return {'id': f'match_{match_id}', 'league': league, 'home': home, 'away': away,
            'match_time': match_time, 'companies': companies}, None

def scrape_all(extra_ids=None):
    today = datetime.now().strftime('%Y%m%d')
    out = os.path.join(OUTPUT_DIR, today, 'kelly_data_full.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    session = requests.Session()
    print("[1/3] 获取赛事列表...")
    ids = get_match_ids(session)
    print(f"  weekfixture: {len(ids)}场")
    if extra_ids:
        s = set(ids)
        added = [m for m in extra_ids if m not in s]
        ids.extend(added)
        if added: print(f"  补充额外: {len(added)}场")
    print(f"  总计: {len(ids)}场")
    if not ids: return None
    print(f"\n[2/3] 抓取凯利数据...")
    matches = []
    skipped = 0
    for i, mid in enumerate(ids):
        try:
            r, err = parse_ouzhi_page(session, mid)
            if err or not r or not r['companies']:
                skipped += 1; continue
            matches.append(r)
            ki = []
            for cid, cn in KEY_COMPANIES.items():
                if cn in r['companies']:
                    k = r['companies'][cn][0]
                    ki.append(f"{cn}({k['payout']}/{k['kelly_h']}/{k['kelly_d']}/{k['kelly_a']})")
            print(f"  [{i+1}/{len(ids)}] ✓ {r['home']} vs {r['away']} | {len(ki)}家关键 | {' '.join(ki[:3])}")
            time.sleep(0.5)
        except Exception as e:
            print(f"  [{i+1}/{len(ids)}] ✗ {e}")
            skipped += 1
    tc = sum(len(m['companies']) for m in matches)
    result = {'date': datetime.now().strftime('%Y-%m-%d'), 'matches': matches,
              'total_matches': len(matches), 'total_companies': tc, 'skipped': skipped}
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 完成: {len(matches)}场 {tc}条公司数据 → {out}")
    return result

if __name__ == '__main__':
    scrape_all(extra_ids=JINGCAI_EXTRA_IDS)
