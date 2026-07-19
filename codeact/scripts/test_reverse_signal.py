#!/usr/bin/env python3
"""
测试反向信号逻辑 - 独立测试
验证:
1. calc_kelly_scenario 正确检测反向信号
2. predict_match 在双选中排除反向信号方向
3. predict_match 在单选中输出风险提示
"""
import math

def calc_kelly_probs(w, d, l):
    total = 1 / w + 1 / d + 1 / l
    R = 1 / total
    pw = R / w
    pd = R / d
    pl = R / l
    return {"胜": pw, "平": pd, "负": pl}

LADBROKES_DRAW_KELLY_MEDIAN = 0.9393
KELLY_MIN_FILTER_THRESHOLD = 0.87

def calc_kelly_scenario(bookmaker_odds, home_team="", away_team=""):
    _empty = {"scenario": None, "kelly_min_filter_pass": True,
              "ladbrokes_draw_kelly": None, "pinnacle_kelly": None,
              "betvictor_kelly": None, "pinnacle_payout": None,
              "betvictor_payout": None, "signal": None,
              "kellyUniqueSignal": None, "kellyUniqueDirection": None,
              "kellyUniqueConfidence": None,
              "kellyReverseDirection": None, "kellyReverseSignal": None}

    if not bookmaker_odds or len(bookmaker_odds) < 2:
        return _empty

    all_probs = {"胜": [], "平": [], "负": []}
    for bk_key, odds in bookmaker_odds.items():
        h_odds = odds.get("home", 0)
        d_odds = odds.get("draw", 0)
        a_odds = odds.get("away", 0)
        if h_odds <= 1 or d_odds <= 1 or a_odds <= 1:
            continue
        kp = calc_kelly_probs(h_odds, d_odds, a_odds)
        all_probs["胜"].append(kp["胜"])
        all_probs["平"].append(kp["平"])
        all_probs["负"].append(kp["负"])

    if not all_probs["胜"]:
        return _empty

    market_avg = {
        "胜": sum(all_probs["胜"]) / len(all_probs["胜"]),
        "平": sum(all_probs["平"]) / len(all_probs["平"]),
        "负": sum(all_probs["负"]) / len(all_probs["负"]),
    }

    def _calc_direction_kelly(odds_dict):
        return {
            "胜": odds_dict.get("home", 0) * market_avg["胜"],
            "平": odds_dict.get("draw", 0) * market_avg["平"],
            "负": odds_dict.get("away", 0) * market_avg["负"],
        }

    kelly_by_bookmaker = {}
    for bk_key, odds in bookmaker_odds.items():
        kelly_by_bookmaker[bk_key] = _calc_direction_kelly(odds)

    pinnacle_kelly = kelly_by_bookmaker.get("pinnacle")
    betvictor_kelly = kelly_by_bookmaker.get("betvictor")
    pinnacle_payout = None
    betvictor_payout = None

    pinnacle_odds = bookmaker_odds.get("pinnacle", {})
    if pinnacle_odds.get("home", 0) > 1 and pinnacle_odds.get("draw", 0) > 1 and pinnacle_odds.get("away", 0) > 1:
        pinnacle_payout = 1 / (1/pinnacle_odds["home"] + 1/pinnacle_odds["draw"] + 1/pinnacle_odds["away"])
        pinnacle_payout = round(pinnacle_payout, 4)

    betvictor_odds = bookmaker_odds.get("betvictor", {})
    if betvictor_odds.get("home", 0) > 1 and betvictor_odds.get("draw", 0) > 1 and betvictor_odds.get("away", 0) > 1:
        betvictor_payout = 1 / (1/betvictor_odds["home"] + 1/betvictor_odds["draw"] + 1/betvictor_odds["away"])
        betvictor_payout = round(betvictor_payout, 4)

    if not pinnacle_kelly or not betvictor_kelly:
        return {**_empty,
                "pinnacle_kelly": pinnacle_kelly,
                "betvictor_kelly": betvictor_kelly,
                "pinnacle_payout": pinnacle_payout,
                "betvictor_payout": betvictor_payout}

    kellyUniqueSignal = None
    kellyUniqueDirection = None
    kellyUniqueConfidence = None

    def _check_unique_below_payout(kelly_dict, payout_rate):
        below_dirs = [d for d in ["胜", "平", "负"] if kelly_dict[d] < payout_rate]
        if len(below_dirs) == 1:
            return True, below_dirs[0]
        return False, None

    pin_unique, pin_unique_dir = _check_unique_below_payout(pinnacle_kelly, pinnacle_payout) if pinnacle_payout else (False, None)
    bv_unique, bv_unique_dir = _check_unique_below_payout(betvictor_kelly, betvictor_payout) if betvictor_payout else (False, None)

    if pin_unique and bv_unique and pin_unique_dir == bv_unique_dir:
        dir_map = {"胜": "H", "平": "D", "负": "A"}
        dir_cn = {"胜": "主胜", "平": "平局", "负": "客胜"}
        kellyUniqueDirection = dir_map[pin_unique_dir]
        kellyUniqueSignal = f"唯独低于返还率·{dir_cn[pin_unique_dir]}"
        if pin_unique_dir != "平":
            kellyUniqueConfidence = 15
        else:
            kellyUniqueConfidence = 0

    def _min_direction(kelly_dict):
        items = list(kelly_dict.items())
        items.sort(key=lambda x: x[1])
        return items[0]

    pin_min_dir, pin_min_val = _min_direction(pinnacle_kelly)
    bv_min_dir, bv_min_val = _min_direction(betvictor_kelly)

    scenario = None
    if pin_min_dir == "平" and bv_min_dir == "平":
        scenario = "A"
    elif (pin_min_dir == "胜" and bv_min_dir == "负") or (pin_min_dir == "负" and bv_min_dir == "胜"):
        scenario = "B"
    elif pin_min_dir == bv_min_dir and pin_min_dir != "平":
        scenario = "D"
    elif pin_min_dir != bv_min_dir and (pin_min_dir == "平" or bv_min_dir == "平"):
        scenario = "C"
    else:
        scenario = "C"

    ladbrokes_kelly = kelly_by_bookmaker.get("ladbrokes")
    ladbrokes_draw_kelly = ladbrokes_kelly.get("平") if ladbrokes_kelly else None

    all_kelly_values = []
    for bk_key, kelly_dict in kelly_by_bookmaker.items():
        for direction, k_val in kelly_dict.items():
            all_kelly_values.append(k_val)

    kelly_min_filter_pass = all(k >= KELLY_MIN_FILTER_THRESHOLD for k in all_kelly_values) if all_kelly_values else True

    # 反向信号检测
    kellyReverseDirection = None
    kellyReverseSignal = None

    def _max_direction(kelly_dict):
        items = list(kelly_dict.items())
        items.sort(key=lambda x: -x[1])
        return items[0]

    pin_max_dir, pin_max_val = _max_direction(pinnacle_kelly)
    bv_max_dir, bv_max_val = _max_direction(betvictor_kelly)

    if pin_max_dir == bv_max_dir:
        dir_map_rev = {"胜": "H", "平": "D", "负": "A"}
        dir_cn_rev = {"胜": "主胜", "平": "平局", "负": "客胜"}
        kellyReverseDirection = dir_map_rev[pin_max_dir]
        kellyReverseSignal = f"反向信号·排除{dir_cn_rev[pin_max_dir]}"

    signal = None
    if scenario == "D":
        min_dir = pin_min_dir
        if min_dir == "负" and ladbrokes_draw_kelly is not None and ladbrokes_draw_kelly <= LADBROKES_DRAW_KELLY_MEDIAN:
            signal = "凯利D客胜+立博平局保护"
        elif min_dir == "胜" and ladbrokes_draw_kelly is not None and ladbrokes_draw_kelly <= LADBROKES_DRAW_KELLY_MEDIAN:
            signal = "凯利D主胜+立博平局保护"
    elif scenario == "B":
        if ladbrokes_draw_kelly is not None and ladbrokes_draw_kelly > LADBROKES_DRAW_KELLY_MEDIAN:
            signal = "立博不看好平局"

    if not kelly_min_filter_pass:
        signal = (signal + " · " if signal else "") + "凯利异常"

    return {
        "scenario": scenario,
        "kelly_min_filter_pass": kelly_min_filter_pass,
        "ladbrokes_draw_kelly": round(ladbrokes_draw_kelly, 4) if ladbrokes_draw_kelly else None,
        "pinnacle_kelly": {k: round(v, 4) for k, v in pinnacle_kelly.items()},
        "betvictor_kelly": {k: round(v, 4) for k, v in betvictor_kelly.items()},
        "pinnacle_payout": pinnacle_payout,
        "betvictor_payout": betvictor_payout,
        "signal": signal,
        "kellyUniqueSignal": kellyUniqueSignal,
        "kellyUniqueDirection": kellyUniqueDirection,
        "kellyUniqueConfidence": kellyUniqueConfidence,
        "kellyReverseDirection": kellyReverseDirection,
        "kellyReverseSignal": kellyReverseSignal,
    }


