#!/usr/bin/env python3
"""每日网站自检脚本：检查5个网站的可访问性和关键功能，含足球预测网常犯错误自动检查"""

import json, sys, os, re
from datetime import datetime

# CodeAct SDK
from codeact import CodeAct

SCRIPT_NAME = "website_self_check"

# 竞彩/北单联赛白名单（唯一真相源，与 daily_predictions.py 和 index.html 保持一致）
ACTIVE_LEAGUE_CODES = {"bra.1", "nor.1", "swe.1", "mls", "usa.1", "uefa.champions", "uefa.champions.qual", "uefa.europa", "fifa.world"}

SITES = {
    "足球预测网": {
        "url": "https://ceshi1986.github.io/football-predictions/index.html",
        "checks": [
            ("schedule.json", "https://ceshi1986.github.io/football-predictions/schedule.json", "json_matches"),
            ("ai-predictions.json", "https://ceshi1986.github.io/football-predictions/data/ai-predictions.json", "json"),
            ("odds_api_odds.json", "https://ceshi1986.github.io/football-predictions/data/odds_api_odds.json", "json"),
        ],
        "min_schedule_matches": 1,
        "key_js": ["_fetchRealOdds", "_calc", "fpUpdateLockState", "_matchRealOdds"],
    },
    "玄学直播网": {
        "url": "https://ceshi1986.github.io/metaphysics-live/index.html",
        "checks": [],
        "key_js": [],
    },
    "直播助手": {
        "url": "https://ceshi1986.github.io/live-assistant/index.html",
        "checks": [],
        "key_js": [],
    },
    "AI策略网": {
        "url": "https://ceshi1986.github.io/stock-strategy/index.html",
        "checks": [
            ("portfolio.json", "https://ceshi1986.github.io/stock-strategy/portfolio.json", "json"),
        ],
        "key_js": [],
    },
    "学习转化网": {
        "url": "https://ceshi1986.github.io/xuexizhuanhua/index.html",
        "checks": [],
        "key_js": [],
    },
}


def check_url(url, timeout=15):
    """检查URL是否可访问，返回(status_code, size_bytes, error)"""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (SelfCheck/1.0)"})
        r = urllib.request.urlopen(req, timeout=timeout)
        body = r.read()
        return r.status, len(body), None
    except Exception as e:
        return 0, 0, str(e)


def check_json_data(url, timeout=15):
    """检查JSON数据是否有效，返回(data, error)"""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (SelfCheck/1.0)"})
        r = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(r.read().decode("utf-8"))
        return data, None
    except json.JSONDecodeError as e:
        return None, f"JSON解析失败: {e}"
    except Exception as e:
        return None, str(e)


def check_js_functions(url, functions, timeout=15):
    """检查HTML中是否包含关键JS函数定义"""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (SelfCheck/1.0)"})
        r = urllib.request.urlopen(req, timeout=timeout)
        content = r.read().decode("utf-8", errors="replace")
        missing = []
        for fn in functions:
            if f"function {fn}" not in content and f"{fn}(" not in content:
                missing.append(fn)
        return missing, None
    except Exception as e:
        return [], str(e)


