import asyncio,json,os,sys,re
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
SD=os.path.dirname(os.path.abspath(__file__))
DD=os.path.join(SD,"data","500com_daily")
HD={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139.0.0.0 Safari/537.36","Accept-Language":"zh-CN,zh;q=0.9"}
BA=['--disable-blink-features=AutomationControlled','--no-sandbox']
AD="Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
TC={"365":"bet365","weide":"weide","libo":"libo","william":"william_hill"}
def parse(html,fid):
    soup=BeautifulSoup(html,'html.parser');co={}
    for row in soup.select('tr[class*="odd"], tr'):
        c=row.find_all('td')
        if len(c)<5:continue
        nm=c[0].get_text(strip=True).lower();m=None
        for k,v in TC.items():
            if k in nm:m=v;break
        if not m:continue
        try:
            od=[float(c[i].get_text(strip=True))for i in range(1,4)]
            kl=[float(c[i].get_text(strip=True))for i in range(4,7)]if len(c)>6 else[.9]*3
            pt=c[7].get_text(strip=True)if len(c)>7 else"92"
            pv=float(pt.replace('%',''))/100 if'%'in pt else float(pt)/100 if float(pt)>1 else float(pt)
            co[m]={"latest_odds":od,"kelly":kl,"payout":round(pv,4),"initial_odds":od}
        except:pass
    return co
async def scrape(fid,br):
    try:
        ctx=await br.new_context(user_agent=HD["User-Agent"])
        pg=await ctx.new_page();await pg.add_init_script(AD)
        await pg.goto(f"https://odds.500.com/fenxi/ouzhi-{fid}.shtml",wait_until="domcontentloaded",timeout=20000)
        await asyncio.sleep(1.5);h=await pg.content();await ctx.close()
        if"Access Restricted"in h or len(h)<1000:return None
        return parse(h,fid)
    except:return None
def get_matches():
    import urllib.request,ssl
    cx=ssl.create_default_context();cx.check_hostname=False;cx.verify_mode=ssl.CERT_NONE
    rq=urllib.request.Request("https://trade.500.com/jczq/",headers=HD)
    h=urllib.request.urlopen(rq,timeout=15,context=cx).read().decode('utf-8','ignore')
    ids=re.findall(r'ouzhi-(\d+)',h);nms=re.findall(r'title="([^"]+)"',h)
    return{fid:{"match_name":nms[i]if i<len(nms)else"","fixture_id":fid}for i,fid in enumerate(ids)}
async def main():
    print(f"=== 500com {datetime.now().strftime('%H:%M:%S')} ===")
    ms=get_matches();print(f"{len(ms)} matches")
    async with async_playwright()as p:
        br=await p.chromium.launch(headless=True,args=BA)
        res={};sem=asyncio.Semaphore(5)
        async def w(f):
            async with sem:d=await scrape(f,br)
            if d:res[f]=d;print(f"OK {f}")
            else:print(f"-- {f}")
        await asyncio.gather(*[w(f)for f in ms]);await br.close()
    if not res:print("NO DATA");sys.exit(1)
    td=datetime.now().strftime('%Y%m%d');od=os.path.join(DD,td);os.makedirs(od,exist_ok=True)
    out={"source":"500.com","scrape_time":datetime.now().isoformat(),"matches":{fid:{"match_name":ms[fid]["match_name"],"fixture_id":fid,"companies":d}for fid,d in res.items()}}
    fp=os.path.join(od,"zgzcw_kelly_data.json")
    with open(fp,'w',encoding='utf-8')as f:json.dump(out,f,ensure_ascii=False,indent=2)
    print(f"Saved {len(res)} to {fp}")
if __name__=='__main__':asyncio.run(main())