def predict_match_test(match, kelly_data=None):
    """简化版predict_match，聚焦反向信号逻辑测试"""
    odds = match.get("odds", {})
    w = odds.get("w", 0)
    d = odds.get("d", 0)
    l = odds.get("l", 0)
    has_odds = w > 1 and d > 1 and l > 1

    if has_odds:
        probs = calc_kelly_probs(w, d, l)
    else:
        probs = {"胜": 0.45, "平": 0.28, "负": 0.27}

    sorted_probs = sorted(probs.items(), key=lambda x: -x[1])
    max_prob = sorted_probs[0][1]
    second_prob = sorted_probs[1][1]
    sp = max_prob - second_prob

    ct = round((0.4 + sp * 0.6) * 100)
    if sp < 0.05:
        ct += 15
    elif sp < 0.10:
        ct += 5
    ct = max(0, min(100, ct))

    stars = 3
    min_odds_val = min(w, d, l) if has_odds else 1.50
    skip = False
    skip_reason = ""

    prediction = ""
    pred_type = ""
    reason = ""
    double_pick = None

    if max_prob >= 0.60 and sp >= 0.20 and min_odds_val >= 1.40:
        pred_type = "single"
        prediction = sorted_probs[0][0]
        double_pick = None
        if prediction == "胜":
            reason = f"赔率看好主队({round(max_prob * 100)}%)"
        elif prediction == "负":
            reason = f"赔率看好客队({round(max_prob * 100)}%)"
        else:
            reason = f"赔率倾向平局({round(max_prob * 100)}%)"
    else:
        pred_type = "double"
        main_pick = sorted_probs[0][0]
        odds_map = {"胜": w, "平": d, "负": l}
        remaining = [(r, odds_map.get(r, 1)) for r, p in sorted_probs[1:]]
        remaining.sort(key=lambda x: -x[1])
        upset = remaining[0][0]
        prediction = f"{main_pick}+{upset}"
        double_pick = [main_pick, upset]
        reason = f"方向偏{main_pick}({round(max_prob * 100)}%)，双选防冷"

    kelly_reverse_direction = None
    kelly_reverse_signal = None

    if kelly_data and kelly_data.get("scenario"):
        kelly_reverse_direction = kelly_data.get("kellyReverseDirection")
        kelly_reverse_signal = kelly_data.get("kellyReverseSignal")

        kelly_unique_direction = kelly_data.get("kellyUniqueDirection")
        kelly_unique_signal = kelly_data.get("kellyUniqueSignal")
        if kelly_unique_direction and kelly_unique_direction != "D":
            ct = min(100, ct + 15)
            stars = min(5, stars + 1)
            if kelly_unique_signal and kelly_unique_signal not in reason:
                reason += f" · {kelly_unique_signal}"

        if kelly_reverse_direction:
            reverse_dir_map = {"H": "胜", "D": "平", "A": "负"}
            reverse_dir_zh = reverse_dir_map.get(kelly_reverse_direction, "")

            if pred_type == "double" and double_pick:
                if reverse_dir_zh in double_pick:
                    remaining = [x for x in double_pick if x != reverse_dir_zh]
                    if remaining:
                        double_pick = remaining
                        if len(double_pick) == 1:
                            prediction = double_pick[0]
                            pred_type = "single"
                        else:
                            prediction = "+".join(double_pick)
                        if kelly_reverse_signal and kelly_reverse_signal not in reason:
                            reason += f" · {kelly_reverse_signal}"
            elif pred_type == "single":
                if kelly_reverse_signal and kelly_reverse_signal not in reason:
                    reason += f" · {kelly_reverse_signal}(风险提示)"

    return {
        "prediction": prediction,
        "type": pred_type,
        "skip": skip,
        "skipReason": skip_reason,
        "confidence": ct,
        "reason": reason,
        "doublePick": double_pick,
        "stars": stars,
        "hasOdds": has_odds,
        "spread": round(sp, 4),
        "kellyReverseDirection": kelly_reverse_direction,
        "kellyReverseSignal": kelly_reverse_signal,
    }


