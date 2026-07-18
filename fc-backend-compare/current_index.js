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
      headers: {
        'Date': date,
        'Authorization': 'OSS ' + OSS_ACCESS_KEY_ID + ':' + signature
      }
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
      headers: {
        'Date': date,
        'Content-Type': contentType,
        'Authorization': 'OSS ' + OSS_ACCESS_KEY_ID + ':' + signature
      },
      body: body
    });
    console.log('Saved', keysDB.length, 'keys to OSS');
  } catch(e) {
    console.error('OSS save error:', e.message);
  }
}

async function ensureKeysAsync() {
  if (!keysLoaded && !loading) {
    await loadKeysFromOSS();
  }
}

function jsonOk(d) {
  return JSON.stringify(Object.assign({ success: true }, d));
}

function jsonErr(m) {
  return JSON.stringify({ success: false, error: m });
}

async function callAI(sp, up) {
  try {
    const r = await fetch('https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + DASHSCOPE_API_KEY
      },
      body: JSON.stringify({
        model: 'qwen-plus',
        messages: [{role:'system',content:sp},{role:'user',content:up}],
        max_tokens: 2000,
        temperature: 0.7
      })
    });
    const d = await r.json();
    if (d.choices && d.choices[0]) {
      const tokens = d.usage ? (d.usage.total_tokens || 0) : 0;
      return { content: d.choices[0].message.content, tokens: tokens };
    }
  } catch(e) {
    console.error('AI error:', e.message);
  }
  return null;
}

function handleHealth() {
  return jsonOk({ status: 'ok', version: 'v4-oss', key_count: keysDB.length });
}

async function handleAnalyze(body) {
  const mode = body.mode, system_prompt = body.system_prompt, user_prompt = body.user_prompt, key = body.key;
  if (!system_prompt || !user_prompt) return jsonErr('缺参数');
  const isPreview = mode === 'preview';
  if (!isPreview && key) {
    await ensureKeysAsync();
    const k = keysDB.find(function(x) { return x.key === key && x.status === 'active'; });
    if (!k) return jsonErr('Key无效');
    const remaining = (k.token_limit || 4000000) - (k.token_used || 0);
    if (remaining <= 0) return jsonErr('额度已用完');
  }
  const result = await callAI(
    isPreview ? system_prompt + '\n【预览模式】精简版500字' : system_prompt,
    user_prompt
  );
  if (!result) return jsonErr('AI失败');
  if (!isPreview && key) {
    const k = keysDB.find(function(x) { return x.key === key && x.status === 'active'; });
    if (k) {
      k.token_used = (k.token_used || 0) + result.tokens;
      await saveKeysToOSS();
      const remaining = (k.token_limit || 4000000) - k.token_used;
      return jsonOk({ analysis: result.content, mode: isPreview ? 'preview' : 'full', tokens_used: result.tokens, token_remaining: remaining });
    }
  }
  return jsonOk({ analysis: result.content, mode: isPreview ? 'preview' : 'full' });
}

async function handleKeyValidate(body) {
  const key = body.key;
  if (!key) return jsonErr('请提供Key');
  if (key === 'META-TEST-2026') {
    return jsonOk({ valid: true, remaining: 999, type: 'test' });
  }
  await ensureKeysAsync();
  const k = keysDB.find(function(x) { return x.key === key && x.status === 'active'; });
  if (!k) return jsonErr('Key无效或已过期');
  const isExpired = k.expire_date && new Date(k.expire_date) < new Date();
  if (isExpired) return jsonErr('Key已过期');
  const remaining = (k.token_limit || 4000000) - (k.token_used || 0);
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
    keysDB.push({ key: key, type: type || 'basic', status: 'active', token_limit: 4000000, token_used: 0, created_at: new Date().toISOString(), expire_date: null });
    keys.push(key);
  }
  await saveKeysToOSS();
  return jsonOk({ keys: keys, count: keys.length });
}

exports.handler = async function(event, context, callback) {
  let body = {};
  try {
    let e = Buffer.isBuffer(event) ? JSON.parse(event.toString('utf8')) : (typeof event === 'string' ? JSON.parse(event) : event);
    if (e.body) body = JSON.parse(e.body);
  } catch(err) {
    callback(null, { statusCode: 400, headers: {'Content-Type':'application/json'}, body: jsonErr('解析失败') });
    return;
  }
  const action = body.action || '';
  let result;
  try {
    if (action === 'health') result = handleHealth();
    else if (action === 'analyze') result = await handleAnalyze(body);
    else if (action === 'key_validate') result = await handleKeyValidate(body);
    else if (action === 'generate_key') result = await handleGenerateKey(body);
    else result = jsonErr('未知action: ' + action);
  } catch(e) {
    result = jsonErr(e.message);
  }
  callback(null, { statusCode: 200, headers: {'Content-Type':'application/json; charset=utf-8'}, body: result });
};