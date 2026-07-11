#!/usr/bin/env python3
"""Fetch football schedule from ESPN API -> schedule.json (concurrent)"""
import json, urllib.request, sys, os, concurrent.futures
from datetime import datetime, timedelta

LEAGUES = [
    ("eng.1","英超","英超",10),("esp.1","西甲","西甲",9),("ger.1","德甲","德甲",8),
    ("ita.1","意甲","意甲",7),("fra.1","法甲","法甲",6),("chn.1","中超","中超",3),
    ("jpn.1","日职","日职",3),("kor.1","韩K","韩K",3),
    ("uefa.champions","欧冠","欧冠",12),("uefa.europa","欧联","欧联",11),
    ("fifa.world","世界杯","世界杯",15),("por.1","葡超","葡超",5),
    ("ned.1","荷甲","荷甲",5),("bra.1","巴甲","巴甲",4),("arg.1","阿甲","阿甲",4),
    ("tur.1","土超","土超",5),("bel.1","比甲","比甲",4),("nor.1","挪超","挪超",3),
    ("swe.1","瑞典超","瑞典",3),("fin.1","芬超","芬超",3),("aut.1","奥甲","奥甲",3),
]

TEAM_ZH = {
    # 世界杯球队
    "France":"法国","Spain":"西班牙","Belgium":"比利时","Morocco":"摩洛哥",
    "Norway":"挪威","England":"英格兰","Argentina":"阿根廷","Switzerland":"瑞士",
    "Germany":"德国","Brazil":"巴西","Portugal":"葡萄牙","Netherlands":"荷兰",
    "Italy":"意大利","Uruguay":"乌拉圭","Colombia":"哥伦比亚","Mexico":"墨西哥",
    "USA":"美国","Canada":"加拿大","Japan":"日本","South Korea":"韩国",
    "Australia":"澳大利亚","Senegal":"塞内加尔","Ghana":"加纳","Cameroon":"喀麦隆",
    "Iran":"伊朗","Saudi Arabia":"沙特","Ecuador":"厄瓜多尔","Qatar":"卡塔尔",
    "Denmark":"丹麦","Croatia":"克罗地亚","Serbia":"塞尔维亚","Poland":"波兰",
    "Wales":"威尔士","Tunisia":"突尼斯","Sweden":"瑞典","Austria":"奥地利",
    "Quarterfinal 1 Winner":"1/4决赛胜者1","Quarterfinal 2 Winner":"1/4决赛胜者2",
    "Quarterfinal 3 Winner":"1/4决赛胜者3","Quarterfinal 4 Winner":"1/4决赛胜者4",
    "Semifinal 1 Winner":"半决赛胜者1","Semifinal 2 Winner":"半决赛胜者2",
    "Third Place":"季军赛","Final":"决赛",
    # 欧洲联赛球队
    "Manchester United":"曼联","Manchester City":"曼城","Liverpool":"利物浦",
    "Chelsea":"切尔西","Arsenal":"阿森纳","Tottenham Hotspur":"热刺",
    "Newcastle United":"纽卡斯尔","Aston Villa":"阿斯顿维拉",
    "West Ham United":"西汉姆","Brighton & Hove Albion":"布莱顿",
    "Crystal Palace":"水晶宫","Wolverhampton Wanderers":"狼队",
    "Everton":"埃弗顿","Nottingham Forest":"诺丁汉森林",
    "Fulham":"富勒姆","AFC Bournemouth":"伯恩茅斯",
    "Brentford":"布伦特福德","Burnley":"伯恩利",
    "Sheffield United":"谢菲联","Luton Town":"卢顿",
    "Leicester City":"莱斯特城","Leeds United":"利兹联",
    "Ipswich Town":"伊普斯维奇","Southampton":"南安普顿",
    "Real Madrid":"皇马","FC Barcelona":"巴萨","Barcelona":"巴萨",
    "Club Atlético de Madrid":"马竞","Sevilla FC":"塞维利亚",
    "Real Sociedad":"皇家社会","Real Betis":"贝蒂斯",
    "Villarreal CF":"比利亚雷亚尔","Athletic Club":"毕尔巴鄂",
    "Valencia CF":"瓦伦西亚","Getafe CF":"赫塔费",
    "RC Celta":"塞尔塔","CA Osasuna":"奥萨苏纳","RCD Mallorca":"马略卡",
    "FC Bayern Munich":"拜仁","Borussia Dortmund":"多特蒙德",
    "RB Leipzig":"莱比锡","Bayer 04 Leverkusen":"勒沃库森",
    "Eintracht Frankfurt":"法兰克福","VfL Wolfsburg":"沃尔夫斯堡",
    "SC Freiburg":"弗赖堡","1. FC Union Berlin":"柏林联合",
    "1.FSV Mainz 05":"美因茨","VfB Stuttgart":"斯图加特",
    "TSG 1899 Hoffenheim":"霍芬海姆","Borussia Mönchengladbach":"门兴",
    "FC Augsburg":"奥格斯堡","1. FC Köln":"科隆",
    "Juventus":"尤文","Inter Milan":"国米","AC Milan":"AC米兰",
    "SSC Napoli":"那不勒斯","AS Roma":"罗马","SS Lazio":"拉齐奥",
    "Atalanta BC":"亚特兰大","ACF Fiorentina":"佛罗伦萨",
    "Torino FC":"都灵","Bologna FC 1909":"博洛尼亚",
    "Udinese Calcio":"乌迪内斯","Empoli FC":"恩波利",
    "Paris Saint-Germain":"巴黎","Olympique de Marseille":"马赛",
    "Olympique Lyonnais":"里昂","AS Monaco":"摩纳哥",
    "LOSC Lille":"里尔","Stade Rennais FC":"雷恩","OGC Nice":"尼斯",
    "Shanghai Port FC":"上海海港","Shanghai Port":"上海海港",
    "Shanghai Shenhua":"上海申花","Beijing Guoan":"北京国安",
    "Shandong Taishan":"山东泰山","Changchun Yatai":"长春亚泰",
    "Wuhan Three Towns":"武汉三镇","Zhejiang FC":"浙江队",
    "Chengdu Rongcheng":"成都蓉城","Tianjin Jinmen Tiger":"天津津门虎",
}