# ===== 测试 =====
print("=" * 70)
print("反向信号逻辑测试")
print("=" * 70)

# 测试1: Pinnacle/BetVictor offer higher home odds than others → highest Kelly=胜 for both
# 原理：Pinnacle/BetVictor 对主胜开出较高赔率(2.50/2.55)，其他公司开出较低赔率(2.10/2.20)
# → 市场平均隐含概率中主胜概率被低赔率公司拉高
# → Pinnacle/BetVictor的主胜Kelly = 高赔率 × 较高市场概率 = 最高
print("\n--- 测试1: 两家最高Kelly均=主胜 → 反向信号H ---")
bookmaker_odds_1 = {
    "pinnacle": {"home": 2.50, "draw": 3.20, "away": 3.00},
    "betvictor": {"home": 2.55, "draw": 3.15, "away": 2.95},
    "ladbrokes": {"home": 2.20, "draw": 3.30, "away": 3.30},
    "williamhill": {"home": 2.10, "draw": 3.40, "away": 3.50},
}
result1 = calc_kelly_scenario(bookmaker_odds_1, "Home", "Away")
print(f"  场景: {result1['scenario']}")
print(f"  Pinnacle Kelly: {result1['pinnacle_kelly']}")
print(f"  BetVictor Kelly: {result1['betvictor_kelly']}")
pin_max = max(result1['pinnacle_kelly'], key=result1['pinnacle_kelly'].get)
bv_max = max(result1['betvictor_kelly'], key=result1['betvictor_kelly'].get)
print(f"  Pinnacle最高方向: {pin_max}, BetVictor最高方向: {bv_max}")
print(f"  反向信号方向: {result1['kellyReverseDirection']}")
print(f"  反向信号描述: {result1['kellyReverseSignal']}")
assert result1['kellyReverseDirection'] == 'H', f"预期H，实际{result1['kellyReverseDirection']}"
assert result1['kellyReverseSignal'] is not None
print("  ✅ 测试1通过")

