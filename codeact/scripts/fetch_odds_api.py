#!/usr/bin/env python3
"""
从 The Odds API 获取足球比赛赔率数据，转换为统一格式，
保存到 GitHub 仓库供前端读取。

用法: python fetch_odds_api.py [result_mode] [api_key]
  result_mode: display_only | notify | no_reply | auto (默认 display_only)
  api_key: The Odds API 密钥 (默认内置)
"""
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

# ─── CodeAct SDK ───
from codeact_sdk import CodeActSDK

# ─── SDK 工具 Schema Versions ───
TOOL_SCHEMA_VERSIONS = {
    "codeact_fetch_web": "v1_2c8d0580b3f93a58",
    "codeact_search_web": "v1_5ac1b0eba8c26f2a",
}

# ─── 联赛映射: sport_key → (league_code, leagueShort) ───
# 基于竞彩/北京单场赛程 + 主流联赛，精简至17个以节省API配额（2026-07-17）
SPORT_LEAGUE_MAP = {
    # === 竞彩核心赛事 ===
    "soccer_fifa_world_cup": ("fifa.world", "世界杯"),
    "soccer_uefa_champs_league": ("uefa.champions", "欧冠"),
    "soccer_uefa_europa_league": ("uefa.europa", "欧联"),
    "soccer_china_superleague": ("chn.1", "中超"),
    "soccer_japan_j_league": ("jpn.1", "日职"),
    "soccer_korea_kleague1": ("kor.1", "韩K"),
    "soccer_usa_mls": ("usa.1", "美职联"),
    "soccer_brazil_campeonato": ("bra.1", "巴甲"),
    "soccer_mexico_ligamx": ("mex.1", "墨超"),
    "soccer_sweden_allsvenskan": ("swe.1", "瑞典超"),
    "soccer_norway_eliteserien": ("nor.1", "挪超"),
    "soccer_finland_veikkausliiga": ("fin.1", "芬超"),
    # === 五大联赛（竞彩常备） ===
    "soccer_epl": ("eng.1", "英超"),
    "soccer_spain_la_liga": ("esp.1", "西甲"),
    "soccer_germany_bundesliga": ("ger.1", "德甲"),
    "soccer_italy_serie_a": ("ita.1", "意甲"),
    "soccer_france_ligue_one": ("fra.1", "法甲"),
}

