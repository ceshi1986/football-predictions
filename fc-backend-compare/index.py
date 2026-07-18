# -*- coding: utf-8 -*-
"""
FC Backend - /compare-bets endpoint
Football Predictions - 竞彩截图比对功能后端

部署说明：
1. 将此代码部署到阿里云函数计算（FC），Python 3.10 运行时
2. 入口：index.handler
3. 环境变量需配置：DASHSCOPE_API_KEY（DashScope API Key）
4. 此文件可独立部署，也可合并到现有 FC index.py 中（将 compare_bets_handler 函数和路由添加到现有代码）
"""

import json
import os
import base64
import requests
from datetime import datetime

FC_URL = "https://metaphyai-api-v-cwpuwzgtdx.cn-shanghai.fcapp.run"
DASHSCOPE_API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

# 比对图片分析的 Prompt
COMPARE_SYSTEM_PROMPT = """你是一个专业的竞彩足球截图识别助手。请仔细分析用户上传的图片，提取其中的竞彩投注信息。

你需要识别以下格式的图片：
1. sporttery.cn 计算器弹窗格式：显示"周X+数字 主队 VS 客队"和赔率选项（如"胜(1.93)、平(3.40)"）
2. 模拟试玩已选列表格式：显示"周X+数字 主队 VS 客队 [玩法] 选项 赔率"
3. 比赛详情页格式：显示让球/非让球玩法，红色高亮选中项

请提取每场比赛的以下信息：
- matchId: 比赛编号（如"周五201"、"周六003"等）
- home: 主队名称
- away: 客队名称  
- selections: 用户选择的投注选项数组

选项值标准化规则：
- "胜"/"主胜"/"3" -> "胜"
- "平"/"平局"/"1" -> "平"  
- "负"/"主负"/"0" -> "负"
- "让胜"/"让球胜" -> "让胜"
- "让平"/"让球平" -> "让平"
- "让负"/"让球负" -> "让负"
- 如果是让球玩法，在选项前加"让"字标识，如 selections: ["让负"]
- 如果同时有让球和非让球选择，全部列出，如 ["胜", "让负"]

返回严格的JSON数组格式，不要包含其他内容：
[{"matchId": "周五201", "home": "哥德堡", "away": "布鲁马波", "selections": ["胜","平"]}]

如果无法识别任何比赛信息，返回空数组 []。"""


def call_dashscope_vl(image_base64: str) -> dict:
    """调用 DashScope qwen-vl-plus 视觉模型分析图片"""
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        return {"error": "DASHSCOPE_API_KEY not configured"}
    
    # 构建 multimodal message
    image_url = f"data:image/png;base64,{image_base64}"
    
    payload = {
        "model": "qwen-vl-plus",
        "input": {
            "messages": [
                {
                    "role": "system",
                    "content": [{"text": COMPARE_SYSTEM_PROMPT}]
                },
                {
                    "role": "user",
                    "content": [
                        {"image": image_url},
                        {"text": "请分析这张竞彩截图，提取比赛编号、队名和投注选择。"}
                    ]
                }
            ]
        },
        "parameters": {
            "result_format": "message"
        }
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        resp = requests.post(DASHSCOPE_API_URL, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        
        # 解析响应
        if "output" in result and "choices" in result["output"]:
            choices = result["output"]["choices"]
            if choices and len(choices) > 0:
                message = choices[0].get("message", {})
                content = message.get("content", [])
                # 提取文本内容
                text_content = ""
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        text_content += item["text"]
                    elif isinstance(item, str):
                        text_content += item
                
                # 尝试解析 JSON
                try:
                    text = text_content.strip()
                    # 尝试找到 JSON 数组部分
                    start_idx = text.find("[")
                    end_idx = text.rfind("]") + 1
                    if start_idx >= 0 and end_idx > start_idx:
                        json_str = text[start_idx:end_idx]
                        parsed = json.loads(json_str)
                        return {"success": True, "data": parsed}
                    else:
                        return {"success": False, "error": "No JSON array found in response", "raw": text_content}
                except json.JSONDecodeError as e:
                    return {"success": False, "error": f"JSON parse error: {str(e)}", "raw": text_content}
        
        return {"success": False, "error": "Unexpected response format", "raw": str(result)}
    
    except requests.exceptions.Timeout:
        return {"success": False, "error": "DashScope API timeout"}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"DashScope API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Internal error: {str(e)}"}


def validate_key(key: str) -> dict:
    """验证 Premium Key"""
    try:
        resp = requests.post(FC_URL, json={
            "action": "key_validate",
            "key": key
        }, timeout=10)
        return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def compare_bets_handler(environ, start_response):
    """
    /compare-bets 端点处理函数
    
    POST /compare-bets
    Body: {
        "image_data": "base64...",
        "key": "optional-key"
    }
    """
    # 只允许 POST
    if environ.get("REQUEST_METHOD") != "POST":
        start_response("405 Method Not Allowed", [("Content-Type", "application/json")])
        return [json.dumps({"success": False, "error": "Method not allowed"}).encode()]
    
    try:
        request_body_size = int(environ.get("CONTENT_LENGTH", 0))
        request_body = environ["wsgi.input"].read(request_body_size)
        body = json.loads(request_body)
    except Exception:
        start_response("400 Bad Request", [("Content-Type", "application/json")])
        return [json.dumps({"success": False, "error": "Invalid request body"}).encode()]
    
    image_data = body.get("image_data", "")
    key = body.get("key", "")
    
    if not image_data:
        start_response("400 Bad Request", [("Content-Type", "application/json")])
        return [json.dumps({"success": False, "error": "image_data is required"}).encode()]
    
    # 去除可能的 data URI 前缀
    if "," in image_data:
        image_data = image_data.split(",", 1)[1]
    
    # Key 验证（如果提供了 key）
    if key:
        key_result = validate_key(key)
        if not key_result.get("success") or not key_result.get("valid"):
            start_response("403 Forbidden", [("Content-Type", "application/json")])
            return [json.dumps({"success": False, "error": "Invalid key"}).encode()]
    
    # 调用 DashScope 视觉模型
    result = call_dashscope_vl(image_data)
    
    if result.get("success"):
        response_data = {
            "success": True,
            "data": result["data"],
            "timestamp": datetime.now().isoformat()
        }
        start_response("200 OK", [("Content-Type", "application/json")])
        return [json.dumps(response_data, ensure_ascii=False).encode("utf-8")]
    else:
        response_data = {
            "success": False,
            "error": result.get("error", "Unknown error"),
            "raw": result.get("raw", "")
        }
        start_response("200 OK", [("Content-Type", "application/json")])
        return [json.dumps(response_data, ensure_ascii=False).encode("utf-8")]


def handler(environ, start_response):
    """FC 主入口函数 - 独立部署版本"""
    path = environ.get("PATH_INFO", "/")
    
    if path == "/compare-bets" or path == "/compare-bets/":
        return compare_bets_handler(environ, start_response)
    
    # 默认响应
    start_response("404 Not Found", [("Content-Type", "application/json")])
    return [json.dumps({"success": False, "error": "Endpoint not found"}).encode()]