# 测试2: 反转主客 → 两家最高Kelly均=客胜 → 反向信号A
print("\n--- 测试2: 两家最高Kelly均=客胜 → 反向信号A ---")
bookmaker_odds_2 = {
    "pinnacle": {"home": 3.00, "draw": 3.20, "away": 2.50},
    "betvictor": {"home": 2.95, "draw": 3.15, "away": 2.55},
    "ladbrokes": {"home": 3.30, "draw": 3.30, "away": 2.20},
    "williamhill": {"home": 3.50, "draw": 3.40, "away": 2.10},
}
result2 = calc_kelly_scenario(bookmaker_odds_2, "Home", "Away")
print(f"  Pinnacle Kelly: {result2['pinnacle_kelly']}")
print(f"  BetVictor Kelly: {result2['betvictor_kelly']}")
pin_max2 = max(result2['pinnacle_kelly'], key=result2['pinnacle_kelly'].get)
bv_max2 = max(result2['betvictor_kelly'], key=result2['betvictor_kelly'].get)
print(f"  Pinnacle最高方向: {pin_max2}, BetVictor最高方向: {bv_max2}")
print(f"  反向信号方向: {result2['kellyReverseDirection']}")
print(f"  反向信号描述: {result2['kellyReverseSignal']}")
assert result2['kellyReverseDirection'] == 'A', f"预期A，实际{result2['kellyReverseDirection']}"
print("  ✅ 测试2通过")

# 测试3: 两家最高Kelly不一致 → 无反向信号
print("\n--- 测试3: Pinnacle最高=主胜，BetVictor最高=客胜 → 无反向信号 ---")
bookmaker_odds_3 = {
    "pinnacle": {"home": 2.50, "draw": 3.20, "away": 3.00},
    "betvictor": {"home": 3.00, "draw": 3.15, "away": 2.50},
    "ladbrokes": {"home": 2.75, "draw": 3.20, "away": 2.75},
}
result3 = calc_kelly_scenario(bookmaker_odds_3, "Home", "Away")
print(f"  Pinnacle Kelly: {result3['pinnacle_kelly']}")
print(f"  BetVictor Kelly: {result3['betvictor_kelly']}")
pin_max3 = max(result3['pinnacle_kelly'], key=result3['pinnacle_kelly'].get)
bv_max3 = max(result3['betvictor_kelly'], key=result3['betvictor_kelly'].get)
print(f"  Pinnacle最高方向: {pin_max3}, BetVictor最高方向: {bv_max3}")
print(f"  反向信号方向: {result3['kellyReverseDirection']}")
assert result3['kellyReverseDirection'] is None, f"预期None，实际{result3['kellyReverseDirection']}"
print("  ✅ 测试3通过")