def run_check():
    """执行全部检查，返回报告"""
    results = []
    issues = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    for site_name, config in SITES.items():
        site_result = {"name": site_name, "status": "ok", "details": []}

        # 1. 主页可访问性
        status, size, err = check_url(config["url"])
        if err:
            site_result["status"] = "error"
            site_result["details"].append(f"主页访问失败: {err}")
            issues.append(f"🔴 {site_name} 主页无法访问: {err}")
        elif status != 200:
            site_result["status"] = "warn"
            site_result["details"].append(f"主页HTTP {status}")
            issues.append(f"🟡 {site_name} 主页HTTP {status}")
        else:
            site_result["details"].append(f"主页正常 ({size} bytes)")

        # 2. 数据源检查
        for check_name, check_url, check_type in config.get("checks", []):
            if check_type == "json_matches":
                data, err = check_json_data(check_url)
                if err:
                    site_result["details"].append(f"{check_name}: {err}")
                    if "schedule" in check_name.lower():
                        issues.append(f"🔴 {site_name} {check_name}加载失败: {err}")
                else:
                    matches = data if isinstance(data, list) else data.get("matches", [])
                    count = len(matches) if isinstance(matches, list) else 0
                    site_result["details"].append(f"{check_name}: {count}条")
                    min_count = config.get("min_schedule_matches", 0)
                    if count < min_count:
                        issues.append(f" {site_name} {check_name}数据不足({count}<{min_count})")
            else:
                data, err = check_json_data(check_url)
                if err:
                    site_result["details"].append(f"{check_name}: {err}")
                    issues.append(f" {site_name} {check_name}: {err}")
                else:
                    count = len(data) if isinstance(data, list) else len(data.keys())
                    site_result["details"].append(f"{check_name}: {count}条")

        # 3. 关键JS函数检查
        key_js = config.get("key_js", [])
        if key_js:
            missing, err = check_js_functions(config["url"], key_js)
            if err:
                site_result["details"].append(f"JS检查失败: {err}")
            elif missing:
                site_result["status"] = "error" if site_result["status"] == "ok" else site_result["status"]
                site_result["details"].append(f"缺少JS函数: {','.join(missing)}")
                issues.append(f"🔴 {site_name} 缺少关键JS函数: {','.join(missing)}")
            else:
                site_result["details"].append(f"JS函数({len(key_js)}个)全部存在")

        results.append(site_result)

    # 4. 足球预测网专项：检查赔率数据源优先级
    fp_result = results[0]  # 足球预测网是第一个
    if fp_result["status"] == "ok":
        # 验证 schedule.json 中的赔率数据
        schedule_data, err = check_json_data("https://ceshi1986.github.io/football-predictions/schedule.json")
        if not err and schedule_data:
            matches = schedule_data if isinstance(schedule_data, list) else schedule_data.get("matches", [])
            odds_count = sum(1 for m in matches if m.get("odds"))
            fp_result["details"].append(f"schedule.json含赔率比赛: {odds_count}/{len(matches)}")
            if odds_count == 0 and len(matches) > 0:
                issues.append(f"🟡 足球预测网 schedule.json 无赔率数据（{len(matches)}场比赛均无odds）")

    # 汇总报告
    ok_count = sum(1 for r in results if r["status"] == "ok")
    total = len(results)

    report_lines = [f"📋 每日网站自检报告 ({now})"]
    report_lines.append(f"{'='*40}")
    for r in results:
        icon = "✅" if r["status"] == "ok" else ("️" if r["status"] == "warn" else "❌")
        report_lines.append(f"{icon} {r['name']} [{r['status'].upper()}]")
        for d in r["details"]:
            report_lines.append(f"   └ {d}")

    if issues:
        report_lines.append(f"\n{'='*40}")
        report_lines.append("⚠️ 发现问题：")
        for issue in issues:
            report_lines.append(f"  {issue}")
    else:
        report_lines.append(f"\n 全部 {total} 个网站检查通过")

    report = "\n".join(report_lines)
    return report, issues


