// ============================================================
// 认证模块 (Auth Module)
// 登录/注册弹窗 + 邀请码校验 + 用户状态管理
// ============================================================
(function(){
  'use strict';

  var sb = null; // Supabase client 引用

  // ─── 敏感词列表（基础过滤） ───
  var BLOCKED_USERNAMES = ['admin', '管理员', '系统', '官方', 'test', 'fuck', 'shit', 'porn', 'sex'];

  // ─── 等待 Supabase 就绪 ───
  function waitForSupabase(){
    return new Promise(function(resolve){
      var attempts = 0;
      var interval = setInterval(function(){
        sb = window.FP_CONFIG && window.FP_CONFIG.supabase;
        if(sb || attempts > 20){
          clearInterval(interval);
          resolve(!!sb);
        }
        attempts++;
      }, 200);
    });
  }

  // ─── 显示登录弹窗 ───
  function showLoginModal(){
    if(document.getElementById('fp-auth-modal')) return; // 已存在
    var html = '<div id="fp-auth-modal" class="fp-auth-overlay" onclick="if(event.target===this)FP_AUTH.closeModal()">'
      + '<div class="fp-auth-modal">'
      + '<button class="fp-auth-close" onclick="FP_AUTH.closeModal()">&times;</button>'
      + '<div class="fp-auth-tabs">'
      + '<button class="fp-auth-tab active" data-mode="login" onclick="FP_AUTH.switchMode(\'login\')">登录</button>'
      + '<button class="fp-auth-tab" data-mode="register" onclick="FP_AUTH.switchMode(\'register\')">注册</button>'
      + '</div>'
      + '<div id="fp-auth-form">'
      + _buildLoginForm()
      + '</div>'
      + '<div id="fp-auth-msg" class="fp-auth-msg"></div>'
      + '</div></div>';
    document.body.insertAdjacentHTML('beforeend', html);
  }

  function _buildLoginForm(){
    return '<div class="fp-auth-field">'
      + '<label>邮箱</label>'
      + '<input type="email" id="fp-auth-email" placeholder="your@email.com" autocomplete="email">'
      + '</div>'
      + '<div class="fp-auth-field">'
      + '<label>密码</label>'
      + '<input type="password" id="fp-auth-password" placeholder="至少6位" autocomplete="current-password">'
      + '</div>'
      + '<div id="fp-auth-register-fields" style="display:none">'
      + '<div class="fp-auth-field">'
      + '<label>用户名</label>'
      + '<input type="text" id="fp-auth-username" placeholder="2-20个字符" maxlength="20">'
      + '</div>'
      + '<div class="fp-auth-field">'
      + '<label>邀请码 <span class="fp-auth-required">*必填</span></label>'
      + '<input type="text" id="fp-auth-invite" placeholder="请输入邀请码" maxlength="32">'
      + '</div>'
      + '</div>'
      + '<button class="fp-auth-submit" id="fp-auth-submit-btn" onclick="FP_AUTH.handleSubmit()">登录</button>';
  }

  // ─── 切换登录/注册模式 ───
  function switchMode(mode){
    var tabs = document.querySelectorAll('.fp-auth-tab');
    tabs.forEach(function(t){ t.classList.toggle('active', t.dataset.mode === mode); });
    var regFields = document.getElementById('fp-auth-register-fields');
    var submitBtn = document.getElementById('fp-auth-submit-btn');
    if(mode === 'register'){
      regFields.style.display = 'block';
      submitBtn.textContent = '注册';
    } else {
      regFields.style.display = 'none';
      submitBtn.textContent = '登录';
    }
    _clearMsg();
  }

  // ─── 提交处理 ───
  async function handleSubmit(){
    if(!sb){ await waitForSupabase(); }
    if(!sb){ _showMsg('系统初始化中，请稍后重试', 'error'); return; }

    var activeMode = document.querySelector('.fp-auth-tab.active').dataset.mode;
    var email = document.getElementById('fp-auth-email').value.trim();
    var password = document.getElementById('fp-auth-password').value;

    if(!email || !password){ _showMsg('请填写邮箱和密码', 'error'); return; }
    if(password.length < 6){ _showMsg('密码至少6位', 'error'); return; }

    var btn = document.getElementById('fp-auth-submit-btn');
    btn.disabled = true;
    btn.textContent = '处理中...';

    try {
      if(activeMode === 'login'){
        await _doLogin(email, password);
      } else {
        var username = document.getElementById('fp-auth-username').value.trim();
        var inviteCode = document.getElementById('fp-auth-invite').value.trim();
        await _doRegister(email, password, username, inviteCode);
      }
    } catch(e){
      _showMsg(e.message || '操作失败，请重试', 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = activeMode === 'login' ? '登录' : '注册';
    }
  }

  // ─── 登录 ───
  async function _doLogin(email, password){
    var result = await sb.auth.signInWithPassword({ email: email, password: password });
    if(result.error){ _showMsg(result.error.message, 'error'); return; }
    _showMsg('登录成功！', 'success');
    await _afterAuth();
    setTimeout(closeModal, 800);
  }

  // ─── 注册 ───
  async function _doRegister(email, password, username, inviteCode){
    // 前端校验
    if(!username || username.length < 2){ _showMsg('用户名至少2个字符', 'error'); return; }
    if(!inviteCode){ _showMsg('请输入邀请码', 'error'); return; }
    // 敏感词检查
    var lowerName = username.toLowerCase();
    for(var i = 0; i < BLOCKED_USERNAMES.length; i++){
      if(lowerName.indexOf(BLOCKED_USERNAMES[i]) >= 0){
        _showMsg('用户名包含敏感词，请更换', 'error');
        return;
      }
    }
    // 校验邀请码
    var codeResult = await sb.rpc('fn_validate_invite_code', { p_code: inviteCode });
    if(codeResult.error || !codeResult.data){
      _showMsg('邀请码无效或已过期', 'error');
      return;
    }
    // 注册
    var result = await sb.auth.signUp({
      email: email,
      password: password,
      options: {
        data: { username: username, invite_code: inviteCode }
      }
    });
    if(result.error){ _showMsg(result.error.message, 'error'); return; }

    // 更新 profile username 和邀请码
    if(result.data.user){
      await sb.from('profiles').update({
        username: username,
        invite_code_used: inviteCode
      }).eq('id', result.data.user.id);

      // 消耗邀请码使用次数
      await sb.rpc('fn_consume_invite_code', { p_code: inviteCode });
    }

    if(result.data.session){
      _showMsg('注册成功！', 'success');
      await _afterAuth();
      setTimeout(closeModal, 800);
    } else {
      _showMsg('注册成功！请检查邮箱完成验证', 'success');
    }
  }

  // ─── 登出 ───
  async function logout(){
    if(!sb){ await waitForSupabase(); }
    if(!sb) return;
    await sb.auth.signOut();
    window.FP_CONFIG.currentUser = null;
    window.FP_CONFIG.currentProfile = null;
    _updateHeaderUI();
    _showToast('已退出登录');
  }

  // ─── 认证成功后 ───
  async function _afterAuth(){
    await window.FP_AUTH.refreshUser();
    _updateHeaderUI();
    // 通知论坛模块刷新
    if(window.FP_FORUM && window.FP_FORUM.refresh){
      window.FP_FORUM.refresh();
    }
  }

  // ─── 更新顶部 UI ───
  function _updateHeaderUI(){
    var container = document.getElementById('fp-auth-header');
    if(!container) return;
    var user = window.FP_CONFIG.currentUser;
    var profile = window.FP_CONFIG.currentProfile;
    if(user && profile){
      container.innerHTML = '<div class="fp-user-info">'
        + '<span class="fp-user-avatar">' + (profile.username ? profile.username.charAt(0).toUpperCase() : '?') + '</span>'
        + '<span class="fp-user-name">' + _escHtml(profile.username) + '</span>'
        + (profile.role === 'admin' ? '<span class="fp-admin-badge">管理员</span>' : '')
        + '<button class="fp-logout-btn" onclick="FP_AUTH.logout()">退出</button>'
        + '</div>';
    } else {
      container.innerHTML = '<button class="fp-login-btn" onclick="FP_AUTH.showLogin()">登录 / 注册</button>';
    }
  }

  // ─── 关闭弹窗 ───
  function closeModal(){
    var modal = document.getElementById('fp-auth-modal');
    if(modal) modal.remove();
  }

  // ─── 工具函数 ───
  function _showMsg(text, type){
    var el = document.getElementById('fp-auth-msg');
    if(el){
      el.textContent = text;
      el.className = 'fp-auth-msg ' + (type || '');
    }
  }
  function _clearMsg(){
    var el = document.getElementById('fp-auth-msg');
    if(el){ el.textContent = ''; el.className = 'fp-auth-msg'; }
  }
  function _escHtml(s){
    var d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }
  function _showToast(text){
    var toast = document.createElement('div');
    toast.className = 'fp-toast';
    toast.textContent = text;
    document.body.appendChild(toast);
    setTimeout(function(){ toast.classList.add('show'); }, 10);
    setTimeout(function(){ toast.classList.remove('show'); setTimeout(function(){ toast.remove(); }, 300); }, 2500);
  }

  // ─── 暴露全局接口 ───
  window.FP_AUTH = Object.assign(window.FP_AUTH || {}, {
    showLogin: showLoginModal,
    closeModal: closeModal,
    switchMode: switchMode,
    handleSubmit: handleSubmit,
    logout: logout,
    updateHeaderUI: _updateHeaderUI
  });

  // ─── 初始化：检查登录态 ───
  document.addEventListener('DOMContentLoaded', async function(){
    await waitForSupabase();
    if(sb){
      await window.FP_AUTH.refreshUser();
    }
    _updateHeaderUI();
  });

})();
