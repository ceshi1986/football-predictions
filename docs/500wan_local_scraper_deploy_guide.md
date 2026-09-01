# 500万数据本地抓取链路 · 部署与维护手册

> 建立日期：2026-09-02
> 状态：已验证上线（竞彩+北单105场，稳定抓取60-70场/轮，自动上传GitHub）
> 脚本本体：`fp-repo/codeact/scripts/scraper_v6.py`（Windows端文件名 `scrape_500com.py`，内容相同）

---

## 一、为什么需要这套链路

500万（odds.500.com）启用了 EdgeOne WAF：
- **封机房IP段**：云端服务器（含Coze云电脑、云手机）的IP一律被拦截，headless浏览器拿到的只有7399字符的拦截页
- **检测headless指纹**：即使用真实cookie，headless=True 仍被拦截
- **不封频率**：住宅IP + 真实Chrome + 验证cookie下，每30分钟抓一轮、并发3、随机延时1-3秒，长期稳定

**结论：500万数据只能从主人的住宅宽带Windows电脑抓。** 云端定时任务（kelly_update.py）改为从GitHub读取Windows上传的数据。

## 二、链路架构

```
Windows电脑(DESKTOP-H4LFT0G)
  计划任务「500comKellyScraper」每30分钟
    → run_hidden.bat → python scrape_500com.py --hidden
    → 真实Chrome(持久profile, 窗口移出屏幕)
    → 抓竞彩+北单列表(trade.500.com/jczq|bjdc)
    → 每场抓两页：欧赔ouzhi-{fid}.shtml + 亚盘yazhi-{fid}.shtml
    → 解析：欧赔四家(365/韦德/立博/威廉)实时赔率/凯利/赔付率 + 澳门亚盘盘口水位
    → 本地存 data\500com_daily\{日期}\zgzcw_kelly_data.json + 快照
    → GitHub Contents API 直传 win500_data.json + win500_{时分秒}.json
                                                    ↓
云端 kelly_update.py（每30分钟Calendar日程）
  → 先拉GitHub win500_data.json，scrape_time≤30分钟且≥5场 → 直接用（500.com_local）
  → 不新鲜/拉取失败 → 回退zgzcw中国足彩网浏览器抓取
  → 锁定(赛前60分) / 回测写入 / 蛙跳检测(用win500澳门盘口快照) / 推送GitHub
```

## 三、Windows端部署清单（换机重建照此做）

1. **Python 3.12**：`C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe`
2. **依赖**：`pip install playwright aiohttp beautifulsoup4 requests -i https://mirrors.aliyun.com/pypi/simple/`，然后 `playwright install chromium`
3. **目录**：`C:\Users\Administrator\football-scraper\`
   - `scrape_500com.py`（主脚本，从fp-repo/codeact/scripts/scraper_v6.py复制）
   - `run_hidden.bat`（计划任务入口，输出追加到scrape.log）
   - `chrome_profile\`（Chrome持久化目录，**含验证cookie，勿删**）
   - `data\500com_daily\{YYYYMMDD}\`（数据输出）
   - `scrape.log`（运行日志）
4. **脚本下发通道**（国内网络GitHub直连不稳）：
   - 云端对 scraper_v6.py 调 `file_to_url` 生成 coze.cn 短链
   - Windows PowerShell：`(New-Object Net.WebClient).DownloadFile("<短链>", "$env:USERPROFILE\football-scraper\scrape_500com.py")`
5. **人机验证（2026-09-02起全自动）**：
   - "确认您是真人"是**腾讯防水墙**（验证码iframe来自 captcha.eo.gtimg.com），复选框=iframe内 `DIV#verifyCheckbox`
   - 脚本 `_pass_captcha()`：检测到约1.6万字符验证页 → 进iframe → 真人鼠标随机轨迹 → 点复选框；窗口移屏外亦可一次放行，点完直接进数据页、无滑块
   - 启动验证阶段 + 抓取中撞到验证页都会自动点；Chrome参数带 `--disable-backgrounding-occluded-windows --disable-renderer-backgrounding` 防离屏渲染被后台化
   - 仅当出现**滑块**（极罕见）时退出码2，需不带 --hidden 手动跑一次点验证；cookie存入chrome_profile