# ─── 英中文名映射表 (来自前端 _ESPN_CN) ───
TEAM_EN_CN = {
    # 英超
    "Manchester United": "曼联", "Man United": "曼联", "Manchester City": "曼城", "Man City": "曼城",
    "Liverpool": "利物浦", "Chelsea": "切尔西", "Arsenal": "阿森纳",
    "Tottenham Hotspur": "热刺", "Tottenham": "热刺", "Spurs": "热刺",
    "Newcastle United": "纽卡斯尔", "Newcastle": "纽卡斯尔",
    "Aston Villa": "阿斯顿维拉", "West Ham United": "西汉姆", "West Ham": "西汉姆",
    "Brighton & Hove Albion": "布莱顿", "Brighton": "布莱顿",
    "Wolverhampton Wanderers": "狼队", "Wolverhampton": "狼队", "Wolves": "狼队",
    "Crystal Palace": "水晶宫", "Everton": "埃弗顿", "Fulham": "富勒姆",
    "AFC Bournemouth": "伯恩茅斯", "Bournemouth": "伯恩茅斯",
    "Nottingham Forest": "诺丁汉森林", "Brentford": "布伦特福德",
    "Ipswich Town": "伊普斯维奇", "Leeds United": "利兹联",
    "Coventry City": "考文垂", "Sunderland": "桑德兰",
    # 英冠
    "Hull City": "赫尔城", "Leicester City": "莱斯特城", "Leicester": "莱斯特城",
    "Southampton": "南安普顿",
    # 西甲
    "Real Madrid": "皇马", "Real Betis": "贝蒂斯", "Real Sociedad": "皇家社会",
    "Athletic Club": "毕尔巴鄂", "Athletic Bilbao": "毕尔巴鄂",
    "Atletico Madrid": "马竞", "FC Barcelona": "巴萨", "Barcelona": "巴塞罗那",
    "Villarreal CF": "比利亚雷亚尔", "Villarreal": "比利亚雷亚尔",
    "Sevilla FC": "塞维利亚", "Sevilla": "塞维利亚",
    "Valencia CF": "瓦伦西亚", "Valencia": "瓦伦西亚",
    "Celta Vigo": "塞尔塔", "Girona FC": "赫罗纳", "Girona": "赫罗纳",
    "CA Osasuna": "奥萨苏纳", "Osasuna": "奥萨苏纳",
    "RCD Mallorca": "马洛卡", "Mallorca": "马洛卡",
    "Getafe CF": "赫塔费", "Getafe": "赫塔费",
    "Rayo Vallecano": "巴列卡诺", "RCD Espanyol": "西班牙人",
    "Deportivo Alaves": "阿拉维斯", "Alaves": "阿拉维斯",
    "Las Palmas": "拉斯帕尔马斯", "Leganes": "莱加内斯",
    # 德甲
    "Bayern Munich": "拜仁", "FC Bayern München": "拜仁",
    "Borussia Dortmund": "多特蒙德", "Dortmund": "多特蒙德",
    "Bayer 04 Leverkusen": "勒沃库森", "Bayer Leverkusen": "勒沃库森", "Leverkusen": "勒沃库森",
    "RB Leipzig": "莱比锡", "Eintracht Frankfurt": "法兰克福",
    "VfL Wolfsburg": "沃尔夫斯堡", "Borussia Mönchengladbach": "门兴", "Gladbach": "门兴",
    "TSG Hoffenheim": "霍芬海姆", "Hoffenheim": "霍芬海姆",
    "1. FSV Mainz 05": "美因茨", "Mainz": "美因茨",
    "SC Freiburg": "弗赖堡", "Freiburg": "弗赖堡",
    "Union Berlin": "柏林联合", "SV Werder Bremen": "不莱梅", "Werder Bremen": "不莱梅",
    "VfB Stuttgart": "斯图加特", "Stuttgart": "斯图加特",
    "FC Augsburg": "奥格斯堡", "1. FC Heidenheim": "海登海姆", "Heidenheim": "海登海姆",
    "FC St. Pauli": "圣保利", "St. Pauli": "圣保利",
    "Holstein Kiel": "基尔", "Darmstadt 98": "达姆施塔特",
    # 意甲
    "AC Milan": "AC米兰", "Milan": "AC米兰",
    "Inter Milan": "国米", "FC Internazionale Milano": "国米", "Internazionale": "国米",
    "Juventus": "尤文", "SSC Napoli": "那不勒斯", "Napoli": "那不勒斯",
    "AS Roma": "罗马", "Lazio": "拉齐奥", "SS Lazio": "拉齐奥",
    "Atalanta BC": "亚特兰大", "Atalanta": "亚特兰大",
    "ACF Fiorentina": "佛罗伦萨", "Fiorentina": "佛罗伦萨",
    "Bologna FC 1909": "博洛尼亚", "Bologna": "博洛尼亚",
    "Torino FC": "都灵", "Torino": "都灵",
    "Udinese Calcio": "乌迪内斯", "Udinese": "乌迪内斯",
    "Cagliari Calcio": "卡利亚里", "Cagliari": "卡利亚里",
    "Genoa CFC": "热那亚", "Genoa": "热那亚",
    "US Lecce": "莱切", "Lecce": "莱切",
    "Hellas Verona": "维罗纳", "Verona": "维罗纳",
    "Como 1907": "科莫", "Como": "科莫",
    "Parma Calcio 1913": "帕尔马", "Parma": "帕尔马",
    "US Sassuolo Calcio": "萨索洛", "Sassuolo": "萨索洛",
    "Empoli FC": "恩波利", "Empoli": "恩波利",
    "Venezia FC": "威尼斯", "Monza": "蒙扎",
    # 法甲
    "Paris Saint-Germain": "巴黎圣日耳曼", "Paris SG": "巴黎圣日耳曼", "PSG": "巴黎圣日耳曼",
    "Olympique Marseille": "马赛", "Marseille": "马赛",
    "Olympique Lyonnais": "里昂", "Lyon": "里昂",
    "AS Monaco": "摩纳哥", "Monaco": "摩纳哥",
    "LOSC Lille": "里尔", "Lille": "里尔",
    "OGC Nice": "尼斯", "Nice": "尼斯",
    "Stade Rennais FC": "雷恩", "Rennes": "雷恩",
    "RC Strasbourg": "斯特拉斯堡", "Strasbourg": "斯特拉斯堡",
    "Stade Brestois 29": "布雷斯特", "Brest": "布雷斯特",
    "FC Lorient": "洛里昂", "Lorient": "洛里昂",
    "AJ Auxerre": "欧塞尔", "Auxerre": "欧塞尔",
    "Le Havre AC": "勒阿弗尔", "Le Havre": "勒阿弗尔",
    "Angers SCO": "昂热", "Angers": "昂热",
    "Toulouse FC": "图卢兹", "Toulouse": "图卢兹",
    "Stade de Reims": "兰斯", "Reims": "兰斯",
    "FC Nantes": "南特", "Nantes": "南特",
    "Montpellier HSC": "蒙彼利埃", "Montpellier": "蒙彼利埃",
    "Lens": "朗斯",
    # 欧冠/欧联 - 补充欧冠常见队名
    "Celtic FC": "凯尔特人", "Celtic": "凯尔特人",
    "Rangers FC": "流浪者", "Rangers": "流浪者",
    "FC Red Bull Salzburg": "萨尔茨堡", "Red Bull Salzburg": "萨尔茨堡", "Salzburg": "萨尔茨堡",
    "SK Sturm Graz": "格拉茨风暴", "Sturm Graz": "格拉茨风暴",
    "Club Brugge KV": "布鲁日", "Club Brugge": "布鲁日",
    "RSC Anderlecht": "安德莱赫特", "Anderlecht": "安德莱赫特",
    "KAA Gent": "根特", "KRC Genk": "亨克", "Genk": "亨克",
    "Royal Union SG": "圣吉罗斯", "Union SG": "圣吉罗斯",
    "FC Copenhagen": "哥本哈根", "Copenhagen": "哥本哈根",
    "FC Midtjylland": "米迪兰特", "Midtjylland": "米迪兰特",
    "Malmo FF": "马尔默", "Malmö FF": "马尔默",
    "Olympiacos FC": "奥林匹亚科斯", "Olympiacos": "奥林匹亚科斯",
    "Dinamo Zagreb": "萨格勒布迪纳摩",
    "Red Star Belgrade": "贝尔格莱德红星",
    "Ludogorets Razgrad": "卢多戈雷茨",
    "Sheriff Tiraspol": "谢里夫",
    "Ferencvaros TC": "费伦茨瓦罗斯", "Ferencvaros": "费伦茨瓦罗斯",
    "PAOK": "塞萨洛尼基PAOK", "Panathinaikos": "帕纳辛纳科斯",
    "Maccabi Tel-Aviv": "特拉维夫马卡比",
    "Young Boys": "伯尔尼年轻人", "FC Basel": "巴塞尔",
    "FCSB": "布加勒斯特星", "Slavia Prague": "布拉格斯拉维亚",
    "Viktoria Plzen": "比尔森胜利", "Slovan Bratislava": "布拉迪斯拉发",
    "Shakhtar Donetsk": "顿涅茨克矿工", "Dynamo Kyiv": "基辅迪纳摩",
    # 葡超
    "SL Benfica": "本菲卡", "Benfica": "本菲卡",
    "FC Porto": "波尔图", "Porto": "波尔图",
    "Sporting CP": "葡萄牙体育", "Sporting": "葡萄牙体育",
    "SC Braga": "布拉加", "Braga": "布拉加",
    "Vitoria SC": "吉马良斯", "Vitoria de Guimaraes": "吉马良斯",
    "Moreirense FC": "莫雷伦斯", "Arouca": "阿罗卡",
    "Casa Pia": "卡萨皮亚", "Estoril": "埃斯托里尔",
    "FC Famalicao": "法马利康", "Santa Clara": "圣克拉拉",
    "Nacional": "国民队", "Rio Ave": "里奥阿维",
    # 荷甲
    "AFC Ajax": "阿贾克斯", "Ajax": "阿贾克斯",
    "PSV Eindhoven": "埃因霍温", "PSV": "埃因霍温",
    "Feyenoord Rotterdam": "费耶诺德", "Feyenoord": "费耶诺德",
    "AZ Alkmaar": "阿尔克马尔", "AZ": "阿尔克马尔",
    "FC Twente": "特温特", "Twente": "特温特",
    "FC Utrecht": "乌得勒支", "Utrecht": "乌得勒支",
    "Sparta Rotterdam": "鹿特丹斯巴达",
    "Go Ahead Eagles": "前进之鹰", "NEC Nijmegen": "奈梅亨", "NEC": "奈梅亨",
    "SC Heerenveen": "海伦芬", "Fortuna Sittard": "福图纳锡塔德",
    "PEC Zwolle": "兹沃勒", "Willem II": "威廉二世",
    "FC Groningen": "格罗宁根",
    # 比甲
    "Royal Antwerp": "安特卫普", "Antwerp": "安特卫普",
    "Standard Liege": "标准列日", "Kortrijk": "科特赖克",
    "KV Mechelen": "梅赫伦", "Mechelen": "梅赫伦",
    "Charleroi": "沙勒罗瓦",
    # 土超
    "Galatasaray SK": "加拉塔萨雷", "Galatasaray": "加拉塔萨雷",
    "Fenerbahce SK": "费内巴切", "Fenerbahce": "费内巴切",
    "Besiktas JK": "贝西克塔斯", "Besiktas": "贝西克塔斯",
    "Trabzonspor": "特拉布宗体育",
    "Istanbul Basaksehir": "伊斯坦布尔巴萨克赛尔",
    "Antalyaspor": "安塔利亚体育", "Alanyaspor": "阿兰亚体育",
    "Konyaspor": "科尼亚体育", "Sivasspor": "锡瓦斯体育",
    "Kayserispor": "开塞利体育", "Rizespor": "里泽体育",
    # 中超
    "Shanghai Port FC": "上海海港", "Shanghai Port": "上海海港", "Shanghai SIPG FC": "上海海港",
    "Shanghai Shenhua": "上海申花", "Shandong Taishan": "山东泰山", "Shandong Luneng Taishan FC": "山东泰山",
    "Beijing Guoan": "北京国安", "Beijing FC": "北京国安",
    "Wuhan Three Towns": "武汉三镇",
    "Zhejiang Professional FC": "浙江", "Zhejiang FC": "浙江", "Zhejiang": "浙江",
    "Chengdu Rongcheng": "成都蓉城",
    "Tianjin Jinmen Tiger": "天津津门虎", "Henan": "河南",
    "Yunnan Yukun": "云南玉昆",
    "Qingdao Hainiu": "青岛海牛", "Qingdao West Coast": "青岛西海岸",
    "Shenzhen Xinpengcheng": "深圳新鹏城", "Shenzhen Peng City FC": "深圳新鹏城",
    "Chongqing Tonglianglong": "重庆铜梁龙",
    "Dalian Yingbo": "大连英博",
    "Liaoning Tieren": "辽宁铁人",
    # 日职
    "Urawa Red Diamonds": "浦和红钻", "Urawa Reds": "浦和红钻",
    "Kawasaki Frontale": "川崎前锋",
    "Yokohama F. Marinos": "横滨水手", "Yokohama F Marinos": "横滨水手",
    "Cerezo Osaka": "大阪樱花", "FC Tokyo": "FC东京",
    "Kashima Antlers": "鹿岛鹿角", "Vissel Kobe": "神户胜利船",
    "Gamba Osaka": "大阪钢巴", "Nagoya Grampus": "名古屋鲸八",
    "Sanfrecce Hiroshima": "广岛三箭", "Avispa Fukuoka": "福冈黄蜂",
    "Kashiwa Reysol": "柏太阳神",
    "Kyoto Sanga": "京都不死鸟", "Machida Zelvia": "町田泽维亚",
    "Shimizu S-Pulse": "清水鼓动", "Tokyo Verdy": "东京绿茵",
    # 韩K
    "Jeonbuk Hyundai Motors": "全北现代", "Jeonbuk": "全北现代",
    "Ulsan HD FC": "蔚山现代", "Ulsan": "蔚山现代",
    "Pohang Steelers": "浦项制铁", "FC Seoul": "FC首尔",
    "Incheon United": "仁川联", "Daegu FC": "大邱",
    # 美职联
    "Inter Miami CF": "迈阿密国际", "Inter Miami": "迈阿密国际",
    "LAFC": "洛杉矶FC", "Los Angeles FC": "洛杉矶FC",
    "LA Galaxy": "洛杉矶银河", "Los Angeles Galaxy": "洛杉矶银河",
    "Atlanta United": "亚特兰大联", "Atlanta United FC": "亚特兰大联",
    "Seattle Sounders FC": "西雅图海湾人", "Portland Timbers": "波特兰伐木工",
    "New York City FC": "纽约城", "NYCFC": "纽约城",
    "New York Red Bulls": "纽约红牛",
    "CF Montreal": "蒙特利尔", "CF Montréal": "蒙特利尔", "Toronto FC": "多伦多FC",
    "Chicago Fire FC": "芝加哥火焰", "Chicago Fire": "芝加哥火焰",
    "Vancouver Whitecaps FC": "温哥华白帽", "Vancouver Whitecaps": "温哥华白帽",
    "St. Louis City SC": "圣路易斯城", "St Louis City SC": "圣路易斯城",
    "Sporting Kansas City": "堪萨斯城竞技", "Sporting KC": "堪萨斯城竞技",
    "Nashville SC": "纳什维尔", "Houston Dynamo FC": "休斯顿迪纳摩",
    "Minnesota United FC": "明尼苏达联", "Austin FC": "奥斯汀",
    "Colorado Rapids": "科罗拉多急流", "San Jose Earthquakes": "圣何塞地震",
    "FC Cincinnati": "辛辛那提", "Columbus Crew": "哥伦布机员",
    "Charlotte FC": "夏洛特", "DC United": "华盛顿联",
    "Orlando City SC": "奥兰多城", "Philadelphia Union": "费城联合",
    "Real Salt Lake": "皇家盐湖城", "FC Dallas": "达拉斯",
    # 墨超
    "Club America": "美洲", "CF Monterrey": "蒙特雷", "Monterrey": "蒙特雷",
    "Cruz Azul": "蓝十字", "Tigres UANL": "新莱昂自治大学老虎", "Tigres": "新莱昂自治大学老虎",
    "Deportivo Toluca": "托卢卡", "Toluca": "托卢卡",
    "Chivas Guadalajara": "瓜达拉哈拉", "Guadalajara": "瓜达拉哈拉",
    "Club Leon": "莱昂", "Leon": "莱昂",
    "Puebla FC": "普埃布拉", "Puebla": "普埃布拉",
    "FC Juarez": "华雷斯", "Juarez": "华雷斯",
    "Necaxa": "内卡萨", "Atlas FC": "阿特拉斯", "Atlas": "阿特拉斯",
    "Mazatlan FC": "马萨特兰", "Mazatlan": "马萨特兰",
    "Santos Laguna": "桑托斯拉古纳",
    "Tijuana": "蒂华纳", "Queretaro": "克雷塔罗",
    "Pachuca": "帕丘卡", "UNAM Pumas": "墨西哥国立自治大学",
    "Atletico San Luis": "圣路易斯竞技", "San Luis": "圣路易斯竞技",
    "Leones Negros": "莱昂内格罗斯",
    # 韩K
    "Jeonbuk Hyundai Motors": "全北现代", "Jeonbuk": "全北现代",
    "Ulsan HD FC": "蔚山现代", "Ulsan": "蔚山现代", "Ulsan Hyundai FC": "蔚山现代",
    "Pohang Steelers": "浦项制铁", "FC Seoul": "FC首尔",
    "Incheon United": "仁川联", "Daegu FC": "大邱",
    "Daejeon Citizen": "大田市民", "Daejeon Hana Citizen": "大田市民",
    "Gangwon FC": "江原", "Sangju Sangmu FC": "尚州尚武",
    "Jeju United FC": "济州联", "Jeju United": "济州联",
    "Gwangju FC": "光州", "Suwon FC": "水原",
    "Seongnam FC": "城南", "Busan IPark": "釜山IPark",
    # 芬超
    "HJK Helsinki": "赫尔辛基", "HJK": "赫尔辛基",
    "KuPS": "库奥皮奥", "Inter Turku": "国际图尔库",
    "FC Lahti": "拉赫蒂", "IFK Mariehamn": "玛丽港",
    "FC Haka": "哈卡", "AC Oulu": "奥卢", "Oulu": "奥卢",
    "VPS": "瓦萨", "VPS Vaasa": "瓦萨", "Vaasa": "瓦萨",
    "SJK": "塞伊奈约基", "SJK Seinäjoki": "塞伊奈约基",
    "IF Gnistan": "格尼斯坦", "Gnistan": "格尼斯坦",
    "KuPS Kuopio": "库奥皮奥", "Ilves": "伊尔韦斯",
    "FC Honka": "洪卡", "HIFK": "赫尔辛基IFK",
    # 瑞典超
    "IF Elfsborg": "埃尔夫斯堡", "Elfsborg": "埃尔夫斯堡",
    "Djurgardens IF": "尤尔加丹", "AIK Solna": "AIK索尔纳", "AIK": "AIK索尔纳",
    "IFK Goteborg": "哥德堡", "IFK Norrkoping": "诺尔雪平",
    "Hammarby IF": "哈马比", "Hammarby": "哈马比",
    "Kalmar FF": "卡尔马", "Mjallby AIF": "米亚尔比", "Mjällby AIF": "米亚尔比",
    "IF Brommapojkarna": "布鲁马波卡纳", "Halmstads BK": "哈尔姆斯塔德",
    "Hacken": "赫根", "BK Hacken": "赫根",
    "Degerfors": "代格福什", "Degerfors IF": "代格福什", "GAIS": "盖斯",
    "IK Sirius": "西里乌斯", "Sirius": "西里乌斯",
    "Vasteras SK": "韦斯特罗斯", "Västerås SK": "韦斯特罗斯",
    "Mjallby": "米亚尔比",
    # 挪超
    "Molde FK": "莫尔德", "Molde": "莫尔德",
    "Rosenborg BK": "罗森博格", "Rosenborg": "罗森博格",
    "Viking FK": "维京", "Viking": "维京",
    "Fredrikstad FK": "弗雷德里克斯塔", "Fredrikstad": "弗雷德里克斯塔",
    "FK Haugesund": "海于格松", "Haugesund": "海于格松",
    "Stromsgodset": "斯托姆加斯特", "Sarpsborg 08": "萨尔普斯堡",
    "Sarpsborg FK": "萨尔普斯堡",
    "Sandefjord": "桑德菲杰", "Tromso IL": "特罗姆瑟", "Tromso": "特罗姆瑟",
    "SK Brann": "布兰", "Bodo/Glimt": "博德闪耀", "Bodø/Glimt": "博德闪耀",
    "Lillestrom": "利勒斯特罗姆", "Valerenga": "瓦勒伦加",
    "Kristiansund BK": "克里斯蒂安松", "KFUM Oslo": "奥斯陆KFUM", "KFUM": "奥斯陆KFUM",
    "IK Start": "斯达特", "Start": "斯达特",
    "HamKam": "汉坎", "Hamarkameratene": "汉坎",
    "Odds BK": "奥德",
    # 苏超
    "Hearts": "哈茨", "Heart of Midlothian": "哈茨",
    "Hibernian": "希伯尼安", "Aberdeen": "阿伯丁",
    "Motherwell": "马瑟韦尔", "Kilmarnock": "基尔马诺克",
    "Ross County": "罗斯郡", "Livingston": "利文斯顿",
    # 解放者杯/南美杯 常见队
    "Penarol": "佩纳罗尔", "Nacional Montevideo": "蒙得维的亚国民",
    "Atletico Nacional": "国民竞技", "Deportivo Cali": "卡利体育",
    "Millonarios": "百万富翁", "LDU Quito": "基多体育",
    "Fluminense": "弗鲁米嫩塞", "Palmeiras": "帕尔梅拉斯",
    "Atletico Paranaense": "巴拉那竞技",
    # 沙特联
    "Al Hilal": "利雅得新月", "Al-Hilal": "利雅得新月",
    "Al Nassr": "利雅得胜利", "Al-Nassr": "利雅得胜利",
    "Al Ittihad": "吉达联合", "Al-Ittihad": "吉达联合",
    "Al Ahli": "吉达国民", "Al-Ahli": "吉达国民",
    "Al Ain FC": "艾因", "Al Ain": "艾因",
    "Al Sadd SC": "萨德", "Al Duhail SC": "杜海勒",
    # 国家队
    "Algeria": "阿尔及利亚", "Argentina": "阿根廷", "Austria": "奥地利",
    "Belgium": "比利时", "Brazil": "巴西", "Canada": "加拿大",
    "Colombia": "哥伦比亚", "Croatia": "克罗地亚", "Czechia": "捷克",
    "Denmark": "丹麦", "Ecuador": "厄瓜多尔", "Egypt": "埃及",
    "England": "英格兰", "France": "法国", "Germany": "德国",
    "Ghana": "加纳", "Ivory Coast": "科特迪瓦", "Mexico": "墨西哥",
    "Morocco": "摩洛哥", "Netherlands": "荷兰", "Nigeria": "尼日利亚",
    "Norway": "挪威", "Paraguay": "巴拉圭", "Portugal": "葡萄牙",
    "Scotland": "苏格兰", "Senegal": "塞内加尔", "Spain": "西班牙",
    "Sweden": "瑞典", "Switzerland": "瑞士", "Tunisia": "突尼斯",
    "Turkey": "土耳其", "United States": "美国", "USA": "美国",
    "Uruguay": "乌拉圭", "Japan": "日本", "South Korea": "韩国",
    "China PR": "中国", "China": "中国", "Australia": "澳大利亚",
    "Saudi Arabia": "沙特", "Iran": "伊朗", "Iraq": "伊拉克",
    "Qatar": "卡塔尔", "Uzbekistan": "乌兹别克斯坦",
    "Bosnia-Herzegovina": "波黑", "New Zealand": "新西兰",
    "Republic of Ireland": "爱尔兰", "Ireland": "爱尔兰",
    "Wales": "威尔士", "Poland": "波兰", "Ukraine": "乌克兰",
    "Serbia": "塞尔维亚", "Romania": "罗马尼亚", "Hungary": "匈牙利",
    "Greece": "希腊", "Russia": "俄罗斯", "Finland": "芬兰",
    "Iceland": "冰岛", "North Macedonia": "北马其顿",
    "Montenegro": "黑山", "Slovenia": "斯洛文尼亚",
    "Slovakia": "斯洛伐克", "Czech Republic": "捷克",
    "Israel": "以色列", "Bulgaria": "保加利亚",
    "Georgia": "格鲁吉亚", "Albania": "阿尔巴尼亚",
    "Kosovo": "科索沃", "Armenia": "亚美尼亚",
    "Cyprus": "塞浦路斯", "Luxembourg": "卢森堡",
    "Kazakhstan": "哈萨克斯坦", "Azerbaijan": "阿塞拜疆",
    "Moldova": "摩尔多瓦", "Latvia": "拉脱维亚",
    "Lithuania": "立陶宛", "Estonia": "爱沙尼亚",
    "Faroe Islands": "法罗群岛", "Malta": "马耳他",
    "Andorra": "安道尔", "Gibraltar": "直布罗陀",
    "San Marino": "圣马力诺", "Liechtenstein": "列支敦士登",
    "Costa Rica": "哥斯达黎加", "Honduras": "洪都拉斯",
    "Jamaica": "牙买加", "Panama": "巴拿马",
    "Trinidad and Tobago": "特立尼达和多巴哥",
    "Guatemala": "危地马拉", "El Salvador": "萨尔瓦多",
    "Cuba": "古巴", "Haiti": "海地",
    "Dominican Republic": "多米尼加",
    "South Africa": "南非", "Cameroon": "喀麦隆",
    "Mali": "马里", "Congo DR": "刚果民主共和国",
    "Guinea": "几内亚", "Zambia": "赞比亚",
    "Chile": "智利", "Peru": "秘鲁", "Venezuela": "委内瑞拉",
    "Bolivia": "玻利维亚", "Paraguay": "巴拉圭",
    "Colombia": "哥伦比亚", "Ecuador": "厄瓜多尔",
}

