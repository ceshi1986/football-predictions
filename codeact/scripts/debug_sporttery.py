#!/usr/bin/env python3
"""调试竞彩网 codeact_fetch_web 返回内容"""
import asyncio
import json
from codeact_sdk import CodeActSDK

TOOL_SCHEMA_VERSIONS = {
    "codeact_fetch_web": "v1_2c8d0580b3f93a58",
}

async def main():
    sdk = CodeActSDK()
    # SDK auto-initializes via IPC
    
    # 测试页面 URL
    page_url = "https://www.sporttery.cn/jc/jsq/zqspf/"
    print(f"Fetching: {page_url}")
    
    fetch_result = await sdk.call_tool(
        "codeact_fetch_web",
        {"url": page_url},
        schema_version=TOOL_SCHEMA_VERSIONS["codeact_fetch_web"],
    )
    
    print(f"is_success: {fetch_result.get('is_success')}")
    print(f"keys: {list(fetch_result.keys())}")
    
    content = fetch_result.get("content", "")
    print(f"\ncontent length: {len(content)}")
    print(f"\n--- First 2000 chars of content ---")
    print(content[:2000])
    print(f"\n--- Last 500 chars ---")
    print(content[-500:] if len(content) > 500 else content)
    
    # 检查是否包含 VS
    vs_count = content.count("VS")
    print(f"\nVS occurrences: {vs_count}")
    
    # 检查赔率数字
    import re
    odds_matches = re.findall(r'\d+\.\d{2}', content)
    print(f"Odds-like numbers found: {len(odds_matches)}")
    if odds_matches:
        print(f"First 20: {odds_matches[:20]}")
    
    # 测试 API URL
    api_url = "https://i.sporttery.cn/odds_calculator/get_odds?i_format=json&poolcode[]=had&poolcode[]=hhad"
    print(f"\n\nFetching API: {api_url}")
    
    api_result = await sdk.call_tool(
        "codeact_fetch_web",
        {"url": api_url},
        schema_version=TOOL_SCHEMA_VERSIONS["codeact_fetch_web"],
    )
    
    print(f"is_success: {api_result.get('is_success')}")
    api_content = api_result.get("content", "")
    print(f"content length: {len(api_content)}")
    print(f"\n--- First 2000 chars ---")
    print(api_content[:2000])
    
    await sdk.submit_result(
        message="Debug complete",
        result_mode="display_only",
        status="success",
    )

if __name__ == "__main__":
    asyncio.run(main())
