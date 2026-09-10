#!/usr/bin/env python3
"""
竞彩模拟投注核心引擎 (bet_sim_engine.py)
- 自动模拟单生成：赛前60分钟预测锁定后，基于V6.9预测生成模拟投注单
- 赛后自动结算：对接赛果回填流程，结算未结算模拟单
- 战绩统计：累计投入/回收/收益率/胜率/近30天盈亏/按玩法分组
- SQLite 状态库：bets 表存投注单，settlements 表存结算，幂等可重复跑

金额单位：分（整数），避免浮点误差。
每注2元 = 200分。

用法:
  python bet_sim_engine.py [result_mode] [repo_dir] [mode]
  - result_mode: display_only | auto (默认 display_only)
  - repo_dir: fp-repo 绝对路径
  - mode: auto | generate | settle | stats (默认 auto，即生成+结算+统计)
"""
import asyncio
import json
import os
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Optional

from codeact_sdk import CodeActSDK

TOOL_SCHEMA_VERSIONS = {
    "codeact_fetch_web": "v1_2c8d0580b3f93a58",
    "codeact_search_web": "v1_5ac1b0eba8c26f2a",
}

CST = timezone(timedelta(hours=8))

# ─── 常量 ───────────────────────────────────────────────────
UNIT_BET_FEN = 200  # 每注2元 = 200分
DEFAULT_MULTIPLIER = 5  # 默认倍数

# 奖金封顶规则（分）
PRIZE_CAPS = {
    1: 100000 * 100,     # 单场: 10万
    2: 200000 * 100,     # 2-3场: 20万
    3: 200000 * 100,
    4: 500000 * 100,     # 4-5场: 50万
    5: 500000 * 100,
}
PRIZE_CAP_6PLUS = 1000000 * 100  # 6场以上: 100万

# 玩法代码
PLAY_HAD = "had"    # 胜平负
PLAY_HHAD = "hhad"  # 让球胜平负
PLAY_CRS = "crs"    # 比分
PLAY_TTG = "ttg"    # 总进球
PLAY_HAFU = "hafu"  # 半全场

PLAY_NAMES = {
    PLAY_HAD: "胜平负",
    PLAY_HHAD: "让球胜平负",
    PLAY_CRS: "比分",
    PLAY_TTG: "总进球",
    PLAY_HAFU: "半全场",
}

# 串关方式
PARLAY_SINGLE = "single"  # 单关
PARLAY_2 = "parlay_2"     # 2串1
PARLAY_3 = "parlay_3"     # 3串1
PARLAY_4 = "parlay_4"     # 4串1
PARLAY_FREE = "free"      # 自由过关(待扩展)

PARLAY_NAMES = {
    PARLAY_SINGLE: "单关",
    PARLAY_2: "2串1",
    PARLAY_3: "3串1",
    PARLAY_4: "4串1",
    PARLAY_FREE: "自由过关",
}


def now_cst() -> datetime:
    return datetime.now(CST)


def today_str() -> str:
    return now_cst().strftime("%Y%m%d")


def parse_kickoff(kickoff_str: str) -> Optional[datetime]:
    """解析开赛时间"""
    if not kickoff_str:
        return None
    try:
        return datetime.fromisoformat(kickoff_str.replace("Z", "+00:00"))
    except Exception:
        return None


