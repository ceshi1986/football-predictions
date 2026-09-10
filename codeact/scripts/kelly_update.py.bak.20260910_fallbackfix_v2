#!/usr/bin/env python3
"""
Kelly数据更新调度器 v1.0
优先500万网，失败/0数据时回退zgzcw，最后推送GitHub。

用法：
    python3 kelly_update.py              # 正常运行
    python3 kelly_update.py --force-zgzcw  # 强制只用zgzcw
"""
import subprocess
import sys
import os
import json
import base64
import requests as req_lib
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # fp-repo/
DATA_DIR = os.path.join(BASE_DIR, "data", "500com_daily")

SCRAPE_500COM = os.path.join(SCRIPT_DIR, "scrape_500com_kelly.py")
SCRAPE_ZGZCW = os.path.join(SCRIPT_DIR, "scrape_zgzcw_kelly.py")

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GITHUB_REPO = 'ceshi1986/football-predictions'
GITHUB_API = f'https://api.github.com/repos/{GITHUB_REPO}/contents'

# 目标公司（判断数据有效性）
TARGET_COMPANIES = {'bet365', 'weide', 'libo', 'william_hill'}


def get_today():
    return datetime.now().strftime('%Y%m%d')


def get_output_path(date_str):
    return os.path.join(DATA_DIR, date_str, "zgzcw_kelly_data.json")