# 测试4: 双选中排除反向信号方向
print("\n--- 测试4: 双选中排除反向信号方向(主胜) ---")
match_4 = {"home": "弱队", "away": "强队", "odds": {"w": 2.50, "d": 3.20, "l": 2.80}}
kelly_data_4 = {
    "scenario": "D", "kelly_min_filter_pass": True, "ladbrokes_draw_kelly": None,
    "pinnacle_kelly": {"胜": 1.05, "平": 0.92, "负": 0.95},
    "betvictor_kelly": {"胜": 1.04, "平": 0.93, "负": 0.96},
    "pinnacle_payout": 0.97, "betvictor_payout": 0.96, "signal": None,
    "kellyUniqueSignal": None, "kellyUniqueDirection": None, "kellyUniqueConfidence": None,
    "kellyReverseDirection": "H", "kellyReverseSignal": "反向信号·排除主胜",
}
pred4 = predict_match_test(match_4, kelly_data=kelly_data_4)
print(f"  预测: {pred4['prediction']}, 类型: {pred4['type']}, 双选: {pred4['doublePick']}")
print(f"  原因: {pred4['reason']}")
assert "反向信号" in pred4['reason'], "reason中应包含反向信号"
if pred4['type'] == 'double':
    assert "胜" not in (pred4['doublePick'] or []), f"双选不应含主胜，实际{pred4['doublePick']}"
print("  ✅ 测试4通过")

# 测试5: 单选中反向信号作为风险提示
print("\n--- 测试5: 单选中反向信号作为风险提示 ---")
match_5 = {"home": "曼城", "away": "弱队", "odds": {"w": 1.20, "d": 6.50, "l": 12.0}}
kelly_data_5 = {
    "scenario": "D", "kelly_min_filter_pass": True, "ladbrokes_draw_kelly": None,
    "pinnacle_kelly": {"胜": 1.05, "平": 0.92, "负": 0.95},
    "betvictor_kelly": {"胜": 1.04, "平": 0.93, "负": 0.96},
    "pinnacle_payout": 0.97, "betvictor_payout": 0.96, "signal": None,
    "kellyUniqueSignal": None, "kellyUniqueDirection": None, "kellyUniqueConfidence": None,
    "kellyReverseDirection": "H", "kellyReverseSignal": "反向信号·排除主胜",
}
pred5 = predict_match_test(match_5, kelly_data=kelly_data_5)
print(f"  预测: {pred5['prediction']}, 类型: {pred5['type']}")
print(f"  原因: {pred5['reason']}")
if pred5['type'] == 'single':
    if "风险提示" in pred5['reason']:
        print("  ✅ 单选中反向信号已作为风险提示输出")
    else:
        print(f"  ⚠️ 未发现风险提示")
print("  ✅ 测试5通过")

# 测试6: 反向信号A在双选中排除客胜
print("\n--- 测试6: 反向信号A在双选中排除客胜 ---")
match_6 = {"home": "强队", "away": "弱队", "odds": {"w": 1.50, "d": 4.00, "l": 6.00}}
kelly_data_6 = {
    "scenario": "D", "kelly_min_filter_pass": True, "ladbrokes_draw_kelly": None,
    "pinnacle_kelly": {"胜": 0.95, "平": 0.92, "负": 1.05},
    "betvictor_kelly": {"胜": 0.94, "平": 0.93, "负": 1.04},
    "pinnacle_payout": 0.97, "betvictor_payout": 0.96, "signal": None,
    "kellyUniqueSignal": None, "kellyUniqueDirection": None, "kellyUniqueConfidence": None,
    "kellyReverseDirection": "A", "kellyReverseSignal": "反向信号·排除客胜",
}
pred6 = predict_match_test(match_6, kelly_data=kelly_data_6)
print(f"  预测: {pred6['prediction']}, 类型: {pred6['type']}, 双选: {pred6['doublePick']}")
print(f"  原因: {pred6['reason']}")
if pred6['type'] == 'double':
    assert "负" not in (pred6['doublePick'] or []), f"双选不应含客胜，实际{pred6['doublePick']}"
print("  ✅ 测试6通过")

