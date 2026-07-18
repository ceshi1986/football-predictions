const { createHmac } = require('crypto');
const ADMIN_TOKEN = process.env.ADMIN_TOKEN || 'ruochan2026';
const DASHSCOPE_API_KEY = process.env.DASHSCOPE_API_KEY || '';
const OSS_ACCESS_KEY_ID = process.env.OSS_ACCESS_KEY_ID || '';
const OSS_ACCESS_KEY_SECRET = process.env.OSS_ACCESS_KEY_SECRET || '';
const OSS_BUCKET = process.env.OSS_BUCKET || 'metaphysics-keys';
const OSS_REGION = process.env.OSS_REGION || 'oss-cn-shanghai';
const OSS_ENDPOINT = 'https://' + OSS_BUCKET + '.' + OSS_REGION + '.aliyuncs.com';
const KEYS_FILE = 'keys.json';

let keysDB = [];
let keysLoaded = false;
let loading = false;

// 模型倍率：实际token × 倍率 = 标准token扣减
const MODEL_MULTIPLIERS = {
  'qwen-plus': 1.5,
  'qwen-vl-plus': 4,
  'qwen-vl-max': 6
};
const DEFAULT_TOKEN_LIMIT = 5000000; // 500万标准token = ¥5

async function loadKeysFromOSS() {
  if (loading) return;
  loading = true;
  try {
    const date = new Date().toUTCString();
    const resource = '/' + OSS_BUCKET + '/' + KEYS_FILE;
    const stringToSign = 'GET\n\n\n' + date + '\n' + resource;
    const signature = createHmac('sha1', OSS_ACCESS_KEY_SECRET).update(stringToSign).digest('base64');
    const url = OSS_ENDPOINT + '/' + KEYS_FILE;
    const r = await fetch(url, {
      method: 'GET',
      headers: { 'Date': date, 'Authorization': 'OSS ' + OSS_ACCESS_KEY_ID + ':' + signature }
    });
    if (r.ok) {
      const data = await r.json();
      keysDB = data || [];
      console.log('Loaded', keysDB.length, 'keys from OSS');
    } else {
      console.log('OSS load failed:', r.status);
    }
  } catch(e) {
    console.log('No keys file yet:', e.message);
  }
  keysLoaded = true;
  loading = false;
}

async function saveKeysToOSS() {
  try {
    const body = JSON.stringify(keysDB);
    const date = new Date().toUTCString();
    const contentType = 'application/json';
    const resource = '/' + OSS_BUCKET + '/' + KEYS_FILE;
    const stringToSign = 'PUT\n\n' + contentType + '\n' + date + '\n' + resource;
    const signature = createHmac('sha1', OSS_ACCESS_KEY_SECRET).update(stringToSign).digest('base64');
    const url = OSS_ENDPOINT + '/' + KEYS_FILE;
    await fetch(url, {
      method: 'PUT',
      headers: { 'Date': date, 'Content-Type': contentType, 'Authorization': 'OSS ' + OSS_ACCESS_KEY_ID + ':' + signature },
      body: body
    });
    console.log('Saved', keysDB.length, 'keys to OSS');
  } catch(e) {
    console.error('OSS save error:', e.message);
  }
}

async function ensureKeysAsync() {
  if (!keysLoaded && !loading) { await loadKeysFromOSS(); }
}

function jsonOk(d) { return JSON.stringify(Object.assign({ success: true }, d)); }
function jsonErr(m) { return JSON.stringify({ success: false, error: m }); }

async function callAI(sp, up) {
  try {
    const r = await fetch('https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + DASHSCOPE_API_KEY },
      body: JSON.stringify({
        model: 'qwen-plus',
        messages: [{role:'system',content:sp},{role:'user',content:up}],
        max_tokens: 2000, temperature: 0.7
      })
    });
    const d = await r.json();
    if (d.choices && d.choices[0]) {
      const tokens = d.usage ? (d.usage.total_tokens || 0) : 0;
      return { content: d.choices[0].message.content, tokens: tokens };
    }
  } catch(e) { console.error('AI error:', e.message); }
  return null;
}