def check_football_common_mistakes():
    """足球预测网常犯错误自动检查，返回(检查项列表, 问题列表)"""
    checks = []
    issues = []
    
    # 获取GitHub上的最新文件内容
    base_raw = "https://raw.githubusercontent.com/ceshi1986/football-predictions/main"
    
    def fetch_raw(path):
        url = f"{base_raw}/{path}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SelfCheck/1.0"})
            r = urllib.request.urlopen(req, timeout=15)
            return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            return None
    
    # 获取文件内容
    index_html = fetch_raw("index.html")
    daily_pred = fetch_raw("codeact/scripts/daily_predictions.py")
    fetch_sched = fetch_raw("scripts/fetch_schedule.py")
    schedule_json, sj_err = check_json_data("https://ceshi1986.github.io/football-predictions/schedule.json")
    ai_preds, ap_err = check_json_data("https://ceshi1986.github.io/football-predictions/data/ai-predictions.json")
    odds_json, od_err = check_json_data("https://ceshi1986.github.io/football-predictions/data/odds_api_odds.json")
    
    # === 检查1: 中超残留 ===
    cs_issues = []
    for fname, content in [("index.html", index_html), ("daily_predictions.py", daily_pred), ("fetch_schedule.py", fetch_sched)]:
        if content is None:
            continue
        if re.search(r'中超|chinese\.super|CHINESE_SUPER', content, re.IGNORECASE):
            # 排除注释中提到的"不含中超"之类的说明
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if re.search(r'中超|chinese\.super', line, re.IGNORECASE):
                    # 如果注释中是"不含中超"/"去掉中超"等说明性文字，不算残留
                    if '不含中超' in line or '去掉中超' in line or '已移除中超' in line or 'removed' in line.lower():
                        continue
                    cs_issues.append(f"{fname}:{i+1}")
    if cs_issues:
        issues.append(f"🔴 [常犯错误#3] 中超残留: {', '.join(cs_issues[:5])}")
    checks.append(f"中超残留检查: {'通过' if not cs_issues else '发现残留'}")
    
    # === 检查2: 前后端联赛白名单一致性 ===
    py_codes = set()
    if daily_pred:
        # 提取 ACTIVE_LEAGUE_CODES = {...}
        m = re.search(r'ACTIVE_LEAGUE_CODES\s*=\s*\{([^}]+)\}', daily_pred)
        if m:
            py_codes = set(re.findall(r'["\']([^"\']+)["\']', m.group(1)))
    
    js_codes = set()
    if index_html:
        # 提取 _activeLeagues={...} (可能有多处，取第一个完整的)
        m = re.search(r'_activeLeagues\s*=\s*\{([^}]+)\}', index_html)
        if m:
            js_codes = set(re.findall(r'"([^"]+)"\s*:\s*1', m.group(1)))
    
    whitelist_match = True
    if py_codes and js_codes:
        if py_codes != js_codes:
            only_py = py_codes - js_codes
            only_js = js_codes - py_codes
            msg = "🔴 [常犯错误#1] 前后端白名单不一致:"
            if only_py: msg += f" Python独有{only_py}"
            if only_js: msg += f" JS独有{only_js}"
            issues.append(msg)
            whitelist_match = False
        checks.append(f"白名单一致性: Python({len(py_codes)}个) vs JS({len(js_codes)}个) = 一致")
    else:
        checks.append(f"白名单一致性: 无法提取(Python={len(py_codes)}, JS={len(js_codes)})")
    
    # === 检查3: 已完赛比赛残留 ===
    if schedule_json:
        matches = schedule_json if isinstance(schedule_json, list) else schedule_json.get("matches", [])
        completed = [m for m in matches if m.get("status") in ("completed", "finished", "done")]
        if completed:
            issues.append(f"🟡 [常犯错误#2] schedule.json含{len(completed)}场已完赛比赛未过滤")
        checks.append(f"已完赛过滤: {'通过' if not completed else f'发现{len(completed)}场残留'}")
    
    # === 检查4: 非竞彩联赛数据 ===
    non_active = set()
    if schedule_json:
        matches = schedule_json if isinstance(schedule_json, list) else schedule_json.get("matches", [])
        for m in matches:
            lc = m.get("league_code") or m.get("leagueCode") or m.get("league") or ""
            if lc and lc not in ACTIVE_LEAGUE_CODES:
                non_active.add(lc)
    if non_active:
        issues.append(f"🟡 [常犯错误#3] schedule.json含非竞彩联赛: {non_active}")
    checks.append(f"非竞彩联赛过滤: {'通过' if not non_active else f'发现{non_active}'}")
    
    # === 检查5: 命中率统计范围一致性 ===
    if ai_preds and py_codes:
        verified = ai_preds.get("verified_predictions", []) if isinstance(ai_preds, dict) else []
        if verified:
            active_verified = [p for p in verified if p.get("leagueCode") in py_codes]
            total_verified = len(verified)
            active_count = len(active_verified)
            if total_verified != active_count:
                checks.append(f"命中率范围: 总验证{total_verified}场, 竞彩范围{active_count}场(差{total_verified-active_count}场非竞彩)")
            else:
                checks.append(f"命中率范围: 全部{total_verified}场均在竞彩范围内")
    
    # === 检查6: 赔率数据时效性 ===
    if odds_json:
        update_time = odds_json.get("update_time") or odds_json.get("timestamp") or odds_json.get("fetched_at", "")
        if update_time:
            try:
                from datetime import timezone
                ut = datetime.fromisoformat(update_time.replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - ut).total_seconds() / 3600
                if age_hours > 24:
                    issues.append(f"🔴 [常犯错误#5] 赔率数据超24h未更新({age_hours:.1f}小时前)")
                checks.append(f"赔率时效性: {age_hours:.1f}小时前更新{'  ✅' if age_hours <= 24 else ' ⚠️'}")
            except:
                checks.append("赔率时效性: 时间格式解析失败")
        else:
            checks.append("赔率时效性: 无时间戳字段")
        odds_count = len(odds_json.get("matches", [])) if isinstance(odds_json, dict) else 0
        checks.append(f"赔率数据量: {odds_count}场")
    else:
        issues.append(f"🔴 [常犯错误#5] odds_api_odds.json加载失败")
        checks.append("赔率数据: 加载失败")
    
    # === 检查7: 赔率数据合理性 ===
    if odds_json:
        odds_matches = odds_json.get("matches", []) if isinstance(odds_json, dict) else []
        bad_odds = []
        for m in odds_matches[:10]:  # 抽查前10场
            o = m.get("odds", {})
            h, d, a = o.get("h") or o.get("home"), o.get("d") or o.get("draw"), o.get("a") or o.get("away")
            if h and d and a:
                if not (1.01 <= h <= 50 and 1.01 <= d <= 50 and 1.01 <= a <= 50):
                    bad_odds.append(f"{m.get('home','?')}vs{m.get('away','?')}赔率异常({h}/{d}/{a})")
                total = h + d + a
                if total < 1.5:  # 三项之和过小可能是数据错误
                    bad_odds.append(f"{m.get('home','?')}vs{m.get('away','?')}三项和={total:.2f}")
        if bad_odds:
            issues.append(f"🟡 [常犯错误#6] 赔率异常: {bad_odds[0]}")
        checks.append(f"赔率合理性: 抽查{min(10,len(odds_matches))}场{'全部正常' if not bad_odds else f'发现{len(bad_odds)}场异常'}")
    
    # === 检查8: 主客队赔率一致性 ===
    if odds_json and schedule_json:
        odds_matches = odds_json.get("matches", []) if isinstance(odds_json, dict) else []
        sched_matches = schedule_json if isinstance(schedule_json, list) else schedule_json.get("matches", [])
        # 抽查前5场有赔率的比赛，验证主客队匹配
        mismatch_count = 0
        checked = 0
        for sm in sched_matches[:20]:
            if checked >= 5:
                break
            sh, sa = (sm.get("home") or "").lower(), (sm.get("away") or "").lower()
            if not sh or not sa:
                continue
            for om in odds_matches:
                oh, oa = (om.get("home") or "").lower(), (om.get("away") or "").lower()
                if not oh or not oa:
                    continue
                # 模糊匹配：主队在赔率中也是主队
                if (sh in oh or oh in sh) and (sa in oa or oa in sa):
                    checked += 1
                    break
                # 主客反了：主队变成了客队
                if (sh in oa or oa in sh) and (sa in oh or oh in sa):
                    mismatch_count += 1
                    checked += 1
                    break
        if mismatch_count > 0:
            issues.append(f"🔴 [常犯错误#7] 发现{mismatch_count}场主客队赔率匹配反转！")
        checks.append(f"主客队一致性: 抽查{checked}场{'全部正确' if mismatch_count == 0 else f'发现{mismatch_count}场反转'}")
    
    return checks, issues


def main():
    result_mode = sys.argv[1] if len(sys.argv) > 1 else "notify"
    report, issues = run_check()
    
    # 执行足球预测网常犯错误专项检查
    fp_checks, fp_issues = check_football_common_mistakes()
    if fp_checks:
        report += "\n\n📋 常犯错误专项检查："
        for c in fp_checks:
            report += f"\n   ├ {c}"
    if fp_issues:
        issues.extend(fp_issues)

    if not issues:
        # 无问题，安静返回
        print(report)
        if result_mode == "notify":
            CodeAct.notify("NO_REPLY")
        else:
            CodeAct.display(report)
    else:
        # 有问题，报告
        print(report)
        if result_mode == "notify":
            CodeAct.notify(report)
        else:
            CodeAct.display(report)


if __name__ == "__main__":
    main()