# ─── Git 配置 ───
GIT_USER_EMAIL = "ceshi@ruochanit.com"
GIT_USER_NAME = "ceshi1986"
GIT_REPO = "ceshi1986/football-predictions"
GIT_TOKEN = os.environ.get("GITHUB_TOKEN", "YOUR_TOKEN_HERE")
REPO_DIR = "/tmp/football-predictions"


def get_cn_name(en_name: str) -> str:
    """英文名→中文名，精确匹配后尝试去除常见后缀匹配，并处理重音/变体"""
    if not en_name:
        return en_name
    # 去除重音符号，统一比较（如 Atlético → Atletico）
    import unicodedata
    normalized = unicodedata.normalize('NFKD', en_name)
    normalized = ''.join(c for c in normalized if not unicodedata.combining(c))
    # 替换常见变体
    normalized = normalized.replace('-', ' ').replace("'", '').replace("'", '')
    # 精确匹配原始名
    if en_name in TEAM_EN_CN:
        return TEAM_EN_CN[en_name]
    # 精确匹配去重音后的名
    if normalized in TEAM_EN_CN:
        return TEAM_EN_CN[normalized]
    # 去除 FC, CF, SC 等后缀再匹配
    for suffix in [" FC", " CF", " SC", " AC", " BK", " IF", " FK", " SK", " FF", " SK", " BC"]:
        stripped = en_name.replace(suffix, "")
        if stripped in TEAM_EN_CN:
            return TEAM_EN_CN[stripped]
        # 也试去重音后的
        stripped_n = unicodedata.normalize('NFKD', stripped)
        stripped_n = ''.join(c for c in stripped_n if not unicodedata.combining(c))
        stripped_n = stripped_n.replace('-', ' ').replace("'", '').replace("'", '')
        if stripped_n in TEAM_EN_CN:
            return TEAM_EN_CN[stripped_n]
    # 取名字的最后部分再匹配（如 "VPS Vaasa" → "Vaasa", "St. Louis City SC" → "Louis City"）
    parts = normalized.split()
    if len(parts) > 1:
        # 取最后2-3个词尝试匹配
        for n in range(min(3, len(parts)), 0, -1):
            sub = ' '.join(parts[-n:])
            if sub in TEAM_EN_CN:
                return TEAM_EN_CN[sub]
    return en_name