# ─── SQLite 状态库 ────────────────────────────────────────
class BetSimDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS bets (
                bet_id TEXT PRIMARY KEY,
                bet_date TEXT NOT NULL,
                bet_type TEXT NOT NULL,          -- single / parlay
                parlay_type TEXT NOT NULL,       -- single / parlay_2 / parlay_3 / parlay_4
                play_type TEXT NOT NULL,         -- had / hhad / crs / ttg / hafu / mixed
                match_count INTEGER NOT NULL,
                matches_json TEXT NOT NULL,      -- JSON数组，每场包含match_id, play_type, selections, odds等
                combos INTEGER NOT NULL,
                multiplier INTEGER NOT NULL,
                total_stake_fen INTEGER NOT NULL,  -- 总投入（分）
                max_prize_fen INTEGER NOT NULL,    -- 理论最高奖金（分）
                source TEXT NOT NULL,              -- auto / manual
                status TEXT NOT NULL,              -- pending / settled / cancelled
                created_at TEXT NOT NULL,
                settled_at TEXT,
                pnl_fen INTEGER,                   -- 盈亏（分）
                total_return_fen INTEGER,          -- 总回收（分）
                win INTEGER,                       -- 是否盈利 1/0
                result_detail TEXT,                -- 结算明细JSON
                remark TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status);
            CREATE INDEX IF NOT EXISTS idx_bets_date ON bets(bet_date);
            CREATE INDEX IF NOT EXISTS idx_bets_play ON bets(play_type);
            CREATE INDEX IF NOT EXISTS idx_bets_parlay ON bets(parlay_type);

            CREATE TABLE IF NOT EXISTS daily_stats (
                stat_date TEXT PRIMARY KEY,
                total_stake_fen INTEGER NOT NULL DEFAULT 0,
                total_return_fen INTEGER NOT NULL DEFAULT 0,
                pnl_fen INTEGER NOT NULL DEFAULT 0,
                bet_count INTEGER NOT NULL DEFAULT 0,
                win_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        self.conn.commit()

    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def insert_bet(self, bet: dict) -> bool:
        """插入投注单，幂等（bet_id已存在则返回False）"""
        existing = self.conn.execute(
            "SELECT bet_id FROM bets WHERE bet_id=?", (bet["bet_id"],)
        ).fetchone()
        if existing:
            return False
        self.conn.execute("""
            INSERT INTO bets (
                bet_id, bet_date, bet_type, parlay_type, play_type, match_count,
                matches_json, combos, multiplier, total_stake_fen, max_prize_fen,
                source, status, created_at, remark
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            bet["bet_id"], bet["bet_date"], bet["bet_type"], bet["parlay_type"],
            bet["play_type"], bet["match_count"], json.dumps(bet["matches"], ensure_ascii=False),
            bet["combos"], bet["multiplier"], bet["total_stake_fen"],
            bet["max_prize_fen"], bet["source"], "pending",
            bet["created_at"], bet.get("remark", ""),
        ))
        self.conn.commit()
        return True

    def get_pending_bets(self) -> list:
        rows = self.conn.execute(
            "SELECT * FROM bets WHERE status='pending' ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def settle_bet(self, bet_id: str, pnl_fen: int, total_return_fen: int,
                   win: bool, result_detail: dict, settled_at: str):
        self.conn.execute("""
            UPDATE bets SET status='settled', settled_at=?, pnl_fen=?,
                total_return_fen=?, win=?, result_detail=?
            WHERE bet_id=? AND status='pending'
        """, (settled_at, pnl_fen, total_return_fen, 1 if win else 0,
              json.dumps(result_detail, ensure_ascii=False), bet_id))
        self.conn.commit()

    def get_all_settled_bets(self) -> list:
        rows = self.conn.execute(
            "SELECT * FROM bets WHERE status='settled' ORDER BY settled_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_daily_stats(self, date_str: str, stake: int, ret: int,
                           pnl: int, bet_count: int, win_count: int, updated_at: str):
        self.conn.execute("""
            INSERT INTO daily_stats(stat_date, total_stake_fen, total_return_fen,
                pnl_fen, bet_count, win_count, updated_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(stat_date) DO UPDATE SET
                total_stake_fen=excluded.total_stake_fen,
                total_return_fen=excluded.total_return_fen,
                pnl_fen=excluded.pnl_fen,
                bet_count=excluded.bet_count,
                win_count=excluded.win_count,
                updated_at=excluded.updated_at
        """, (date_str, stake, ret, pnl, bet_count, win_count, updated_at))
        self.conn.commit()

    def get_daily_stats(self, days: int = 30) -> list:
        rows = self.conn.execute(
            "SELECT * FROM daily_stats ORDER BY stat_date DESC LIMIT ?", (days,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_group_stats(self) -> dict:
        """按玩法和串关方式分组统计"""
        rows = self.conn.execute("""
            SELECT play_type, parlay_type,
                   COUNT(*) as bet_count,
                   SUM(win) as win_count,
                   SUM(total_stake_fen) as total_stake,
                   SUM(total_return_fen) as total_return,
                   SUM(pnl_fen) as pnl
            FROM bets WHERE status='settled'
            GROUP BY play_type, parlay_type
            ORDER BY play_type, parlay_type
        """).fetchall()
        return [dict(r) for r in rows]

    def generate_bet_id(self, prefix: str = "B") -> str:
        """生成投注单ID"""
        counter = int(self.get_meta("bet_counter", "0")) + 1
        self.set_meta("bet_counter", str(counter))
        return f"{prefix}{counter:06d}"

    def close(self):
        self.conn.close()


# ─── 赔率数据加载 ──────────────────────────────────────────
def load_sporttery_odds(repo_dir: str, date_str: str) -> list:
    """加载指定日期的竞彩官方赔率数据"""
    path = os.path.join(repo_dir, "data", "sporttery_odds", f"{date_str}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("matches", [])
    except Exception as e:
        print(f"[WARN] 加载赔率数据失败 {path}: {e}")
        return []


# ─── 预测数据加载 ──────────────────────────────────────────
def load_locked_predictions(repo_dir: str, date_str: str) -> dict:
    """加载已锁定的预测数据"""
    path = os.path.join(repo_dir, "data", "500com_daily", date_str, "locked_predictions.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] 加载锁定预测失败 {path}: {e}")
        return {}


# ─── 赛果数据加载 ──────────────────────────────────────────
def load_match_results(repo_dir: str) -> dict:
    """从多个来源加载赛果，返回 {match_id: {home_score, away_score}}"""
    results = {}

    # 来源1: backtest_master_table_dedup.json
    bt_path = os.path.join(repo_dir, "backtest_master_table_dedup.json")
    if os.path.exists(bt_path):
        try:
            with open(bt_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for m in data if isinstance(data, list) else data.get("matches", []):
                hscore = m.get("homeScore") or m.get("home_score")
                ascore = m.get("awayScore") or m.get("away_score")
                if hscore is None or ascore is None:
                    continue
                mid = m.get("matchId") or m.get("match_id") or m.get("id")
                jc_num = m.get("jcNum") or m.get("jc_num")
                entry = {"home_score": hscore, "away_score": ascore}
                if mid:
                    results[str(mid)] = entry
                if jc_num:
                    results[str(jc_num)] = entry
        except Exception as e:
            print(f"[WARN] 读取backtest主表失败: {e}")

    # 来源2: schedule.json
    sch_path = os.path.join(repo_dir, "schedule.json")
    if os.path.exists(sch_path):
        try:
            with open(sch_path, "r", encoding="utf-8") as f:
                sched = json.load(f)
            for m in sched.get("matches", []):
                if m.get("completed") and m.get("homeScore") is not None:
                    jc_num = m.get("jcNum")
                    bd_num = m.get("bdNum")
                    entry = {"home_score": m["homeScore"], "away_score": m["awayScore"]}
                    if jc_num:
                        results[str(jc_num)] = entry
                    if bd_num:
                        results[f"bd_{bd_num}"] = entry
        except Exception as e:
            print(f"[WARN] 读取schedule.json失败: {e}")

    return results


# ─── 比赛结果判定 ──────────────────────────────────────────
def determine_had_result(home_score: int, away_score: int) -> str:
    """胜平负结果: h/d/a"""
    if home_score > away_score:
        return "h"
    elif home_score == away_score:
        return "d"
    else:
        return "a"


def determine_hhad_result(home_score: int, away_score: int, handicap: float) -> str:
    """让球胜平负结果"""
    adj_home = home_score + handicap
    return determine_had_result(adj_home, away_score)


def determine_crs_result(home_score: int, away_score: int) -> str:
    """比分结果，返回crs键名
    0-0→s00s00, 1-0→s01s00, ..., 胜其他→s1sh, 平其他→s1sd, 负其他→s1sa
    """
    max_std = 5
    if home_score <= max_std and away_score <= max_std:
        return f"s{home_score:02d}s{away_score:02d}"
    # 其他
    if home_score > away_score:
        return "s1sh"
    elif home_score == away_score:
        return "s1sd"
    else:
        return "s1sa"


def determine_ttg_result(home_score: int, away_score: int) -> str:
    """总进球结果 0-7（7+）"""
    total = home_score + away_score
    if total >= 7:
        return "7"
    return str(total)


def determine_hafu_result(home_score: int, away_score: int,
                          ht_home: int = None, ht_away: int = None) -> str:
    """半全场结果: hh/hd/ha/dh/dd/da/ah/ad/aa
    没有半场比分时，用全场比分推断（假设领先方半场也领先）
    """
    # 半场结果推断（无半场数据时的简化处理）
    if ht_home is None or ht_away is None:
        if home_score > away_score:
            ht_h, ht_a = 1, 0
        elif home_score < away_score:
            ht_h, ht_a = 0, 1
        else:
            ht_h, ht_a = 0, 0
    else:
        ht_h, ht_a = ht_home, ht_away

    half = determine_had_result(ht_h, ht_a)
    full = determine_had_result(home_score, away_score)
    return half + full


def get_actual_result(play_type: str, home_score: int, away_score: int,
                      handicap: float = 0) -> Optional[str]:
    """根据玩法获取实际赛果键"""
    if play_type == PLAY_HAD:
        return determine_had_result(home_score, away_score)
    elif play_type == PLAY_HHAD:
        return determine_hhad_result(home_score, away_score, handicap)
    elif play_type == PLAY_CRS:
        return determine_crs_result(home_score, away_score)
    elif play_type == PLAY_TTG:
        return determine_ttg_result(home_score, away_score)
    elif play_type == PLAY_HAFU:
        return determine_hafu_result(home_score, away_score)
    return None


# ─── 最高奖金计算 ──────────────────────────────────────────
def calc_max_prize(matches: list, multiplier: int, combos: int) -> int:
    """
    计算理论最高奖金（分）
    matches: 每场 {play_type, selections, odds_map}
    odds_map: {selection_key: odds_fen}
    取每场最高赔率的选项连乘 × 2元 × 倍数
    考虑封顶规则
    """
    if not matches:
        return 0

    max_odds_product = 1.0  # 用float计算赔率乘积，最后再乘200×倍数
    for m in matches:
        odds_map = m.get("odds_map", {})
        if not odds_map:
            continue
        max_odds = max(odds_map.values()) / 100.0  # 分→元
        max_odds_product *= max_odds

    match_count = len(matches)
    max_prize = int(round(max_odds_product * UNIT_BET_FEN * multiplier))

    # 封顶
    cap = PRIZE_CAPS.get(match_count, PRIZE_CAP_6PLUS)
    return min(max_prize, cap)


def calc_stake(combos: int, multiplier: int) -> int:
    """计算总投入（分）= 组合数 × 每注2元 × 倍数"""
    return combos * UNIT_BET_FEN * multiplier


# ─── 结算逻辑 ──────────────────────────────────────────────
def settle_single_bet(bet: dict, score_map: dict) -> Optional[dict]:
    """
    结算一注投注单
    返回结算结果字典，若有比赛未结束则返回None

    结算规则（竞彩固定奖金）:
    - 枚举所有组合，全中才算中奖
    - 奖金 = 2元 × 命中组合赔率连乘 × 倍数
    - 总回报 = 所有命中组合的奖金之和
    - 单注奖金封顶
    """
    matches_data = json.loads(bet["matches_json"])
    match_count = len(matches_data)
    multiplier = bet["multiplier"]

    # 检查所有比赛是否有赛果
    match_results = []
    for m in matches_data:
        match_id = m.get("match_id") or str(m.get("matchNum", ""))
        scores = score_map.get(str(match_id))
        # 也尝试matchNumStr匹配
        if not scores and m.get("matchNumStr"):
            scores = score_map.get(m["matchNumStr"])
        if not scores:
            return None  # 比赛未结束

        play_type = m["play_type"]
        handicap = float(m.get("handicap", 0) or 0)
        actual = get_actual_result(play_type, scores["home_score"], scores["away_score"], handicap)

        match_results.append({
            "match_id": match_id,
            "matchNumStr": m.get("matchNumStr", ""),
            "home": m.get("home", ""),
            "away": m.get("away", ""),
            "play_type": play_type,
            "home_score": scores["home_score"],
            "away_score": scores["away_score"],
            "actual_result": actual,
            "selections": m.get("selections", []),
            "odds_map": m.get("odds_map", {}),
        })

    # 枚举所有组合
    from itertools import product

    # 每场构建选项列表 [(selection_key, odds_fen)]
    match_options = []
    for mr in match_results:
        options = []
        for sel in mr["selections"]:
            odds = mr["odds_map"].get(sel, 0)
            if odds > 0:
                options.append((sel, odds))
        if not options:
            return None  # 无有效选项，无法结算
        match_options.append(options)

    total_return_fen = 0
    winning_combos = []
    cap = PRIZE_CAPS.get(match_count, PRIZE_CAP_6PLUS)

    for combo in product(*match_options):
        all_hit = True
        odds_product = 1.0  # 元单位的赔率乘积
        combo_desc = []

        for i, (sel, odds_fen) in enumerate(combo):
            mr = match_results[i]
            if sel == mr["actual_result"]:
                odds_product *= odds_fen / 100.0
                combo_desc.append({"idx": i, "sel": sel, "hit": True, "odds": odds_fen})
            else:
                all_hit = False
                combo_desc.append({"idx": i, "sel": sel, "hit": False, "actual": mr["actual_result"]})
                break

        if all_hit:
            # 计算该组合奖金
            combo_prize = int(round(odds_product * UNIT_BET_FEN * multiplier))
            combo_prize = min(combo_prize, cap)  # 单注封顶
            total_return_fen += combo_prize
            winning_combos.append({
                "selections": [c["sel"] for c in combo_desc],
                "prize_fen": combo_prize,
            })

    total_stake = bet["total_stake_fen"]
    pnl_fen = total_return_fen - total_stake
    win = total_return_fen > 0

    result_detail = {
        "match_results": [
            {
                "match_id": mr["match_id"],
                "matchNumStr": mr["matchNumStr"],
                "score": f"{mr['home_score']}-{mr['away_score']}",
                "play_type": mr["play_type"],
                "actual": mr["actual_result"],
                "selections": mr["selections"],
            }
            for mr in match_results
        ],
        "winning_combos": winning_combos,
        "total_return_fen": total_return_fen,
        "total_stake_fen": total_stake,
        "pnl_fen": pnl_fen,
        "win": win,
    }

    return {
        "pnl_fen": pnl_fen,
        "total_return_fen": total_return_fen,
        "win": win,
        "detail": result_detail,
    }


# ─── 自动模拟单生成 ──────────────────────────────────────
def generate_auto_bets(db: BetSimDB, repo_dir: str, date_str: str,
                       config: dict) -> list:
    """
    基于V6.9预测自动生成模拟投注单
    规则：
    - 单选推荐场且单关开售：单关单注×5倍
    - 双选推荐场且单关开售：单关双注×5倍
    - 单选场非单关：组2串1（信心最高的两两组合）
    - 信心最高的3场单选场：额外组2串1（3个组合）

    返回生成的bet_id列表
    """
    odds_matches = load_sporttery_odds(repo_dir, date_str)
    if not odds_matches:
        print(f"  无赔率数据: {date_str}")
        return []

    predictions = load_locked_predictions(repo_dir, date_str)
    if not predictions:
        print(f"  无锁定预测: {date_str}")
        return []

    # 构建预测映射: match_id → prediction
    pred_map = {}
    pred_matches = predictions.get("matches", [])
    if isinstance(pred_matches, list):
        for pm in pred_matches:
            mid = pm.get("matchId") or pm.get("match_id") or pm.get("id")
            if mid:
                pred_map[str(mid)] = pm
            # 也用jcNum索引
            jcn = pm.get("jcNum") or pm.get("jc_num")
            if jcn:
                pred_map[str(jcn)] = pm
    elif isinstance(pred_matches, dict):
        for key, pm in pred_matches.items():
            pred_map[key] = pm

    # 筛选出有预测且有胜平负/让球赔率的竞彩场次
    candidate_matches = []
    for om in odds_matches:
        match_num = str(om.get("matchNum", ""))
        match_num_str = om.get("matchNumStr", "")
        match_id = str(om.get("matchId", ""))

        # 查找预测
        pred = pred_map.get(match_num) or pred_map.get(match_num_str) or pred_map.get(match_id)
        if not pred:
            continue

        # 只取胜平负和让球胜平负（V6.9策略覆盖这两个）
        had_odds = om["odds"].get("had")
        hhad_odds = om["odds"].get("hhad")
        pool_info = om.get("poolInfo", {})

        if not had_odds:
            continue

        # 单关标识
        had_single = pool_info.get("HAD", {}).get("bettingSingle", False)
        hhad_single = pool_info.get("HHAD", {}).get("bettingSingle", False)
        had_allup = pool_info.get("HAD", {}).get("bettingAllup", True)
        hhad_allup = pool_info.get("HHAD", {}).get("bettingAllup", True)

        # 提取预测方向
        prediction = pred.get("prediction") or pred.get("pick") or ""
        single_pick = pred.get("singlePick") or pred.get("single_pick") or ""
        hit_rate = pred.get("hitRate") or pred.get("hit_rate") or 0
        single_rate = pred.get("singleRate") or pred.get("single_rate") or 0
        conf_level = pred.get("confLevel") or pred.get("conf_level") or "low"
        sample_count = pred.get("sampleCount") or pred.get("sample_count") or 0

        # 信心评分（用于排序）
        confidence = 0.0
        if single_pick and single_rate:
            confidence = float(single_rate) / 100.0
        elif hit_rate:
            confidence = float(hit_rate) / 100.0 * 0.8

        # 解析选法
        # 双选: "胜平" "平负" "胜负"
        # 单选: "胜" "平" "负"
        def parse_selection(pred_str: str):
            """解析预测字符串为选项列表"""
            if not pred_str:
                return []
            pred_str = pred_str.strip()
            # 清理
            for c in ["(", ")", "（", "）", " ", "让球", "让"]:
                pred_str = pred_str.replace(c, "")
            sels = []
            for ch in pred_str:
                if ch == "胜":
                    sels.append("h")
                elif ch == "平":
                    sels.append("d")
                elif ch == "负":
                    sels.append("a")
            return sels

        double_sels = parse_selection(prediction)
        single_sel = parse_selection(single_pick)[:1] if single_pick else []

        # 让球盘预测
        handicap = 0
        if hhad_odds and hhad_odds.get("goalLine"):
            try:
                handicap = float(hhad_odds["goalLine"])
            except (ValueError, TypeError):
                pass

        candidate = {
            "matchNum": match_num,
            "matchNumStr": match_num_str,
            "matchId": match_id,
            "home": om.get("home", ""),
            "away": om.get("away", ""),
            "league": om.get("league", ""),
            "kickoff": om.get("kickoff", ""),
            "had_odds": had_odds,
            "hhad_odds": hhad_odds,
            "had_single": had_single,
            "hhad_single": hhad_single,
            "had_allup": had_allup,
            "hhad_allup": hhad_allup,
            "double_sels": double_sels,
            "single_sel": single_sel,
            "confidence": confidence,
            "hit_rate": hit_rate,
            "single_rate": single_rate,
            "conf_level": conf_level,
            "sample_count": sample_count,
            "handicap": handicap,
        }
        candidate_matches.append(candidate)

    if not candidate_matches:
        print(f"  无符合条件的场次")
        return []

    # 按信心排序
    candidate_matches.sort(key=lambda x: x["confidence"], reverse=True)
    print(f"  候选场次: {len(candidate_matches)}场 (按信心降序)")

    multiplier = config.get("multiplier", DEFAULT_MULTIPLIER)
    created_bets = []

    # ── 1. 单选单关 ──
    single_picks = [c for c in candidate_matches if c["single_sel"]]
    single_single_list = [c for c in single_picks if c["had_single"]]  # 单关可买的
    single_nonsingle_list = [c for c in single_picks if not c["had_single"]]  # 非单关的

    for c in single_single_list:
        odds_map = {c["single_sel"][0]: c["had_odds"][c["single_sel"][0]]}
        match_entry = {
            "match_id": c["matchNum"],
            "matchNumStr": c["matchNumStr"],
            "home": c["home"],
            "away": c["away"],
            "league": c["league"],
            "play_type": PLAY_HAD,
            "selections": c["single_sel"],
            "odds_map": odds_map,
            "handicap": 0,
            "confidence": c["confidence"],
        }
        combos = 1
        bet = {
            "bet_id": db.generate_bet_id("A"),
            "bet_date": date_str,
            "bet_type": "single",
            "parlay_type": PARLAY_SINGLE,
            "play_type": PLAY_HAD,
            "match_count": 1,
            "matches": [match_entry],
            "combos": combos,
            "multiplier": multiplier,
            "total_stake_fen": calc_stake(combos, multiplier),
            "max_prize_fen": calc_max_prize([match_entry], multiplier, combos),
            "source": "auto",
            "created_at": now_cst().isoformat(timespec="seconds"),
            "remark": f"自动模拟-单选单关 置信{c['confidence']:.0%}",
        }
        if db.insert_bet(bet):
            created_bets.append(bet["bet_id"])
            print(f"    单关单选: {c['matchNumStr']} {c['home']}vs{c['away']} → {c['single_sel'][0]} 信心{c['confidence']:.0%}")

    # ── 2. 双选单关 ──
    double_picks = [c for c in candidate_matches if len(c["double_sels"]) == 2]
    double_single_list = [c for c in double_picks if c["had_single"]]

    for c in double_single_list:
        odds_map = {s: c["had_odds"].get(s, 0) for s in c["double_sels"] if c["had_odds"].get(s, 0) > 0}
        if len(odds_map) < 2:
            continue
        match_entry = {
            "match_id": c["matchNum"],
            "matchNumStr": c["matchNumStr"],
            "home": c["home"],
            "away": c["away"],
            "league": c["league"],
            "play_type": PLAY_HAD,
            "selections": c["double_sels"],
            "odds_map": odds_map,
            "handicap": 0,
            "confidence": c["confidence"],
        }
        combos = 2
        bet = {
            "bet_id": db.generate_bet_id("A"),
            "bet_date": date_str,
            "bet_type": "single",
            "parlay_type": PARLAY_SINGLE,
            "play_type": PLAY_HAD,
            "match_count": 1,
            "matches": [match_entry],
            "combos": combos,
            "multiplier": multiplier,
            "total_stake_fen": calc_stake(combos, multiplier),
            "max_prize_fen": calc_max_prize([match_entry], multiplier, combos),
            "source": "auto",
            "created_at": now_cst().isoformat(timespec="seconds"),
            "remark": f"自动模拟-双选单关 命中率{c['hit_rate']}%",
        }
        if db.insert_bet(bet):
            created_bets.append(bet["bet_id"])
            print(f"    单关双选: {c['matchNumStr']} {c['home']}vs{c['away']} → {''.join(c['double_sels'])} 命中率{c['hit_rate']}%")

    # ── 3. 非单关单选场组2串1 ──
    # 信心高的前N场非单关单选场，两两组合
    parlay_candidates = []
    # 合并所有可串关的单选场（包括单关和非单关的，只要支持串关）
    for c in single_picks:
        if c["had_allup"] and c["had_odds"].get(c["single_sel"][0], 0) > 0:
            parlay_candidates.append(c)

    # 取信心最高的3场组2串1（3个组合）
    top3_parlay = parlay_candidates[:3]
    if len(top3_parlay) >= 2:
        for combo in combinations(top3_parlay, 2):
            match_entries = []
            for c in combo:
                odds_map = {c["single_sel"][0]: c["had_odds"][c["single_sel"][0]]}
                match_entries.append({
                    "match_id": c["matchNum"],
                    "matchNumStr": c["matchNumStr"],
                    "home": c["home"],
                    "away": c["away"],
                    "league": c["league"],
                    "play_type": PLAY_HAD,
                    "selections": c["single_sel"],
                    "odds_map": odds_map,
                    "handicap": 0,
                    "confidence": c["confidence"],
                })
            combos = 1
            bet = {
                "bet_id": db.generate_bet_id("A"),
                "bet_date": date_str,
                "bet_type": "parlay",
                "parlay_type": PARLAY_2,
                "play_type": PLAY_HAD,
                "match_count": 2,
                "matches": match_entries,
                "combos": combos,
                "multiplier": multiplier,
                "total_stake_fen": calc_stake(combos, multiplier),
                "max_prize_fen": calc_max_prize(match_entries, multiplier, combos),
                "source": "auto",
                "created_at": now_cst().isoformat(timespec="seconds"),
                "remark": f"自动模拟-2串1 高信心单选组合",
            }
            if db.insert_bet(bet):
                created_bets.append(bet["bet_id"])
                match_desc = "+".join(c["matchNumStr"] for c in combo)
                print(f"    2串1: {match_desc}")

    return created_bets


# ─── 统计计算 ──────────────────────────────────────────────
def compute_stats(db: BetSimDB) -> dict:
    """计算总体战绩统计"""
    settled = db.get_all_settled_bets()
    if not settled:
        return {
            "total_stake_fen": 0,
            "total_return_fen": 0,
            "pnl_fen": 0,
            "roi_pct": 0,
            "total_bets": 0,
            "win_bets": 0,
            "win_rate_pct": 0,
            "pending_count": len(db.get_pending_bets()),
        }

    total_stake = sum(b["total_stake_fen"] for b in settled)
    total_return = sum(b.get("total_return_fen") or 0 for b in settled)
    pnl = total_return - total_stake
    roi = (pnl / total_stake * 100) if total_stake > 0 else 0
    win_count = sum(1 for b in settled if b.get("win"))
    win_rate = (win_count / len(settled) * 100) if settled else 0

    return {
        "total_stake_fen": total_stake,
        "total_return_fen": total_return,
        "pnl_fen": pnl,
        "roi_pct": round(roi, 2),
        "total_bets": len(settled),
        "win_bets": win_count,
        "win_rate_pct": round(win_rate, 2),
        "pending_count": len(db.get_pending_bets()),
    }


def compute_group_stats(db: BetSimDB) -> list:
    """按玩法+串关分组统计"""
    groups = db.get_group_stats()
    result = []
    for g in groups:
        stake = g["total_stake"] or 0
        ret = g["total_return"] or 0
        pnl = g["pnl"] or 0
        roi = (pnl / stake * 100) if stake > 0 else 0
        win_rate = (g["win_count"] / g["bet_count"] * 100) if g["bet_count"] > 0 else 0
        result.append({
            "play_type": g["play_type"],
            "play_name": PLAY_NAMES.get(g["play_type"], g["play_type"]),
            "parlay_type": g["parlay_type"],
            "parlay_name": PARLAY_NAMES.get(g["parlay_type"], g["parlay_type"]),
            "bet_count": g["bet_count"],
            "win_count": g["win_count"],
            "win_rate_pct": round(win_rate, 2),
            "total_stake_fen": stake,
            "total_return_fen": ret,
            "pnl_fen": pnl,
            "roi_pct": round(roi, 2),
        })
    return result


def update_daily_stats(db: BetSimDB):
    """更新每日统计"""
    settled = db.get_all_settled_bets()
    daily = {}
    for b in settled:
        d = b["bet_date"]
        if d not in daily:
            daily[d] = {"stake": 0, "return": 0, "pnl": 0, "count": 0, "win": 0}
        daily[d]["stake"] += b["total_stake_fen"]
        daily[d]["return"] += b.get("total_return_fen") or 0
        daily[d]["pnl"] += b.get("pnl_fen") or 0
        daily[d]["count"] += 1
        if b.get("win"):
            daily[d]["win"] += 1

    now_str = now_cst().isoformat(timespec="seconds")
    for d, s in daily.items():
        db.update_daily_stats(d, s["stake"], s["return"], s["pnl"],
                              s["count"], s["win"], now_str)


# ─── 导出战绩JSON供前端 ────────────────────────────────────
def export_stats_json(db: BetSimDB, repo_dir: str):
    """导出战绩统计为JSON供前端读取"""
    overall = compute_stats(db)
    groups = compute_group_stats(db)
    daily = db.get_daily_stats(60)  # 近60天

    # 按日期正序
    daily_sorted = sorted(daily, key=lambda x: x["stat_date"])

    # 近30天盈亏曲线数据
    last_30 = daily_sorted[-30:] if len(daily_sorted) > 30 else daily_sorted

    # 累计盈亏曲线
    cumulative = []
    cum_pnl = 0
    for d in last_30:
        cum_pnl += d["pnl_fen"]
        cumulative.append({
            "date": d["stat_date"],
            "pnl_fen": d["pnl_fen"],
            "cumulative_pnl_fen": cum_pnl,
        })

    export_data = {
        "generated_at": now_cst().isoformat(timespec="seconds"),
        "overall": overall,
        "groups": groups,
        "daily": daily_sorted,
        "last_30_curve": cumulative,
    }

    out_dir = os.path.join(repo_dir, "data", "bet_sim")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "stats.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    # 同时导出投注单列表供前端展示
    bets_export = []
    all_bets = db.conn.execute(
        "SELECT bet_id, bet_date, bet_type, parlay_type, play_type, match_count, "
        "matches_json, combos, multiplier, total_stake_fen, max_prize_fen, "
        "source, status, created_at, settled_at, pnl_fen, total_return_fen, win, remark "
        "FROM bets ORDER BY created_at DESC LIMIT 200"
    ).fetchall()
    for b in all_bets:
        bd = dict(b)
        try:
            bd["matches"] = json.loads(bd["matches_json"])
        except Exception:
            bd["matches"] = []
        del bd["matches_json"]
        bets_export.append(bd)

    bets_path = os.path.join(out_dir, "bets.json")
    with open(bets_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": now_cst().isoformat(timespec="seconds"),
            "total": len(bets_export),
            "bets": bets_export,
        }, f, ensure_ascii=False, indent=2)

    return out_path, bets_path


# ─── 保存模拟单到 predictions/bets/ ─────────────────────
def save_bets_to_predictions(db: BetSimDB, repo_dir: str, date_str: str, bet_ids: list):
    """将当日生成的自动模拟单保存到predictions/bets/目录"""
    if not bet_ids:
        return

    bets_dir = os.path.join(repo_dir, "predictions", "bets")
    os.makedirs(bets_dir, exist_ok=True)

    bets_data = []
    for bid in bet_ids:
        row = db.conn.execute(
            "SELECT * FROM bets WHERE bet_id=?", (bid,)
        ).fetchone()
        if row:
            bd = dict(row)
            try:
                bd["matches"] = json.loads(bd["matches_json"])
            except Exception:
                bd["matches"] = []
            del bd["matches_json"]
            bets_data.append(bd)

    out_path = os.path.join(bets_dir, f"{date_str}.json")
    # 如果文件已存在，合并（去重）
    existing = []
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                old = json.load(f)
                if isinstance(old, list):
                    existing = old
                elif isinstance(old, dict):
                    existing = old.get("bets", [])
        except Exception:
            pass

    # 按bet_id去重
    existing_ids = {b.get("bet_id") for b in existing}
    for b in bets_data:
        if b["bet_id"] not in existing_ids:
            existing.append(b)

    output = {
        "generated_at": now_cst().isoformat(timespec="seconds"),
        "date": date_str,
        "source": "auto",
        "bet_count": len(existing),
        "bets": existing,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


# ─── 主流程 ─────────────────────────────────────────────────
async def main():
    result_mode = sys.argv[1] if len(sys.argv) > 1 else "display_only"
    repo_dir = sys.argv[2] if len(sys.argv) > 2 else "/Coze/Drive/私人助理小策/所有对话/主对话/fp-repo"
    mode = sys.argv[3] if len(sys.argv) > 3 else "auto"

    print(f"[参数] result_mode={result_mode}, repo_dir={repo_dir}, mode={mode}")
    sdk = CodeActSDK()

    try:
        # SQLite 状态库放 /tmp（挂载盘可能不支持SQLite的mmap I/O）
        db_path = "/tmp/bet_sim.db"
        db = BetSimDB(db_path)

        config = {
            "multiplier": 5,
        }

        today = today_str()
        generated = []
        settled_count = 0

        # ── 1. 生成自动模拟单 ──
        if mode in ("auto", "generate"):
            print("\n=== 生成自动模拟单 ===")
            # 尝试生成今天和昨天的（跨天场景）
            for d in [today, (now_cst() - timedelta(days=1)).strftime("%Y%m%d")]:
                day_bets = generate_auto_bets(db, repo_dir, d, config)
                if day_bets:
                    save_bets_to_predictions(db, repo_dir, d, day_bets)
                    generated.extend(day_bets)
            print(f"  共生成 {len(generated)} 注自动模拟单")

        # ── 2. 结算待结算投注单 ──
        if mode in ("auto", "settle"):
            print("\n=== 结算待结算投注单 ===")
            pending = db.get_pending_bets()
            print(f"  待结算: {len(pending)} 注")

            if pending:
                score_map = load_match_results(repo_dir)
                print(f"  可用赛果: {len(score_map)} 场")

                for bet in pending:
                    result = settle_single_bet(bet, score_map)
                    if result is not None:
                        db.settle_bet(
                            bet["bet_id"],
                            result["pnl_fen"],
                            result["total_return_fen"],
                            result["win"],
                            result["detail"],
                            now_cst().isoformat(timespec="seconds"),
                        )
                        settled_count += 1
                        pnl_yuan = result["pnl_fen"] / 100
                        print(f"    {bet['bet_id']}: {'赢' if result['win'] else '输'} {pnl_yuan:+.2f}元")

                print(f"  本次结算 {settled_count} 注")

        # ── 3. 更新每日统计并导出 ──
        if mode in ("auto", "settle", "stats"):
            print("\n=== 更新统计 ===")
            update_daily_stats(db)
            stats_path, bets_path = export_stats_json(db, repo_dir)
            print(f"  统计导出: {stats_path}")
            print(f"  投注单导出: {bets_path}")

        # ── 4. 计算汇总 ──
        overall = compute_stats(db)
        groups = compute_group_stats(db)

        db.close()

        # ── 5. 提交结果 ──
        actual_mode = result_mode if result_mode != "auto" else "display_only"

        stake_yuan = overall["total_stake_fen"] / 100
        ret_yuan = overall["total_return_fen"] / 100
        pnl_yuan = overall["pnl_fen"] / 100

        summary_lines = [
            "📊 竞彩模拟投注统计",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💰 累计投入: {stake_yuan:.2f}元",
            f"💵 累计回收: {ret_yuan:.2f}元",
            f"📈 累计盈亏: {'+' if pnl_yuan >= 0 else ''}{pnl_yuan:.2f}元 ({'+' if overall['roi_pct'] >= 0 else ''}{overall['roi_pct']:.2f}%)",
            f"🎯 胜率: {overall['win_rate_pct']:.1f}% ({overall['win_bets']}胜/{overall['total_bets']}注)",
            f"⏳ 待结算: {overall['pending_count']}注",
        ]

        if generated:
            summary_lines.append("")
            summary_lines.append(f"🆕 本次新增: {len(generated)}注自动模拟单")

        if settled_count:
            summary_lines.append("")
            summary_lines.append(f"✅ 本次结算: {settled_count}注")

        if groups:
            summary_lines.append("")
            summary_lines.append("📋 分组统计:")
            for g in groups[:8]:
                pnl_g = g["pnl_fen"] / 100
                summary_lines.append(
                    f"  {g['play_name']}-{g['parlay_name']}: {g['bet_count']}注 "
                    f"胜率{g['win_rate_pct']:.0f}% 盈亏{'+' if pnl_g >= 0 else ''}{pnl_g:.2f}元"
                )

        summary = "\n".join(summary_lines)
        print(f"\n{summary}")

        await sdk.submit_result(
            result_mode=actual_mode,
            status="success",
            message=summary,
            data={
                "overall": overall,
                "groups": groups,
                "generated_count": len(generated),
                "settled_count": settled_count,
                "pending_count": overall["pending_count"],
                "stats_path": os.path.join(repo_dir, "data", "bet_sim", "stats.json"),
            },
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        await sdk.submit_result(
            result_mode="notify",
            status="error",
            message=f"模拟投注执行失败: {e}",
            data={"error_type": type(e).__name__},
        )


if __name__ == "__main__":
    asyncio.run(main())
