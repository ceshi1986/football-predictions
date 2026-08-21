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
    cmd = [sys.executable, script_path, '--no-github']
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
        else:
            print(f"  ❌ GitHub推送失败: HTTP {resp.status_code}")
            print(f"     {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  ❌ GitHub推送异常: {e}")
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

    # 推送GitHub
    print(f"\n[推送] GitHub...")
    push_ok = push_to_github(date_str)

    # 汇总
    print(f"\n{'='*50}")
    print(f"  Kelly更新完成: {date_str}")
    print(f"  数据源: {data_source}")
    print(f"  比赛: {match_count}场 | 目标公司: {target_count}条")
    print(f"  GitHub: {'✅' if push_ok else '❌'}")
    print(f"{'='*50}")


if __name__ == '__main__':
    main()