def estimate_draw_odds(home_win: float, away_win: float) -> float:
    """
    当 h2h 市场只有 2 个赔率(主胜/客胜)时，估算平局赔率。
    使用公平赔率转换: 1/p = 1/home + 1/away + 1/draw
    假设 margin ≈ 5%，先还原真实概率再计算。
    """
    if home_win <= 1.01 or away_win <= 1.01:
        return 3.3
    # 隐含概率
    ph = 1.0 / home_win
    pa = 1.0 / away_win
    margin = ph + pa  # >1 部分为庄家利润和平局概率
    if margin >= 0.95:
        # margin 太高，说明可能本身就没有平局市场
        pd = max(0.15, 1.0 - ph - pa + 0.05)
    else:
        pd = 1.0 - ph - pa
        if pd < 0.10:
            pd = 0.15
    draw_odds = round(1.0 / pd, 2)
    return max(2.0, min(draw_odds, 15.0))


def extract_odds_from_match(match_data: dict) -> Optional[dict]:
    """
    从 The Odds API 单场比赛数据中提取平均赔率。
    返回 {"w": 主胜, "d": 平局, "l": 客胜} 或 None
    """
    bookmakers = match_data.get("bookmakers", [])
    if not bookmakers:
        return None

    home_prices = []
    draw_prices = []
    away_prices = []
    home_team = match_data.get("home_team", "")
    away_team = match_data.get("away_team", "")

    for bk in bookmakers:
        for market in bk.get("markets", []):
            if market.get("key") != "h2h":
                continue
            outcomes = market.get("outcomes", [])
            for o in outcomes:
                name = o.get("name", "")
                price = o.get("price", 0)
                if price <= 1.0:
                    continue
                if name == home_team or name == "Home":
                    home_prices.append(price)
                elif name == away_team or name == "Away":
                    away_prices.append(price)
                elif name == "Draw":
                    draw_prices.append(price)

    if not home_prices or not away_prices:
        return None

    # 取所有 bookmaker 赔率的平均值
    avg_home = round(sum(home_prices) / len(home_prices), 2)
    avg_away = round(sum(away_prices) / len(away_prices), 2)

    if draw_prices:
        avg_draw = round(sum(draw_prices) / len(draw_prices), 2)
    else:
        avg_draw = estimate_draw_odds(avg_home, avg_away)

    return {"w": avg_home, "d": avg_draw, "l": avg_away}


