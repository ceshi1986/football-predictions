#!/usr/bin/env python3
"""
500.com 全量凯利数据抓取脚本 v4
修复：按TD精确解析payout和kelly值（解决部分公司嵌套表格导致全行nums索引错位）
"""
import json, os, re, time, requests
from bs4 import BeautifulSoup
from datetime import datetime

OUTPUT_DIR = "/app/data/所有对话/主对话/fp-repo/data/500com_daily"
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
    if len(td2_nums) < 6:
        return None
    # HTML列顺序：前3个=初盘，后3个=即时；我们需要即时（最新）数据
    odds_h, odds_d, odds_a = float(td2_nums[3]), float(td2_nums[4]), float(td2_nums[5])
    td4_text = tds[4].get_text()
    parts = td4_text.split('%')
    if len(parts) < 3:
        return None
    try:
        # parts[0]=初盘返还率, parts[1]=即时返还率
        payout = float(parts[1].strip()) / 100.0
    except:
        return None
    kelly_nums = re.findall(r'[\d.]+', parts[2])
    if len(kelly_nums) < 6:
        return None
    # kelly前3个=初盘，后3个=即时；我们需要即时（最新）数据
    kelly_h, kelly_d, kelly_a = float(kelly_nums[-3]), float(kelly_nums[-2]), float(kelly_nums[-1])
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

def extract_odds_from_kelly(kelly_data):
    """
    从 kelly_data_full.json 提取赔率，生成 odds_api_odds.json 格式。
    当 The Odds API 配额耗尽时，用 500com 抓取的公司赔率作为替代数据源。
    取多家主流公司赔率平均，更稳健。
    """
    PRIORITY = ['Bet365', '威廉希尔', '立博', '韦德', '易胜博', 'Pinnacle', 'Bwin', 'Interwetten']
    LEAGUE_MAP = {
        '英超': ('eng.1', '英超'), '西甲': ('esp.1', '西甲'), '德甲': ('ger.1', '德甲'),
        '意甲': ('ita.1', '意甲'), '法甲': ('fra.1', '法甲'), '葡超': ('por.1', '葡超'),
        '荷甲': ('ned.1', '荷甲'), '瑞典超': ('swe.1', '瑞超'), '瑞超': ('swe.1', '瑞超'),
        '挪超': ('nor.1', '挪超'), '芬超': ('fin.1', '芬超'), '日职': ('jpn.1', '日职'),
        '韩K': ('kor.1', '韩K'), '韩K联': ('kor.1', '韩K'), '美职联': ('usa.1', '美职联'),
        '巴甲': ('bra.1', '巴甲'), '阿甲': ('arg.1', '阿甲'), '墨西联': ('mex.1', '墨超'),
        '墨超': ('mex.1', '墨超'), '比甲': ('bel.1', '比甲'), '奥甲': ('aut.1', '奥甲'),
        '土超': ('tur.1', '土超'), '欧冠': ('uefa.champions', '欧冠'), '欧联': ('uefa.europa', '欧联'),
        '世界杯': ('fifa.world', '世界杯'), '世俱杯': ('fifa.club.world.cup', '世俱杯'),
        '中超': ('chn.1', '中超'), '澳超': ('aus.1', '澳超'),
        '澳首超': ('aus.act', '澳首超'), '澳布甲': ('aus.brisbane', '澳布甲'),
        '日职乙': ('jpn.2', '日职乙'), '韩K2': ('kor.2', '韩K2'),
        '英冠': ('eng.2', '英冠'), '德乙': ('ger.2', '德乙'), '西乙': ('esp.2', '西乙'),
        '意乙': ('ita.2', '意乙'), '法乙': ('fra.2', '法乙'),
    }
    
    matches_out = []
    for m in kelly_data.get('matches', []):
        companies = m.get('companies', {})
        if not companies:
            continue
        
        # 收集主流公司赔率取平均
        odds_list = []
        for cname in PRIORITY:
            if cname in companies and companies[cname]:
                c = companies[cname][0]
                if c.get('odds_h', 0) > 1 and c.get('odds_d', 0) > 1 and c.get('odds_a', 0) > 1:
                    odds_list.append((c['odds_h'], c['odds_d'], c['odds_a']))
        
        # 如果主流都没有，遍历所有公司
        if not odds_list:
            for cname, cdata in companies.items():
                if cdata and cdata[0].get('odds_h', 0) > 1 and cdata[0].get('odds_d', 0) > 1 and cdata[0].get('odds_a', 0) > 1:
                    odds_list.append((cdata[0]['odds_h'], cdata[0]['odds_d'], cdata[0]['odds_a']))
        
        if not odds_list:
            continue
        
        avg_w = round(sum(o[0] for o in odds_list) / len(odds_list), 2)
        avg_d = round(sum(o[1] for o in odds_list) / len(odds_list), 2)
        avg_l = round(sum(o[2] for o in odds_list) / len(odds_list), 2)
        
        # 映射联赛
        league_raw = m.get('league', '')
        league_code, league_short = 'other', league_raw
        for keyword, (code, short) in LEAGUE_MAP.items():
            if keyword in league_raw:
                league_code, league_short = code, short
                break
        
        # 解析比赛时间
        match_time_raw = m.get('match_time', '')
        date_iso = ''
        try:
            dt = datetime.strptime(match_time_raw, '%Y-%m-%d %H:%M')
            date_iso = dt.strftime('%Y-%m-%dT%H:%M:00+08:00')
        except:
            date_iso = kelly_data.get('date', '') + 'T00:00:00+08:00'
        
        matches_out.append({
            'home': m['home'], 'away': m['away'],
            'homeEN': '', 'awayEN': '',
            'date': date_iso,
            'league': league_code, 'leagueShort': league_short,
            'odds': {'w': avg_w, 'd': avg_d, 'l': avg_l},
            'source': '500com_kelly'
        })
    
    today = datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00')
    output = {
        'generated_at': today,
        'source': '500com_kelly_derived',
        'total_matches': len(matches_out),
        'matches': matches_out
    }
    
    # 写入 data/odds_api_odds.json
    out_path = os.path.join(os.path.dirname(OUTPUT_DIR), 'odds_api_odds.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[赔率提取] 从Kelly数据提取 {len(matches_out)} 场赔率 → {out_path}")
    return output


def scrape_all(extra_ids=None):
    today = datetime.now().strftime('%Y%m%d')
    out = os.path.join(OUTPUT_DIR, today, 'kelly_data_full.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    session = requests.Session()
    print("[1/4] 获取赛事列表...")
    ids = get_match_ids(session)
    print(f"  weekfixture: {len(ids)}场")
    if extra_ids:
        s = set(ids)
        added = [m for m in extra_ids if m not in s]
        ids.extend(added)
        if added: print(f"  补充额外: {len(added)}场")
    print(f"  总计: {len(ids)}场")
    if not ids: return None
    print(f"[2/4] 抓取凯利数据...")
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
    print(f"\n[3/4] 保存数据...")
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  ✅ {len(matches)}场 {tc}条公司数据 → {out}")
    
    print(f"\n[4/4] 提取赔率生成 odds_api_odds.json...")
    odds_result = extract_odds_from_kelly(result)
    print(f"  ✅ {odds_result['total_matches']} 场赔率已提取")
    
    print(f"\n{'='*40}")
    print(f"全部完成: {len(matches)}场比赛, {tc}条公司数据, {odds_result['total_matches']}场赔率")
    return result

if __name__ == '__main__':
    scrape_all(extra_ids=JINGCAI_EXTRA_IDS)
