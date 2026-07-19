#!/usr/bin/env python3
"""测试修复后的竞彩网解析逻辑 v2"""
import asyncio
import json
import re as _re
from codeact_sdk import CodeActSDK

TOOL_SCHEMA_VERSIONS = {
    "codeact_fetch_web": "v1_2c8d0580b3f93a58",
}

def _normalize_name(name: str) -> str:
    """简单标准化名称"""
    return name.strip().lower().replace(" ", "")

def _parse_sporttery_content_v2(content: str) -> dict:
    """修复后的解析函数 v2 - 按表格行解析"""
    if not content:
        return {}
    
    # Step 1: 解析 JSON
    actual_content = content
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            actual_content = data.get("data", {}).get("content", "")
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    
    if not actual_content:
        return {}
    
    # Step 2: 清理 HTML/Markdown 标记
    text = _re.sub(r'<br\s*/?>', ' ', actual_content)
    text = _re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    # 竞彩网嵌套括号链接格式
    text = _re.sub(r'\]\([^)]*\)', ']', text)
    text = _re.sub(r'\[\[[^\]]*\]([^\[\]]*)\]', r'\1', text)
    text = _re.sub(r'\[([^\[\]]*)\[[^\]]*\]\]', r'\1', text)
    text = _re.sub(r'\[[^\]]*\]', '', text)
    
    # Debug: show processed text around VS
    vs_count = text.count('VS')
    print(f"  VS occurrences in processed text: {vs_count}")
    
    # Debug: show the first 3000 chars of processed text
    print(f"\n--- Processed text (first 3000 chars) ---")
    print(text[:3000])
    print(f"\n--- End processed text ---\n")
    
    # Step 3: 按表格行解析
    results = {}
    lines = text.split('\n')
    
    for li, line in enumerate(lines):
        line = line.strip()
        if 'VS' not in line:
            continue
        if '主队' in line and '客队' in line:
            continue
        
        # 用 | 分割列
        cols = [c.strip() for c in line.split('|')]
        cols = [c for c in cols if c]
        
        if len(cols) < 6:
            continue
        
        # 查找包含 VS 的列
        vs_col_idx = -1
        for i, c in enumerate(cols):
            if 'VS' in c:
                vs_col_idx = i
                break
        
        if vs_col_idx < 0:
            continue
        
        # 提取队名
        vs_text = cols[vs_col_idx]
        vs_parts = vs_text.split('VS')
        if len(vs_parts) != 2:
            continue
        
        home_cn = vs_parts[0].strip()
        away_cn = vs_parts[1].strip()
        home_cn = _re.sub(r'^[\d\s%]+', '', home_cn).strip()
        away_cn = _re.sub(r'[\d\s%]+$', '', away_cn).strip()
        
        if not home_cn or not away_cn:
            continue
        
        # 查找赔率
        odds_text = ""
        for i in range(vs_col_idx + 1, min(len(cols), vs_col_idx + 4)):
            odds_text += " " + cols[i]
        
        all_odds = _re.findall(r'\d+\.\d{2}', odds_text)
        if len(all_odds) < 6:
            # Fallback: 从 VS 后面提取
            vs_pos_in_line = line.find('VS')
            if vs_pos_in_line >= 0:
                after_vs_text = line[vs_pos_in_line:]
                all_odds_after = _re.findall(r'\d+\.\d{2}', after_vs_text)
                if len(all_odds_after) >= 6:
                    all_odds = all_odds_after
        
        if len(all_odds) < 6:
            print(f"  [SKIP] Line {li}: {home_cn} vs {away_cn} - not enough odds ({len(all_odds)})")
            continue
        
        try:
            std_w = float(all_odds[0])
            std_d = float(all_odds[1])
            std_l = float(all_odds[2])
            hcp_w = float(all_odds[3])
            hcp_d = float(all_odds[4])
            hcp_l = float(all_odds[5])
        except (ValueError, IndexError):
            continue
        
        if std_w <= 1.0 or std_d <= 1.0 or std_l <= 1.0:
            print(f"  [SKIP] {home_cn} vs {away_cn}: invalid odds {std_w}/{std_d}/{std_l}")
            continue
        
        # 让球数
        handicap = ""
        for i in range(vs_col_idx + 1, min(len(cols), vs_col_idx + 3)):
            hcp_match = _re.search(r'([+-]?\d+)', cols[i])
            if hcp_match and abs(int(hcp_match.group(1))) <= 5:
                handicap = hcp_match.group(1)
                break
        
        key = (_normalize_name(home_cn), _normalize_name(away_cn))
        results[key] = {
            "w": std_w, "d": std_d, "l": std_l,
            "hcp_w": hcp_w, "hcp_d": hcp_d, "hcp_l": hcp_l,
            "handicap": handicap,
            "home_cn": home_cn,
            "away_cn": away_cn,
        }
        print(f"  [OK] {home_cn} vs {away_cn}: {std_w:.2f}/{std_d:.2f}/{std_l:.2f} (让{handicap})")
    
    return results

async def main():
    sdk = CodeActSDK()
    
    page_url = "https://www.sporttery.cn/jc/jsq/zqspf/"
    print(f"Fetching: {page_url}")
    
    fetch_result = await sdk.call_tool(
        "codeact_fetch_web",
        {"url": page_url},
        schema_version=TOOL_SCHEMA_VERSIONS["codeact_fetch_web"],
    )
    
    content = fetch_result.get("content", "")
    print(f"Content length: {len(content)}")
    
    results = _parse_sporttery_content_v2(content)
    print(f"\n解析结果: {len(results)} 场比赛\n")
    
    for key, odds in results.items():
        print(f"  {odds['home_cn']} vs {odds['away_cn']}")
        print(f"    标准赔率: 胜{odds['w']:.2f} 平{odds['d']:.2f} 负{odds['l']:.2f}")
        print(f"    让球({odds['handicap']}): 胜{odds['hcp_w']:.2f} 平{odds['hcp_d']:.2f} 负{odds['hcp_l']:.2f}")
    
    # 检查芬超雅罗
    yaro_key = (_normalize_name("雅罗"), _normalize_name("国际图尔"))
    if yaro_key in results:
        print(f"\n✅ 芬超 雅罗 vs 国际图尔 有赔率！")
        print(f"  {results[yaro_key]}")
    else:
        print(f"\n❌ 芬超 雅罗 vs 国际图尔 无赔率")
        print(f"  所有key: {list(results.keys())}")
    
    await sdk.submit_result(
        message=f"解析v2: {len(results)}场比赛",
        result_mode="display_only",
        status="success",
    )

if __name__ == "__main__":
    asyncio.run(main())