function handleHealth() { return jsonOk({ status: 'ok', version: 'v5-compare', key_count: keysDB.length }); }

async function handleAnalyze(body) {
  const mode = body.mode, system_prompt = body.system_prompt, user_prompt = body.user_prompt, key = body.key;
  if (!system_prompt || !user_prompt) return jsonErr('缺参数');
  const isPreview = mode === 'preview';
  const model = 'qwen-plus';
  const multiplier = MODEL_MULTIPLIERS[model] || 1;
  if (!isPreview && key) {
    await ensureKeysAsync();
    const k = keysDB.find(function(x) { return x.key === key && x.status === 'active'; });
    if (!k) return jsonErr('Key无效');
    const remaining = (k.token_limit || DEFAULT_TOKEN_LIMIT) - (k.token_used || 0);
    if (remaining <= 0) return jsonErr('额度已用完');
  }
  const result = await callAI(isPreview ? system_prompt + '\n【预览模式】精简版500字' : system_prompt, user_prompt);
  if (!result) return jsonErr('AI失败');
  if (!isPreview && key) {
    const k = keysDB.find(function(x) { return x.key === key && x.status === 'active'; });
    if (k) {
      const standardTokens = Math.ceil(result.tokens * multiplier);
      k.token_used = (k.token_used || 0) + standardTokens;
      await saveKeysToOSS();
      const remaining = (k.token_limit || DEFAULT_TOKEN_LIMIT) - k.token_used;
      return jsonOk({ analysis: result.content, mode: isPreview ? 'preview' : 'full', tokens_used: result.tokens, standard_tokens: standardTokens, token_remaining: remaining });
    }
  }
  return jsonOk({ analysis: result.content, mode: isPreview ? 'preview' : 'full' });
}

async function handleKeyValidate(body) {
  const key = body.key;
  if (!key) return jsonErr('请提供Key');
  if (key === 'META-TEST-2026') return jsonOk({ valid: true, remaining: 999, type: 'test' });
  await ensureKeysAsync();
  const k = keysDB.find(function(x) { return x.key === key && x.status === 'active'; });
  if (!k) return jsonErr('Key无效或已过期');
  const isExpired = k.expire_date && new Date(k.expire_date) < new Date();
  if (isExpired) return jsonErr('Key已过期');
  const remaining = (k.token_limit || DEFAULT_TOKEN_LIMIT) - (k.token_used || 0);
  if (remaining <= 0) return jsonErr('额度已用完');
  return jsonOk({ valid: true, remaining: remaining, type: k.type, expire_date: k.expire_date || '永不过期' });
}

async function handleGenerateKey(body) {
  const token = body.token, type = body.type, count = body.count;
  if (token !== ADMIN_TOKEN) return jsonErr('token无效');
  await ensureKeysAsync();
  const keys = [];
  const num = Math.min(count || 1, 10);
  for (let i = 0; i < num; i++) {
    const key = 'META-' + Date.now() + '-' + Math.random().toString(36).substr(2, 8).toUpperCase();
    keysDB.push({ key: key, type: type || 'basic', status: 'active', token_limit: DEFAULT_TOKEN_LIMIT, token_used: 0, created_at: new Date().toISOString(), expire_date: null });
    keys.push(key);
  }
  await saveKeysToOSS();
  return jsonOk({ keys: keys, count: keys.length });
}