def run_script(script_path, label, extra_args=None):
    """运行抓取脚本，返回(成功与否, 比赛数, 目标公司条数)"""
    print(f"\n{'='*50}")
    print(f"  数据源: {label}")
    print(f"{'='*50}")
    cmd = [sys.executable, script_path, '--no-github', '--use-requests']
    if extra_args:
        cmd.extend(extra_args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, cwd=BASE_DIR
        )
        print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
        if result.stderr:
            # 只打印最后500字符的stderr
            err = result.stderr.strip()
            if err:
                print(f"  [stderr] {err[-500:]}")
        if result.returncode != 0:
            print(f"  ❌ {label} 脚本退出码: {result.returncode}")
            return False, 0, 0
    except subprocess.TimeoutExpired:
        print(f"  ❌ {label} 超时(300s)")
        return False, 0, 0
    except Exception as e:
        print(f"  ❌ {label} 运行异常: {e}")
        return False, 0, 0

    # 检查输出文件
    date_str = get_today()
    out_path = get_output_path(date_str)
    if not os.path.exists(out_path):
        print(f"  ❌ {label} 输出文件不存在: {out_path}")
        return False, 0, 0

    try:
        with open(out_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        total = data.get('total_matches', 0)
        matches = data.get('matches', {})
        if isinstance(matches, dict):
            match_count = len(matches)
        elif isinstance(matches, list):
            match_count = len(matches)
        else:
            match_count = 0
        target_count = 0
        for m in (matches.values() if isinstance(matches, dict) else matches):
            comps = m.get('companies', {})
            target_count += sum(1 for k in TARGET_COMPANIES if k in comps)
        print(f"  ✅ {label}: {match_count}场, {target_count}条目标公司")
        return match_count > 0, match_count, target_count
    except Exception as e:
        print(f"  ❌ {label} 读取输出失败: {e}")
        return False, 0, 0


def push_to_github(date_str):
    """推送数据文件到GitHub"""
    out_path = get_output_path(date_str)
    if not os.path.exists(out_path):
        print(f"  ⚠️ 文件不存在，跳过推送: {out_path}")
        return False

    # 检查数据有效性
    try:
        with open(out_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get('total_matches', 0) == 0:
            print("  ⚠️ 数据为空(total_matches=0)，跳过推送")
            return False
    except Exception:
        return False

    repo_path = f'data/500com_daily/{date_str}/zgzcw_kelly_data.json'
    with open(out_path, 'rb') as f:
        content_b64 = base64.b64encode(f.read()).decode('utf-8')

    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }

    # 检查文件是否已存在（获取SHA）
    sha = None
    try:
        check = req_lib.get(f'{GITHUB_API}/{repo_path}', headers=headers, timeout=10)
        if check.status_code == 200:
            sha = check.json().get('sha')
            print(f"  文件已存在，将更新 (sha={sha[:8]})")
        elif check.status_code == 404:
            print("  文件不存在，将创建新文件")
    except Exception as e:
        print(f"  检查文件状态失败: {e}")

    # PUT with retry on 409 (SHA conflict from concurrent pushes)
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        payload = {
            'message': f'📊 Kelly数据 {date_str} - {datetime.now().strftime("%H:%M")}',
            'content': content_b64,
        }
        if sha:
            payload['sha'] = sha
        try:
            resp = req_lib.put(
                f'{GITHUB_API}/{repo_path}', headers=headers, json=payload, timeout=30
            )
            if resp.status_code in (200, 201):
                print(f"  ✅ GitHub推送成功")
                return True
            elif resp.status_code == 409 and attempt < max_retries:
                # SHA conflict - refetch latest SHA and retry
                print(f"  ⚠️ HTTP 409 SHA冲突，重试({attempt}/{max_retries})...")
                try:
                    check2 = req_lib.get(f'{GITHUB_API}/{repo_path}', headers=headers, timeout=10)
                    if check2.status_code == 200:
                        sha = check2.json().get('sha')
                        print(f"     获取最新SHA: {sha[:8]}")
                except Exception:
                    pass
                import time as _time
                _time.sleep(1)
                continue
            else:
                print(f"  ❌ GitHub推送失败: HTTP {resp.status_code}")
                print(f"     {resp.text[:200]}")
                return False
        except Exception as e:
            print(f"  ❌ GitHub推送异常: {e}")
            return False
    print(f"  ❌ GitHub推送失败: 重试{max_retries}次后仍409")
    return False


def save_snapshot(date_str):
    """保存快照"""
    out_path = get_output_path(date_str)
    snap_dir = os.path.join(DATA_DIR, date_str, "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    time_str = datetime.now().strftime('%H%M%S')
    snap_path = os.path.join(snap_dir, f'kelly_snapshot_{time_str}.json')
    try:
        import shutil
        shutil.copy2(out_path, snap_path)
        print(f"  📸 快照已保存: {os.path.basename(snap_path)}")
    except Exception as e:
        print(f"  ⚠️ 快照保存失败: {e}")


def main():
    force_zgzcw = '--force-zgzcw' in sys.argv
    date_str = get_today()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    print(f"[Kelly Update] {now_str}")
    print(f"  日期={date_str}, 输出目录={os.path.join(DATA_DIR, date_str)}")

    os.makedirs(os.path.join(DATA_DIR, date_str), exist_ok=True)

    success = False
    match_count = 0
    target_count = 0

    # 第一步：500万网（优先）
    if not force_zgzcw and os.path.exists(SCRAPE_500COM):
        ok, mc, tc = run_script(SCRAPE_500COM, "500万网")
        if ok:
            success = True
            match_count = mc
            target_count = tc
            data_source = "500.com"
        else:
            print(f"\n  ⚠️ 500万网无数据，回退zgzcw...")
    elif force_zgzcw:
        print("  --force-zgzcw 指定，跳过500万网")
    else:
        print("  ⚠️ 500万网脚本不存在，跳过")

    # 第二步：zgzcw（兜底）
    if not success and os.path.exists(SCRAPE_ZGZCW):
        ok, mc, tc = run_script(SCRAPE_ZGZCW, "zgzcw中国足彩网")
        if ok:
            success = True
            match_count = mc
            target_count = tc
            data_source = "zgzcw.com"
    elif not success:
        print("  ❌ zgzcw脚本也不存在，无法抓取")

    if not success:
        print(f"\n❌ 所有数据源均失败，静默退出")
        sys.exit(0)

    # 保存快照
    save_snapshot(date_str)

    # 赛前60分钟锁定预测
    print(f"\n[锁定] 检查赛前60分钟锁定...")
    update_locked_predictions(date_str)

    # 推送GitHub
    print(f"\n[推送] GitHub...")
    push_ok = push_to_github(date_str)
    push_locked_to_github(date_str)

    # 汇总
    print(f"\n{'='*50}")
    print(f"  Kelly更新完成: {date_str}")
    print(f"  数据源: {data_source}")
    print(f"  比赛: {match_count}场 | 目标公司: {target_count}条")
    print(f"  GitHub: {'✅' if push_ok else '❌'}")
    print(f"{'='*50}")


def update_locked_predictions(date_str):
    """
    赛前60分钟锁定预测。
    每场比赛在距开赛60-90分钟窗口内首次抓取时，冻结当时的Kelly和亚盘原始数据，
    存入 data/500com_daily/{date}/locked_predictions.json。
    前端加载时用锁定数据覆盖实时数据，保证赛前1小时内预测不再变化。
    """
    out_path = get_output_path(date_str)
    if not os.path.exists(out_path):
        return
    try:
        with open(out_path, 'r', encoding='utf-8') as f:
            current = json.load(f)
    except Exception as e:
        print(f"  [锁定] 读取当前数据失败: {e}")
        return

    matches = current.get('matches', {})
    if isinstance(matches, list):
        match_items = [(str(m.get('jingcai_id') or m.get('id') or m.get('fixture_id') or i), m)
                       for i, m in enumerate(matches)]
    else:
        match_items = list(matches.items())

    lock_path = os.path.join(DATA_DIR, date_str, "locked_predictions.json")
    locked = {}
    if os.path.exists(lock_path):
        try:
            with open(lock_path, 'r', encoding='utf-8') as f:
                locked = json.load(f)
        except:
            locked = {}

    now = datetime.now()
    new_locks = 0
    for mid, m in match_items:
        if not mid or mid == 'None':
            continue
        # 已用任一ID锁定过则跳过
        jc_id = str(m.get('jingcai_id') or '')
        bd_id = str(m.get('beidan_id') or '')
        if mid in locked or (jc_id and jc_id in locked) or (bd_id and bd_id in locked):
            continue
        mt = m.get('match_time', '')
        if not mt:
            continue
        try:
            parts = mt.split(' ')
            mmdd = parts[0].split('-')
            hhmm = parts[1].split(':')
            kickoff = datetime(now.year, int(mmdd[0]), int(mmdd[1]), int(hhmm[0]), int(hhmm[1]))
        except:
            continue
        mins_to_kickoff = (kickoff - now).total_seconds() / 60
        # 60-90分钟窗口：首次进入就锁定
        if 60 <= mins_to_kickoff <= 90:
            companies = m.get('companies', {})
            macau = companies.get('macau', {})
            def extract(key):
                return companies.get(key, {})
            # 锁定数据按所有可用ID各存一份（竞彩/北单/fixture），前端按哪个ID都能匹配
            lock_data = {
                'home': m.get('home'),
                'away': m.get('away'),
                'match_time': mt,
                'locked_at': now.strftime('%Y-%m-%d %H:%M:%S'),
                'mins_to_kickoff': round(mins_to_kickoff),
                'companies': {
                    'bet365': extract('bet365'),
                    'weide': extract('weide'),
                    'libo': extract('libo'),
                    'william_hill': extract('william_hill'),
                    'macau': {
                        'initial_handicap_str': macau.get('initial_handicap_str'),
                        'latest_handicap_str': macau.get('latest_handicap_str'),
                        'initial_handicap_val': macau.get('initial_handicap_val'),
                        'latest_handicap_val': macau.get('latest_handicap_val'),
                    }
                }
            }
            # 用所有可用ID作为key
            all_ids = set()
            if jc_id: all_ids.add(jc_id)
            if bd_id: all_ids.add(bd_id)
            all_ids.add(mid)
            for kid in all_ids:
                locked[kid] = lock_data
            new_locks += 1
            print(f"  🔒 锁定 {m.get('home','?')} vs {m.get('away','?')} (距开赛{int(mins_to_kickoff)}分, IDs={all_ids})")

    if new_locks > 0 or not os.path.exists(lock_path):
        with open(lock_path, 'w', encoding='utf-8') as f:
            json.dump(locked, f, ensure_ascii=False, indent=2)
        print(f"  [锁定] 已保存 {len(locked)} 场锁定预测 (+{new_locks})")


def push_locked_to_github(date_str):
    """推送锁定预测文件到GitHub"""
    lock_path = os.path.join(DATA_DIR, date_str, "locked_predictions.json")
    if not os.path.exists(lock_path):
        return False
    repo_path = f'data/500com_daily/{date_str}/locked_predictions.json'
    with open(lock_path, 'rb') as f:
        content_b64 = base64.b64encode(f.read()).decode('utf-8')
    headers = {'Authorization': f'token {GITHUB_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    sha = None
    try:
        check = req_lib.get(f'{GITHUB_API}/{repo_path}', headers=headers, timeout=10)
        if check.status_code == 200:
            sha = check.json().get('sha')
    except:
        pass
    payload = {'message': f'🔒 锁定预测 {date_str} - {datetime.now().strftime("%H:%M")}', 'content': content_b64}
    if sha:
        payload['sha'] = sha
    try:
        resp = req_lib.put(f'{GITHUB_API}/{repo_path}', headers=headers, json=payload, timeout=30)
        if resp.status_code in (200, 201):
            print(f"  ✅ 锁定预测已推送GitHub")
            return True
    except Exception as e:
        print(f"  [锁定] 推送失败: {e}")
    return False


if __name__ == '__main__':
    main()