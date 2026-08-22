#!/usr/bin/env python3
"""
回测表辅助模块 V1.0
为 daily_predictions.py 和 kelly_update.py 提供统一的回测表读写接口。

回测表结构:
{
  "detail": [
    {
      "date": "20260822",
      "home": "队名", "away": "队名",
      "match_id": "竞彩编号或fid",
      "league": "联赛名",
      "score_h": 2, "score_a": 0,       # 赛前为null
      "result": "胜",                    # 赛前为null
      "scenario": "AA",                  # Kelly场景分类
      "strong": "home"/"away",           # 强队方向
      "is_strong_home": true/false,
      "subgroup": "AA主"/"AA客",         # 72子组
      "sig_365": "A", "sig_weide": "A",  # 两家状态字母
      "sig_365_raw": "A", "sig_weide_raw": "A",
      "prediction": "胜+平",             # 预测方向
      "pred_type": "double"/"single",
      "kelly_365": [0.92, 0.85, 1.05],  # 赛前Kelly值
      "kelly_weide": [0.90, 0.88, 1.02],
      "odds_365": [1.85, 3.40, 4.20],   # 赛前赔率
      "locked_at": "2026-08-22T17:00:00", # 锁定时间
      "hit": true/false/null,            # 赛后判定
      "created_at": "2026-08-22T10:00:00",
      "updated_at": "2026-08-22T17:00:00"
    }
  ],
  "total_matches": 888,
  "last_updated": "2026-08-23T05:56:09"
}
"""
import json
import os
from datetime import datetime
from typing import Optional

# 回测表路径（相对于 fp-repo/ 根目录）
BACKTEST_FILENAME = "backtest_master_table_dedup.json"


def _get_backtest_path(base_dir: str = None) -> str:
    """获取回测表绝对路径"""
    if base_dir is None:
        # 默认: 脚本在 fp-repo/codeact/scripts/，回测表在 fp-repo/
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.dirname(os.path.dirname(script_dir))
    return os.path.join(base_dir, BACKTEST_FILENAME)


def load_backtest(path: str = None) -> dict:
    """加载回测表，返回完整dict"""
    if path is None:
        path = _get_backtest_path()
    if not os.path.exists(path):
        return {"detail": [], "total_matches": 0, "last_updated": ""}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "detail" not in data:
            data["detail"] = []
        return data
    except Exception as e:
        print(f"[BACKTEST] 加载回测表失败: {e}")
        return {"detail": [], "total_matches": 0, "last_updated": ""}


def save_backtest(data: dict, path: str = None) -> bool:
    """保存回测表"""
    if path is None:
        path = _get_backtest_path()
    try:
        data["total_matches"] = len(data.get("detail", []))
        data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 先写临时文件再rename，防止写坏
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        print(f"[BACKTEST] 保存回测表失败: {e}")
        return False


def _make_key(date: str, home: str, away: str) -> str:
    """生成去重键: 日期+主队+客队（队名strip后）"""
    return f"{date}|{home.strip()}|{away.strip()}"


def _record_key(record: dict) -> str:
    """从记录生成去重键"""
    return _make_key(
        record.get("date", ""),
        record.get("home", ""),
        record.get("away", ""),
    )


def upsert_schedule_records(
    matches: list,
    date_str: str,
    base_dir: str = None,
) -> dict:
    """
    步骤①：获取赛程后，批量新建回测表记录（已存在的跳过）。
    
    Args:
        matches: 赛程列表，每个dict需含 home/away，可选 match_id/league/match_time
        date_str: 比赛日期 YYYYMMDD
    
    Returns:
        {"added": 新增数, "skipped": 跳过数, "total": 总数}
    """
    data = load_backtest(base_dir)
    existing_keys = {_record_key(r) for r in data["detail"]}
    
    added = 0
    skipped = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for m in matches:
        home = m.get("home", "").strip()
        away = m.get("away", "").strip()
        if not home or not away:
            continue
        
        key = _make_key(date_str, home, away)
        if key in existing_keys:
            skipped += 1
            continue
        
        record = {
            "date": date_str,
            "home": home,
            "away": away,
            "match_id": m.get("id", m.get("match_id", "")),
            "league": m.get("leagueShort", m.get("leagueName", m.get("league", ""))),
            "score_h": None,
            "score_a": None,
            "result": None,
            "scenario": None,
            "strong": None,
            "is_strong_home": None,
            "subgroup": None,
            "sig_365": None,
            "sig_weide": None,
            "sig_365_raw": None,
            "sig_weide_raw": None,
            "prediction": None,
            "pred_type": None,
            "kelly_365": None,
            "kelly_weide": None,
            "odds_365": None,
            "locked_at": None,
            "hit": None,
            "created_at": now,
            "updated_at": now,
        }
        data["detail"].append(record)
        existing_keys.add(key)
        added += 1
    
    if added > 0:
        save_backtest(data, base_dir)
    
    print(f"[BACKTEST] 赛程写入: 新增{added}场, 跳过{skipped}场, 总计{len(data['detail'])}场")
    return {"added": added, "skipped": skipped, "total": len(data["detail"])}