def fetch_odds_for_sport(sport_key: str, api_key: str) -> list:
    """获取单个联赛的赔率数据"""
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey": api_key,
        "regions": "eu",
        "markets": "h2h",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            print(f"  [限流] {sport_key} 请求被限流，跳过")
            return []
        if resp.status_code != 200:
            print(f"  [错误] {sport_key} HTTP {resp.status_code}")
            return []
        # 检查剩余配额
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        print(f"  [配额] {sport_key}: 剩余={remaining}, 已用={used}")
        return resp.json()
    except Exception as e:
        print(f"  [异常] {sport_key}: {e}")
        return []


def clone_and_push(json_data: dict, filename: str) -> bool:
    """克隆仓库，保存文件，推送到 GitHub"""
    try:
        # 清理旧目录
        subprocess.run(["rm", "-rf", REPO_DIR], timeout=10)
        # 克隆
        clone_url = f"https://{GIT_TOKEN}@github.com/{GIT_REPO}.git"
        result = subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, REPO_DIR],
            timeout=60, capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"[克隆失败] {result.stderr}")
            return False
        print("[克隆成功]")

        # 配置 git
        subprocess.run(["git", "config", "user.email", GIT_USER_EMAIL],
                        cwd=REPO_DIR, timeout=5, capture_output=True)
        subprocess.run(["git", "config", "user.name", GIT_USER_NAME],
                        cwd=REPO_DIR, timeout=5, capture_output=True)

        # 确保 data 目录存在
        data_dir = os.path.join(REPO_DIR, "data")
        os.makedirs(data_dir, exist_ok=True)

        # 保存 JSON 文件
        filepath = os.path.join(data_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        print(f"[保存] {filepath}")

        # 推送
        subprocess.run(["git", "add", f"data/{filename}"],
                        cwd=REPO_DIR, timeout=10, capture_output=True)
        result = subprocess.run(
            ["git", "commit", "-m", f"Update {filename} - {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')}"],
            cwd=REPO_DIR, timeout=10, capture_output=True, text=True,
        )
        if "nothing to commit" in result.stdout:
            print("[无变更] 数据未变化，跳过推送")
            return True
        result = subprocess.run(
            ["git", "push"],
            cwd=REPO_DIR, timeout=30, capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"[推送失败] {result.stderr}")
            return False
        print("[推送成功]")
        return True
    except Exception as e:
        print(f"[Git异常] {e}")
        return False


async def main():
    result_mode = sys.argv[1] if len(sys.argv) > 1 else "display_only"
    api_key = sys.argv[2] if len(sys.argv) > 2 else "0b8808a6d42b077c4f4016737004f22b"

    print(f"[参数] result_mode={result_mode}, api_key={api_key[:8]}...")
    sdk = CodeActSDK()

    try:
        all_matches = []
        now = datetime.now(timezone(timedelta(hours=8)))
        cutoff = now + timedelta(hours=48)

        # 遍历所有联赛
        for sport_key, (league_code, league_short) in SPORT_LEAGUE_MAP.items():
            print(f"[获取] {sport_key} ({league_short})...")
            raw_matches = fetch_odds_for_sport(sport_key, api_key)
            if not raw_matches:
                continue

            count = 0
            for m in raw_matches:
                # 解析比赛时间
                commence = m.get("commence_time", "")
                try:
                    match_time = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                    match_time_cst = match_time.astimezone(timezone(timedelta(hours=8)))
                except Exception:
                    continue

                # 只保留48小时内的比赛
                if match_time_cst > cutoff or match_time_cst < now - timedelta(hours=3):
                    continue

                # 提取赔率
                odds = extract_odds_from_match(m)
                if not odds:
                    continue

                home_en = m.get("home_team", "")
                away_en = m.get("away_team", "")
                home_cn = get_cn_name(home_en)
                away_cn = get_cn_name(away_en)

                match_entry = {
                    "home": home_cn,
                    "away": away_cn,
                    "homeEN": home_en,
                    "awayEN": away_en,
                    "date": match_time_cst.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                    "league": league_code,
                    "leagueShort": league_short,
                    "odds": odds,
                }
                all_matches.append(match_entry)
                count += 1

            print(f"  → {sport_key}: {count} 场有效比赛")

        # 按时间排序
        all_matches.sort(key=lambda x: x["date"])

        # 构建输出 JSON
        output = {
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "source": "the-odds-api",
            "total_matches": len(all_matches),
            "matches": all_matches,
        }

        print(f"\n[汇总] 共 {len(all_matches)} 场比赛有赔率数据")

        # 保存到本地
        local_output_dir = "./codeact/output"
        os.makedirs(local_output_dir, exist_ok=True)
        local_path = os.path.join(local_output_dir, "odds_api_odds.json")
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"[本地保存] {local_path}")

        # 推送到 GitHub
        push_ok = clone_and_push(output, "odds_api_odds.json")

        # 提交结果
        actual_mode = result_mode if result_mode != "auto" else "display_only"
        league_summary = {}
        for m in all_matches:
            ls = m["leagueShort"]
            league_summary[ls] = league_summary.get(ls, 0) + 1
        summary_parts = [f"{k}({v}场)" for k, v in sorted(league_summary.items(), key=lambda x: -x[1])]
        summary_str = "、".join(summary_parts[:8]) if summary_parts else "无"

        message = (
            f"The Odds API 赔率数据获取完成：共 {len(all_matches)} 场比赛\n"
            f"联赛分布：{summary_str}\n"
            f"GitHub推送：{'成功' if push_ok else '失败'}"
        )

        await sdk.submit_result(
            result_mode=actual_mode,
            status="success",
            message=message,
            data={
                "total_matches": len(all_matches),
                "push_success": push_ok,
                "leagues": league_summary,
            },
        )

    except Exception as e:
        print(f"[异常] {e}")
        import traceback
        traceback.print_exc()
        await sdk.submit_result(
            result_mode="notify",
            status="error",
            message=f"赔率数据获取失败: {e}",
            data={"error_type": type(e).__name__},
        )


asyncio.run(main())