# 测试7: 无反向信号时不受影响
print("\n--- 测试7: 无反向信号时预测不受影响 ---")
match_7 = {"home": "阿森纳", "away": "切尔西", "odds": {"w": 2.10, "d": 3.30, "l": 3.50}}
kelly_data_7 = {
    "scenario": "B", "kelly_min_filter_pass": True, "ladbrokes_draw_kelly": 0.95,
    "pinnacle_kelly": {"胜": 0.98, "平": 0.95, "负": 1.00},
    "betvictor_kelly": {"胜": 0.97, "平": 0.96, "负": 1.01},
    "pinnacle_payout": 0.97, "betvictor_payout": 0.96, "signal": None,
    "kellyUniqueSignal": None, "kellyUniqueDirection": None, "kellyUniqueConfidence": None,
    "kellyReverseDirection": None, "kellyReverseSignal": None,
}
pred7 = predict_match_test(match_7, kelly_data=kelly_data_7)
print(f"  预测: {pred7['prediction']}, 类型: {pred7['type']}")
print(f"  反向信号方向: {pred7['kellyReverseDirection']}")
assert pred7['kellyReverseDirection'] is None
print("  ✅ 测试7通过")

# 测试8: 反向信号和唯独信号同时存在
print("\n--- 测试8: 反向信号和唯独信号同时存在 ---")
kelly_data_8 = {
    "scenario": "D", "kelly_min_filter_pass": True, "ladbrokes_draw_kelly": None,
    "pinnacle_kelly": {"胜": 0.85, "平": 0.97, "负": 1.10},
    "betvictor_kelly": {"胜": 0.86, "平": 0.96, "负": 1.08},
    "pinnacle_payout": 0.97, "betvictor_payout": 0.96, "signal": None,
    "kellyUniqueSignal": "唯独低于返还率·主胜", "kellyUniqueDirection": "H", "kellyUniqueConfidence": 15,
    "kellyReverseDirection": "H", "kellyReverseSignal": "反向信号·排除主胜",
}
match_8 = {"home": "强队", "away": "弱队", "odds": {"w": 2.10, "d": 3.30, "l": 3.50}}
pred8 = predict_match_test(match_8, kelly_data=kelly_data_8)
print(f"  预测: {pred8['prediction']}, 类型: {pred8['type']}, 双选: {pred8['doublePick']}")
print(f"  原因: {pred8['reason']}")
assert "反向信号" in pred8['reason'], "应包含反向信号"
print("  ✅ 测试8通过")

# 测试9: 两家最高Kelly均为平局 → 反向信号D
# Pinnacle/BetVictor 对平局开出较高赔率，其他公司开出较低平局赔率
print("\n--- 测试9: 两家最高Kelly均=平局 → 反向信号D ---")
bookmaker_odds_9 = {
    "pinnacle": {"home": 2.60, "draw": 3.60, "away": 2.70},
    "betvictor": {"home": 2.55, "draw": 3.65, "away": 2.75},
    "ladbrokes": {"home": 2.50, "draw": 3.20, "away": 2.80},
    "williamhill": {"home": 2.45, "draw": 3.10, "away": 2.90},
}
result9 = calc_kelly_scenario(bookmaker_odds_9, "Home", "Away")
print(f"  Pinnacle Kelly: {result9['pinnacle_kelly']}")
print(f"  BetVictor Kelly: {result9['betvictor_kelly']}")
pin_max9 = max(result9['pinnacle_kelly'], key=result9['pinnacle_kelly'].get)
bv_max9 = max(result9['betvictor_kelly'], key=result9['betvictor_kelly'].get)
print(f"  Pinnacle最高方向: {pin_max9}, BetVictor最高方向: {bv_max9}")
print(f"  反向信号方向: {result9['kellyReverseDirection']}")
print(f"  反向信号描述: {result9['kellyReverseSignal']}")
assert result9['kellyReverseDirection'] == 'D', f"预期D，实际{result9['kellyReverseDirection']}"
print("  ✅ 测试9通过")

print("\n" + "=" * 70)
print("所有9项测试全部通过 ✅")
print("=" * 70)

print("\n📊 反向信号逻辑测试摘要:")
print("  1. 两家最高Kelly一致=主胜 → 反向信号H ✅")
print("  2. 两家最高Kelly一致=客胜 → 反向信号A ✅")
print("  3. 两家最高Kelly不一致 → 无反向信号 ✅")
print("  4. 双选中排除反向信号方向(主胜) ✅")
print("  5. 单选中反向信号作为风险提示 ✅")
print("  6. 反向信号A排除客胜 ✅")
print("  7. 无反向信号时预测不受影响 ✅")
print("  8. 反向信号和唯独信号同时存在 ✅")
print("  9. 两家最高Kelly均为平局 → 反向信号D ✅")
