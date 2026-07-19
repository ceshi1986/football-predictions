#!/usr/bin/env python3
"""Fetch football schedule from ESPN API -> schedule.json (concurrent)"""
import json, urllib.request, sys, os, concurrent.futures
from datetime import datetime, timedelta

LEAGUES = [
    ("eng.1","英超","英超",10),("esp.1","西甲","西甲",9),("ger.1","德甲","德甲",8),
    ("ita.1","意甲","意甲",7),("fra.1","法甲","法甲",6),
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
    "Semifinal 1 Winner":"英格兰","Semifinal 2 Winner":"阿根廷",
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
    # 巴甲
    "Atlético-MG":"米内罗竞技","Atletico-MG":"米内罗竞技",
    "Bahia":"巴伊亚","Coritiba":"科里蒂巴","Palmeiras":"帕尔梅拉斯",
    "Chapecoense":"沙佩科恩斯","Flamengo":"弗拉门戈","Internacional":"国际体育",
    "Cruzeiro":"克鲁塞罗","São Paulo":"圣保罗","Sao Paulo":"圣保罗",
    "Athletico-PR":"帕拉纳竞技","Botafogo":"博塔弗戈","Vitória":"维多利亚","Vitoria":"维多利亚",
    "Corinthians":"科林蒂安","Remo":"雷莫",
    # 阿甲
    "Belgrano (Córdoba)":"贝尔格拉诺","Belgrano":"贝尔格拉诺",
    "Rosario Central":"罗萨里奥中央",
    "Sarmiento (Junín)":"萨米恩托","Sarmiento":"萨米恩托",
    "Argentinos Juniors":"阿根廷青年人",
    "Defensa y Justicia":"国防与司法","Aldosivi":"阿尔多西维",
    "Gimnasia (Mendoza)":"门多萨体操","Gimnasia La Plata":"拉普拉塔体操",
    "Central Córdoba (Santiago del Estero)":"圣地亚哥中央科尔多瓦",
    "Racing Club":"竞赛","Vélez Sarsfield":"萨斯菲尔德","Velez Sarsfield":"萨斯菲尔德",
    "Instituto (Córdoba)":"科尔多瓦学院","Instituto":"科尔多瓦学院",
    "Huracán":"飓风","Huracan":"飓风","Banfield":"班菲尔德",
    "Platense":"普拉滕斯","Unión (Santa Fe)":"圣菲联合","Union (Santa Fe)":"圣菲联合",
    # 挪超
    "Hamarkameratene":"哈马坎","Tromso":"特罗姆瑟","Tromsø":"特罗姆瑟",
    "IK Start":"斯塔特","Rosenborg":"罗森博格",
    "Kristiansund BK":"克里斯蒂安松","Sarpsborg FK":"萨尔普斯博格",
    "Lillestrom":"利勒斯特罗姆","Lillestrøm":"利勒斯特罗姆",
    "KFUM Oslo":"奥斯陆KFUM","Molde":"莫尔德","SK Brann":"布兰",
    "Viking FK":"维京","Sandefjord":"桑德菲尤尔",
    "Bodo/Glimt":"博德闪耀","Bodø/Glimt":"博德闪耀",
    # 瑞典超
    "AIK":"AIK索尔纳","GAIS":"盖斯",
    "BK Häcken":"哈根","Hammarby IF":"哈马比",
    "Degerfors IF":"代格福什","Djurgården":"尤尔加登","Djurgarden":"尤尔加登",
    "Halmstads BK":"哈尔姆斯塔德","IF Elfsborg":"埃尔夫斯堡",
    "IK Sirius":"西里乌斯","Kalmar FF":"卡尔马",
    "Malmö FF":"马尔默","Malmö":"马尔默","Malmoe":"马尔默",
    "Örgryte IS":"奥格里特","Orgryte IS":"奥格里特",
    "Västerås SK":"瓦斯特拉斯","Vasteras SK":"瓦斯特拉斯",
    # 芬超
    "HJK Helsinki":"赫尔辛基","KuPS Kuopio":"古比斯","KuPS":"古比斯",
    "FC Inter Turku":"国际图尔库","Inter Turku":"国际图尔库",
    "VPS Vaasa":"VPS瓦萨","VPS":"VPS瓦萨",
    "AC Oulu":"奥卢","IF Gnistan":"格尼斯坦","Gnistan":"格尼斯坦",
    "TPS Turku":"TPS图尔库","TPS":"TPS图尔库",
    "FC Lahti":"拉赫蒂","Lahti":"拉赫蒂",
    "Ilves Tampere":"埃尔维斯","Ilves":"埃尔维斯",
    "SJK Seinäjoki":"塞那乔其","SJK":"塞那乔其",
    "Jaro":"雅罗","FF Jaro":"雅罗",
    "IFK Mariehamn":"玛丽港","Mariehamn":"玛丽港",
    # 奥甲
    "SK Sturm Graz":"格拉茨风暴","Sturm Graz":"格拉茨风暴",
    "Red Bull Salzburg":"萨尔茨堡","RB Salzburg":"萨尔茨堡",
    "Rapid Wien":"维也纳快速","Rapid Vienna":"维也纳快速",
    "Austria Wien":"维也纳奥地利","Austria Vienna":"维也纳奥地利",
    "LASK":"林茨","Wolfsberger AC":"沃尔夫斯贝格",
    "Hartberg":"哈特贝格","TSV Hartberg":"哈特贝格",
    "WSG Tirol":"蒂罗尔","Altach":"阿尔塔赫",
    "SCR Altach":"阿尔塔赫","Blau-Weiß Linz":"蓝白林茨",
    "Austria Klagenfurt":"克拉根福","Grazer AK":"格拉茨AK",
    "Austria Lustenau":"卢斯特瑙","Ried":"里德",
    "Rheindorf Altach":"莱因多夫阿尔塔赫",
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
    
    # ---- 合并手动维护的资格赛数据（ESPN不覆盖早期资格赛） ----
    qualifiers_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'qualifiers.json')
    if os.path.exists(qualifiers_path):
        try:
            with open(qualifiers_path, 'r', encoding='utf-8') as qf:
                qdata = json.load(qf)
                qmatches = qdata.get('matches', [])
                # 只合并当前7天窗口内的资格赛
                qmin = min(dates)
                qmax = max(dates)
                for qm in qmatches:
                    if qm['id'] in seen:
                        continue
                    # 提取日期部分 YYYYMMDD
                    qdate = qm.get('date', '')[:10].replace('-', '')
                    if qmin <= qdate <= qmax:
                        matches.append(qm)
                        seen[qm['id']] = True
                print(f"Merged {len([m for m in qmatches if m['id'] in seen])} qualifier matches")
        except Exception as e:
            print(f"Warning: failed to merge qualifiers.json: {e}")

    matches.sort(key=lambda x: (-x.get('weight',0), x.get('date','')))
    out = {"generated_at":datetime.utcnow().isoformat()+"Z","dates":dates,"total_matches":len(matches),"matches":matches}
    outpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'schedule.json')
    with open(outpath,'w',encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Done: {len(matches)} matches -> schedule.json")

if __name__=='__main__':
    main()
