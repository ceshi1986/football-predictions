#!/usr/bin/env python3
"""
500.com 全量凯利数据抓取脚本 v3
方案：requests直接请求 + gb2312解码 + BeautifulSoup解析
不依赖Playwright（速度快、无编码问题）

数据源：
1. https://live.500.com/weekfixture.php - 获取所有未来比赛列表及match_id
2. https://odds.500.com/fenxi/ouzhi-{match_id}.shtml - 获取每家公司的凯利指数

输出格式兼容 kelly_data_full.json 结构
"""
import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

OUTPUT_DIR = "/app/data/所有对话/主对话/football-predictions/data/500com_daily"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

# CID到公司名映射
CID_MAP = {
    "2": "立博", "3": "Bet365", "5": "澳门", "6": "韦德",
    "9": "易胜博", "4": "Interwetten", "293": "威廉希尔",
    "11": "Bwin", "14": "Coral", "16": "12bet", "18": "必发",
    "67": "Unibet", "280": "皇冠", "122": "香港马会",
    "127": "Interwetten2", "140": "Mansion88", "275": "SkyBet",
    "291": "Unibet2", "502": "18Bet", "651": "Ladbrokes",
    "863": "10Bet", "1055": "Pinnacle", "1259": "Betfair",
    "1487": "888Sport", "1488": "Dafabet",
}

# 关键公司（用于凯利七场景分析）
KEY_COMPANIES = {"3": "Bet365", "6": "韦德", "2": "立博", "5": "澳门", "293": "威廉希尔"}


def get_match_ids_from_weekfixture(session):
    """从weekfixture页面获取所有比赛ID"""
    match_ids = []
    try:
        resp = session.get('https://live.500.com/weekfixture.php', headers=HEADERS, timeout=30)
        text = resp.content.decode('utf-8', errors='replace')
        
        # 提取所有shuju/ouzhi链接的match_id
        seen = set()
        for m in re.finditer(r'fenxi/(?:shuju|ouzhi)-(\d+)\.shtml', text):
            mid = m.group(1)
            if mid not in seen:
                seen.add(mid)
                match_ids.append(mid)
    except Exception as e:
        print(f"  获取赛事列表失败: {e}")
    
    return match_ids


def parse_ouzhi_page(session, match_id):
    """解析单个比赛的凯利数据页面，返回结构化数据"""
    url = f'https://odds.500.com/fenxi/ouzhi-{match_id}.shtml'
    
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        text = resp.content.decode('gb2312', errors='replace')
    except Exception as e:
        return None, str(e)
    
    soup = BeautifulSoup(text, 'html.parser')
    
    # 提取队名（取第一个有文本的team链接为主队，第二个为客队）
    team_links = soup.find_all('a', href=re.compile(r'/team/\d+/'))
    home, away = '', ''
    seen_teams = set()
    for a in team_links:
        t = a.get_text(strip=True)
        if t and t not in seen_teams and len(t) >= 2:
            if not home:
                home = t
                seen_teams.add(t)
            elif t != home and not away:
                away = t
                break
    
    # 提取联赛（从 /zuqiu-\d+/ 链接获取，如 "26巴甲第19轮"）
    league = ''
    for a in soup.find_all('a', href=re.compile(r'liansai\.500\.com/zuqiu-\d+')):
        t = a.get_text(strip=True)
        if t and len(t) < 30:
            league = t
            break
    # 备用：从body文本中提取联赛信息
    if not league:
        league_m = re.search(r'(\d{2}[\u4e00-\u9fff]+(?:第\d+轮|资格赛|分组赛|附加赛|半决赛|决赛|第一圈|第二圈))', text)
        if league_m:
            league = league_m.group(1)
    
    # 提取比赛时间
    match_time = ''
    time_m = re.search(r'比赛时间\s*([\d-]+\s+[\d:]+)', text)
    if time_m:
        match_time = time_m.group(1)
    
    # 解析凯利数据 - 通过"ouzhi_same.php"链接定位数据行
    companies = {}
    for a in soup.find_all('a', href=re.compile(r'ouzhi_same\.php')):
        cid_m = re.search(r'cid=(\d+)', a.get('href', ''))
        if not cid_m:
            continue
        cid = cid_m.group(1)
        
        tr = a.find_parent('tr')
        if not tr:
            continue
        
        # 获取公司名
        comp_link = tr.find('a', href=re.compile(r'cid='))
        raw_name = comp_link.get_text(strip=True) if comp_link else ''
        comp_name = CID_MAP.get(cid, raw_name)
        
        # 提取所有数字
        row_text = tr.get_text()
        nums = re.findall(r'[\d.]+', row_text)
        
        if len(nums) < 18:
            continue
        
        # 数据结构：
        # [0]=序号 [1-3]=即时欧指 [4-6]=初盘欧指 [7-9]=即时概率(%)
        # [10-12]=初盘概率(%) [13]=即时返还率(%) [14]=初盘返还率(%)
        # [15-17]=即时凯利 [18-20]=初盘凯利
        try:
            odds_h = float(nums[1])
            odds_d = float(nums[2])
            odds_a = float(nums[3])
            payout = float(nums[13]) / 100  # 百分比转小数
            kelly_h = float(nums[15])
            kelly_d = float(nums[16])
            kelly_a = float(nums[17])
        except (ValueError, IndexError):
            continue
        
        # 验证凯利值合理性
        if not (0.3 < kelly_h < 2.0 and 0.3 < kelly_d < 2.0 and 0.3 < kelly_a < 2.0):
            continue
        if not (0.80 < payout < 1.0):
            continue
        
        companies[comp_name] = [{
            'odds_h': odds_h,
            'odds_d': odds_d,
            'odds_a': odds_a,
            'payout': round(payout, 4),
            'kelly_h': round(kelly_h, 2),
            'kelly_d': round(kelly_d, 2),
            'kelly_a': round(kelly_a, 2),
        }]
    
    result = {
        'id': f'match_{match_id}',
        'league': league,
        'home': home,
        'away': away,
        'match_time': match_time,
        'companies': companies
    }
    
    return result, None