def zh(name):
    if name in TEAM_ZH: return TEAM_ZH[name]
    # Handle World Cup stage patterns
    if "Winner" in name:
        name = name.replace("Winner", "胜者")
        import re
        name = re.sub(r'(\d+)', r'\1', name)
    for en,cn in TEAM_ZH.items():
        if en.lower() in name.lower(): return cn
    return name

def fetch_one(code, date_str):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/scoreboard?dates={date_str}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent':'ScheduleBot/1.0'})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except:
        return None

def main():
    dates = [(datetime.utcnow()+timedelta(days=i)).strftime("%Y%m%d") for i in range(7)]
    tasks = [(code,ln,ls,w,d) for code,ln,ls,w in LEAGUES for d in dates]
    matches, seen = [], {}
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(fetch_one,code,d):(code,ln,ls,w,d) for code,ln,ls,w,d in tasks}
        for f in concurrent.futures.as_completed(futures, timeout=45):
            code,ln,ls,w,d = futures[f]
            data = f.result()
            if not data or not data.get('events'): continue
            for ev in data['events']:
                if ev['id'] in seen: continue
                seen[ev['id']] = True
                c = ev['competitions'][0]
                c0,c1 = c['competitors']
                h = c0 if c0['homeAway']=='home' else c1
                a = c1 if c1['homeAway']=='away' else c0
                st = c['status']['type']['name']
                if st in ('STATUS_IN_PROGRESS','STATUS_HALFTIME','STATUS_SECOND_HALF','STATUS_FIRST_HALF'):
                    sl,sc = "进行中","live"
                elif st=='STATUS_FINAL' or c['status']['type'].get('completed'):
                    sl,sc = "已结束","finished"
                else:
                    # Format date as Chinese readable string
                    raw_date = ev.get('date','')
                    try:
                        dt = datetime.fromisoformat(raw_date.replace('Z','+00:00'))
                        from datetime import timezone
                        dt_local = dt.astimezone(timezone.utc) + timedelta(hours=8)  # UTC+8
                        weekdays = ['周一','周二','周三','周四','周五','周六','周日']
                        wd = weekdays[dt_local.weekday()]
                        sl = f"{dt_local.month}/{dt_local.day} {wd} {dt_local.hour:02d}:{dt_local.minute:02d}"
                    except:
                        sl = raw_date
                    sc = "scheduled"
                hn,an = h['team'].get('displayName',''), a['team'].get('displayName','')
                # Convert to Beijing time for date field
                raw_date = ev.get('date','')
                try:
                    dt = datetime.fromisoformat(raw_date.replace('Z','+00:00'))
                    from datetime import timezone
                    dt_beijing = dt.astimezone(timezone.utc) + timedelta(hours=8)
                    beijing_date = dt_beijing.strftime('%Y-%m-%dT%H:%M:%S') + '+08:00'
                except:
                    beijing_date = raw_date
                
                matches.append({
                    "id":ev['id'],"home":zh(hn),"away":zh(an),
                    "homeEN":hn,"awayEN":an,"date":beijing_date,
                    "league":code,"leagueName":ln,"leagueShort":ls,
                    "status":sl,"statusClass":sc,
                    "completed":c['status']['type'].get('completed',False),
                    "homeScore":int(h.get('score',0) or 0),
                    "awayScore":int(a.get('score',0) or 0),
                    "weight":w,
                })
    
    matches.sort(key=lambda x: (-x.get('weight',0), x.get('date','')))
    out = {"generated_at":datetime.utcnow().isoformat()+"Z","dates":dates,"total_matches":len(matches),"matches":matches}
    outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'schedule.json')
    with open(outpath,'w',encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Done: {len(matches)} matches -> schedule.json")

if __name__=='__main__':
    main()