// === /compare-bets handler ===
const COMPARE_SYSTEM_PROMPT = '你是一个专业的竞彩足球截图识别助手。请仔细分析用户上传的图片，提取其中的竞彩投注信息。\n\n你需要识别以下格式的图片：\n1. sporttery.cn 计算器弹窗格式：显示"周X+数字 主队 VS 客队"和赔率选项\n2. 模拟试玩已选列表格式：显示"周X+数字 主队 VS 客队 [玩法] 选项 赔率"\n3. 比赛详情页格式：显示让球/非让球玩法，红色高亮选中项\n\n请提取每场比赛的以下信息：\n- matchId: 比赛编号（如"周五201"、"周六003"等）\n- home: 主队名称\n- away: 客队名称\n- selections: 用户选择的投注选项数组\n\n选项值标准化规则：\n- "胜"/"主胜"/"3" -> "胜"\n- "平"/"平局"/"1" -> "平"\n- "负"/"主负"/"0" -> "负"\n- "让胜"/"让球胜" -> "让胜"\n- "让平"/"让球平" -> "让平"\n- "让负"/"让球负" -> "让负"\n- 如果是让球玩法，在选项前加"让"字标识\n- 如果同时有让球和非让球选择，全部列出\n\n返回严格的JSON数组格式，不要包含其他内容：\n[{"matchId": "周五201", "home": "哥德堡", "away": "布鲁马波", "selections": ["胜","平"]}]\n\n如果无法识别任何比赛信息，返回空数组 []。';