def update_prediction_record(
    date_str: str,
    home: str,
    away: str,
    scenario: str = None,
    sig_365: str = None,
    sig_weide: str = None,
    is_home_strong: bool = None,
    prediction: str = None,
    pred_type: str = None,
    kelly_365: list = None,
    kelly_weide: list = None,
    odds_365: list = None,
    locked_at: str = None,
    base_dir: str = None,
) -> bool:
    """
    步骤②：Kelly数据+预测生成后，回填场景分类和预测方向到回测表。
    如果记录不存在则自动创建。
    
    Returns:
        True if updated/created, False if error
    """
    data = load_backtest(base_dir)
    key = _make_key(date_str, home, away)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    target = None
    for r in data["detail"]:
        if _record_key(r) == key:
            target = r
            break
    
    if target is None:
        # 记录不存在，自动创建
        target = {
            "date": date_str,
            "home": home.strip(),
            "away": away.strip(),
            "score_h": None, "score_a": None, "result": None,
            "created_at": now,
        }
        data["detail"].append(target)
    
    # 回填字段
    if scenario is not None:
        target["scenario"] = scenario
    if sig_365 is not None:
        target["sig_365"] = sig_365
        target["sig_365_raw"] = sig_365
    if sig_weide is not None:
        target["sig_weide"] = sig_weide
        target["sig_weide_raw"] = sig_weide
    if is_home_strong is not None:
        target["is_strong_home"] = is_home_strong
        target["strong"] = "home" if is_home_strong else "away"
        # 计算72子组
        if scenario:
            suffix = "主" if is_home_strong else "客"
            target["subgroup"] = f"{scenario}{suffix}"
    if prediction is not None:
        target["prediction"] = prediction
    if pred_type is not None:
        target["pred_type"] = pred_type
    if kelly_365 is not None:
        target["kelly_365"] = kelly_365
    if kelly_weide is not None:
        target["kelly_weide"] = kelly_weide
    if odds_365 is not None:
        target["odds_365"] = odds_365
    if locked_at is not None:
        target["locked_at"] = locked_at
    
    target["updated_at"] = now
    save_backtest(data, base_dir)
    return True


def update_match_result(
    date_str: str,
    home: str,
    away: str,
    score_h: int,
    score_a: int,
    base_dir: str = None,
) -> Optional[dict]:
    """
    步骤③：赛后回填比分和赛果，自动判定命中/未中。
    
    Returns:
        更新后的record dict，或None if not found
    """
    data = load_backtest(base_dir)
    key = _make_key(date_str, home, away)
    
    target = None
    for r in data["detail"]:
        if _record_key(r) == key:
            target = r
            break
    
    if target is None:
        print(f"[BACKTEST] 未找到记录: {date_str} {home} vs {away}")
        return None
    
    target["score_h"] = score_h
    target["score_a"] = score_a
    
    if score_h > score_a:
        result = "胜"
    elif score_h < score_a:
        result = "负"
    else:
        result = "平"
    target["result"] = result
    
    # 判定命中
    prediction = target.get("prediction", "")
    pred_type = target.get("pred_type", "")
    if prediction and result:
        if pred_type == "single":
            target["hit"] = (prediction == result)
        else:
            # 双选：prediction格式如"胜+平"，或直接包含结果字
            if "+" in prediction:
                picks = prediction.split("+")
            else:
                picks = list(prediction)
            target["hit"] = result in picks
    else:
        target["hit"] = None
    
    target["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_backtest(data, base_dir)
    
    hit_str = "✅命中" if target.get("hit") else ("❌未中" if target.get("hit") is False else "—")
    print(f"[BACKTEST] 赛果回填: {home} {score_h}-{score_a} {away} | {result} | {hit_str}")
    return target


def get_pending_results(date_str: str = None, base_dir: str = None) -> list:
    """
    获取待填赛果的记录（有预测但无比分）。
    如果指定date_str则只返回该日期的。
    """
    data = load_backtest(base_dir)
    pending = []
    for r in data["detail"]:
        if r.get("score_h") is not None:
            continue
        if r.get("scenario") is None:
            continue  # 没有场景分类的不统计
        if date_str and r.get("date") != date_str:
            continue
        pending.append(r)
    return pending


def get_subgroup_stats(base_dir: str = None) -> dict:
    """
    步骤⑤：按72子组统计命中率。
    返回 {subgroup: {total, hits, hit_rate, scenarios: ...}}
    """
    data = load_backtest(base_dir)
    stats = {}
    for r in data["detail"]:
        sg = r.get("subgroup")
        if not sg or r.get("hit") is None:
            continue
        if sg not in stats:
            stats[sg] = {"total": 0, "hits": 0, "scenario": r.get("scenario", "")}
        stats[sg]["total"] += 1
        if r["hit"]:
            stats[sg]["hits"] += 1
    
    for sg in stats:
        t = stats[sg]["total"]
        stats[sg]["hit_rate"] = round(stats[sg]["hits"] / t * 100, 1) if t > 0 else 0
    
    return stats


if __name__ == "__main__":
    # 简单自测
    data = load_backtest()
    print(f"回测表: {len(data['detail'])} 条记录")
    pending = get_pending_results()
    print(f"待填赛果: {len(pending)} 条")
    stats = get_subgroup_stats()
    print(f"子组统计: {len(stats)} 个子组")
    for sg, s in sorted(stats.items(), key=lambda x: -x[1]["total"])[:10]:
        print(f"  {sg}: {s['hits']}/{s['total']} = {s['hit_rate']}%")