6. **计划任务**（PowerShell管理员）：
   - 任务名 `500comKellyScraper`
   - **Principal必须是 Interactive 登录类型**（后台Session 0跑Chrome会被WAF拦，退出码2）
   - 触发器：每30分钟重复；操作：run_hidden.bat；超时25分钟
   - --hidden 原理：`--window-position=-32000,-32000` 把窗口移出屏幕，指纹仍是真实Chrome

## 四、页面结构（解析依据，500万改版时排查用）

- **欧赔页** `ouzhi-{fid}.shtml`：主表 `table#datatb`，每家公司占9行块
  - 公司名行：td≥9个，td[1]含（国家）；识别：威→威廉、立→立博、伟→韦德、B开头+英国→bet365
  - 初赔 td[3,4,5]，即时赔率 td[6,7,8]；凯利=公司块第+8行前3格；赔付率=+6行第1格（百分数）
- **亚盘页** `yazhi-{fid}.shtml`：主表 `table#datatb`，每家公司3行（即时/变化/初盘）
  - **澳门按公司名识别**（位置不固定、有的场次没有）：名字含"门"(U+95E8)或"MACAUSLOT"
  - 即时行：td[2]=主水、td[3]=盘口、td[4]=客水、td[7-9]=初盘主水/盘口/客水
- **页面长度判据**：正常欧赔页>20万字符、亚盘页约9.6万；77字符=未开盘；1.6万=软拦截；<1万=WAF拦截
- 列表页编码：trade.500.com 为GBK（脚本已做utf-8/gbk兼容）

## 五、数据格式（win500_data.json）

```json
{"source":"500.com_local","scrape_time":"2026-09-02T01:42:17",
 "matches":{"<fid>":{
   "match_name":"...","fixture_id":"...",
   "companies":{"bet365":{"latest_odds":[主,平,客],"kelly":[主,平,客],"payout":0.91,"initial_odds":[...]},"weide":{...},"libo":{...},"william_hill":{...}},
   "macau_yapan":{"live":{"home_water":0.64,"handicap":0.0,"handicap_raw":"澳门平手","away_water":1.14},"initial":{...同结构或null}}
 }}}
```
- 盘口数值化：平手0、平/半0.25、半球0.5…受盘为负值
- GitHub路径：`data/500com_daily/{YYYYMMDD}/win500_data.json` + `snapshots/win500_{HHMMSS}.json`

## 六、日常维护与故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 计划任务LastTaskResult=2 | 自动点验证失败（出现滑块）或 非交互会话 | 先确认任务是Interactive模式；仍2则手动 `python scrape_500com.py`（不带--hidden）跑一次、点验证 |
| 大量"拦截/空页 len=77" | 比赛未开盘 | 正常，开售后自动有数据 |
| "拦截/空页 len=1.6万左右" | 软拦截/页面没加载完 | 偶发正常；成片出现检查cookie |
| 上传失败 SSL CERTIFICATE_VERIFY_FAILED | Windows缺证书链 | 脚本已对GitHub请求关闭证书校验，若复现检查_SSL上下文 |
| UnicodeEncodeError gbk | 控制台打印生僻字符 | 脚本已reconfigure stdout为utf-8 |
| Chrome启动失败/profile被锁 | 上次崩溃残留chrome进程 | 脚本启动时自动清理含football-scraper\chrome_profile的chrome进程 |
| 云端数据旧 | Windows关机/休眠/网络断 | 保证电脑不关机；kelly_update自动回退zgzcw兜底 |

- **cookie寿命**：约数天。过期时脚本退出码2，计划任务日志scrape.log可见提示；手动跑一次点验证即可
- **验证链路是否在跑**：查GitHub win500_data.json的scrape_time是否30分钟内；或Windows端 `Get-ScheduledTaskInfo -TaskName 500comKellyScraper` 看LastTaskResult（0=成功）
- 日志：`C:\Users\Administrator\football-scraper\scrape.log`

## 七、备份位置

- 脚本主副本：`fp-repo/codeact/scripts/scraper_v6.py`（云端，改Windows端先改这里再下发）
- 云端消费侧：`fp-repo/codeact/scripts/kelly_update.py`（v2.0 win500优先+zgzcw回退）
- 本手册：`fp-repo/docs/500万本地抓取链路_部署维护手册.md`
- Windows端：`C:\Users\Administrator\football-scraper\`（含chrome_profile，换机需重新人工验证）