async function handleCompareBets(rawBody) {
  let image_data = '';
  let key = '';
  
  try {
    let body;
    if (typeof rawBody === 'string' && rawBody) {
      body = JSON.parse(rawBody);
    } else if (typeof rawBody === 'object' && rawBody) {
      body = rawBody;
    } else {
      body = {};
    }
    image_data = body.image_data || '';
    key = body.key || '';
  } catch(e) {
    return { statusCode: 400, headers: {'Content-Type':'application/json; charset=utf-8'}, body: jsonErr('Invalid request body') };
  }
  
  if (!image_data) {
    return { statusCode: 400, headers: {'Content-Type':'application/json; charset=utf-8'}, body: jsonErr('image_data is required') };
  }
  
  // Strip data URI prefix
  if (image_data.indexOf(',') >= 0) {
    image_data = image_data.split(',')[1];
  }
  
  // Key validation if provided
  if (key) {
    await ensureKeysAsync();
    const k = keysDB.find(function(x) { return x.key === key && x.status === 'active'; });
    if (!k) {
      return { statusCode: 403, headers: {'Content-Type':'application/json; charset=utf-8'}, body: jsonErr('Invalid key') };
    }
    const remaining = (k.token_limit || DEFAULT_TOKEN_LIMIT) - (k.token_used || 0);
    if (remaining <= 0) {
      return { statusCode: 403, headers: {'Content-Type':'application/json; charset=utf-8'}, body: jsonErr('额度已用完') };
    }
  }
  
  // Call DashScope qwen-vl-plus
  try {
    const image_url = 'data:image/png;base64,' + image_data;
    const payload = {
      model: 'qwen-vl-plus',
      input: {
        messages: [
          { role: 'system', content: [{ text: COMPARE_SYSTEM_PROMPT }] },
          { role: 'user', content: [{ image: image_url }, { text: '请分析这张竞彩截图，提取比赛编号、队名和投注选择。' }] }
        ]
      },
      parameters: { result_format: 'message' }
    };
    
    const resp = await fetch('https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + DASHSCOPE_API_KEY, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    
    const result = await resp.json();
    
    if (result.output && result.output.choices && result.output.choices.length > 0) {
      const message = result.output.choices[0].message || {};
      const contentArr = message.content || [];
      let textContent = '';
      for (const item of contentArr) {
        if (typeof item === 'object' && item.text) textContent += item.text;
        else if (typeof item === 'string') textContent += item;
      }
      
      // Extract token usage from DashScope response
      const usage = result.usage || {};
      const tokensUsed = usage.total_tokens || (usage.output_tokens || 0) + (usage.input_tokens || 0);
      const multiplier = MODEL_MULTIPLIERS['qwen-vl-plus'] || 4;
      const standardTokens = Math.ceil(tokensUsed * multiplier);

      // Deduct tokens from user's key if provided
      if (key && tokensUsed > 0) {
        const k = keysDB.find(function(x) { return x.key === key && x.status === 'active'; });
        if (k) {
          k.token_used = (k.token_used || 0) + standardTokens;
          await saveKeysToOSS();
        }
      }

      const startIdx = textContent.indexOf('[');
      const endIdx = textContent.lastIndexOf(']') + 1;
      if (startIdx >= 0 && endIdx > startIdx) {
        const jsonStr = textContent.substring(startIdx, endIdx);
        const parsed = JSON.parse(jsonStr);
        return {
          statusCode: 200,
          headers: {'Content-Type':'application/json; charset=utf-8'},
          body: JSON.stringify({ success: true, data: parsed, tokens_used: tokensUsed, standard_tokens: standardTokens, timestamp: new Date().toISOString() })
        };
      } else {
        return {
          statusCode: 200,
          headers: {'Content-Type':'application/json; charset=utf-8'},
          body: JSON.stringify({ success: false, error: 'No JSON array found', raw: textContent })
        };
      }
    } else {
      return {
        statusCode: 200,
        headers: {'Content-Type':'application/json; charset=utf-8'},
        body: JSON.stringify({ success: false, error: 'Unexpected response', raw: JSON.stringify(result) })
      };
    }
  } catch(e) {
    console.error('compare-bets error:', e.message);
    return {
      statusCode: 200,
      headers: {'Content-Type':'application/json; charset=utf-8'},
      body: JSON.stringify({ success: false, error: e.message })
    };
  }
}

// === Main handler ===
exports.handler = async function(event, context, callback) {
  let eventObj = {};
  try {
    const raw = Buffer.isBuffer(event) ? event.toString('utf8') : (typeof event === 'string' ? event : JSON.stringify(event));
    eventObj = JSON.parse(raw);
  } catch(err) {
    callback(null, { statusCode: 400, headers: {'Content-Type':'application/json'}, body: jsonErr('解析失败') });
    return;
  }
  
  // FC 3.0 HTTP trigger format: event has rawPath
  const rawPath = eventObj.rawPath || '';
  const requestContext = eventObj.requestContext || {};
  const httpInfo = requestContext.http || {};
  const httpMethod = httpInfo.method || eventObj.httpMethod || '';
  const isHttp = !!rawPath;
  
  // Parse body
  let bodyStr = eventObj.body || '';
  if (eventObj.isBase64Encoded && bodyStr) {
    bodyStr = Buffer.from(bodyStr, 'base64').toString('utf8');
  }
  let body = {};
  if (bodyStr) {
    try { body = JSON.parse(bodyStr); } catch(e) { body = {}; }
  }
  
  // HTTP path-based routing
  if (isHttp) {
    if (rawPath === '/compare-bets' || rawPath === '/compare-bets/') {
      const result = await handleCompareBets(bodyStr);
      callback(null, result);
      return;
    }
    if (rawPath === '/health' || (rawPath === '/' && httpMethod === 'GET')) {
      callback(null, { statusCode: 200, headers: {'Content-Type':'application/json; charset=utf-8'}, body: handleHealth() });
      return;
    }
  }
  
  // Event-based routing (backward compat, for event triggers or POST /)
  const action = body.action || '';
  let result;
  try {
    if (action === 'health') result = handleHealth();
    else if (action === 'analyze') result = await handleAnalyze(body);
    else if (action === 'key_validate') result = await handleKeyValidate(body);
    else if (action === 'generate_key') result = await handleGenerateKey(body);
    else if (isHttp && rawPath === '/') result = handleHealth();
    else result = jsonErr('未知action: ' + action);
  } catch(e) {
    result = jsonErr(e.message);
  }
  callback(null, { statusCode: 200, headers: {'Content-Type':'application/json; charset=utf-8'}, body: result });
};