def scrape_all_kelly(max_matches=None, key_only=False):
    """主抓取流程"""
    today = datetime.now().strftime('%Y%m%d')
    output_path = os.path.join(OUTPUT_DIR, today, 'kelly_data_full.json')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    session = requests.Session()
    
    # Step 1: 获取所有比赛列表
    print("[1/3] 获取500.com未来赛事列表...")
    match_ids = get_match_ids_from_weekfixture(session)
    print(f"  找到 {len(match_ids)} 场比赛")
    
    if len(match_ids) == 0:
        print("  ❌ 没有找到任何比赛")
        return None
    
    if max_matches:
        match_ids = match_ids[:max_matches]
        print(f"  限制抓取前 {max_matches} 场")
    
    # Step 2: 逐个抓取凯利数据
    print(f"\n[2/3] 逐个抓取凯利数据...")
    all_matches = []
    skipped = 0
    
    for idx, mid in enumerate(match_ids):
        try:
            result, error = parse_ouzhi_page(session, mid)
            
            if error:
                print(f"  [{idx+1}/{len(match_ids)}] ✗ {error}")
                skipped += 1
                continue
            
            if not result or not result['companies']:
                # 可能是比赛太早还没开赔
                skipped += 1
                if idx < 5 or idx % 20 == 0:
                    print(f"  [{idx+1}/{len(match_ids)}] ⚠ 无数据 (mid={mid})")
                continue
            
            all_matches.append(result)
            
            # 显示关键公司信息
            key_info = []
            for cid, cname in KEY_COMPANIES.items():
                if cname in result['companies']:
                    k = result['companies'][cname][0]
                    key_info.append(f"{cname}({k['kelly_h']}/{k['kelly_d']}/{k['kelly_a']})")
            
            print(f"  [{idx+1}/{len(match_ids)}] ✓ {result['home']} vs {result['away']} | {result['league']} | {len(result['companies'])}家公司 | {' '.join(key_info)}")
            
            # 控制请求频率
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  [{idx+1}/{len(match_ids)}] ✗ 异常: {e}")
            skipped += 1
            continue
    
    # Step 3: 保存结果
    print(f"\n[3/3] 保存数据...")
    total_companies = sum(len(m['companies']) for m in all_matches)
    output = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'matches': all_matches,
        'total_matches': len(all_matches),
        'total_companies': total_companies,
        'skipped': skipped
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*50}")
    print(f"✅ 完成！")
    print(f"   比赛数: {len(all_matches)} (跳过{skipped}场)")
    print(f"   公司数据: {total_companies}条")
    print(f"   保存到: {output_path}")
    
    return output


if __name__ == '__main__':
    import sys
    max_m = None
    if len(sys.argv) > 1:
        try:
            max_m = int(sys.argv[1])
        except:
            pass
    result = scrape_all_kelly(max_m)
