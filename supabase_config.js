// ============================================================
// Supabase 配置初始化
// 注意：此处仅使用 anon key，service_role key 绝不放前端
// ============================================================
(function(){
  'use strict';

  // ─── 配置 ───
  var SUPABASE_URL = 'https://jfzamtgjifkocvbzklcu.supabase.co';
  var SUPABASE_ANON_KEY = 'sb_publishable_RlMjy-k8D6g1F-epf4xxsg_EH2pmwWC';

  // ─── 全局状态 ───
  window.FP_CONFIG = {
    SUPABASE_URL: SUPABASE_URL,
    SUPABASE_ANON_KEY: SUPABASE_ANON_KEY,
    supabase: null,
    currentUser: null,
    currentProfile: null
  };

  // ─── 初始化 Supabase Client ───
  function initSupabase(){
    if(typeof supabase === 'undefined'){
      console.warn('[FP] Supabase SDK 未加载，论坛功能不可用');
      return;
    }
    window.FP_CONFIG.supabase = supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
    console.log('[FP] Supabase 初始化完成');
  }

  // ─── 获取当前登录用户 ───
  async function refreshCurrentUser(){
    var sb = window.FP_CONFIG.supabase;
    if(!sb) return null;
    var result = await sb.auth.getSession();
    if(result.data.session){
      window.FP_CONFIG.currentUser = result.data.session.user;
      // 获取 profile
      var profileResult = await sb
        .from('profiles')
        .select('*')
        .eq('id', result.data.session.user.id)
        .single();
      if(profileResult.data){
        window.FP_CONFIG.currentProfile = profileResult.data;
      }
      return profileResult.data;
    } else {
      window.FP_CONFIG.currentUser = null;
      window.FP_CONFIG.currentProfile = null;
      return null;
    }
  }

  // ─── 检查是否已登录 ───
  function isLoggedIn(){
    return !!window.FP_CONFIG.currentUser;
  }

  // ─── 检查是否管理员 ───
  function isAdmin(){
    return window.FP_CONFIG.currentProfile && window.FP_CONFIG.currentProfile.role === 'admin';
  }

  // ─── 暴露全局接口 ───
  window.FP_AUTH = {
    init: initSupabase,
    refreshUser: refreshCurrentUser,
    isLoggedIn: isLoggedIn,
    isAdmin: isAdmin
  };

  // ─── 页面加载时初始化 ───
  document.addEventListener('DOMContentLoaded', function(){
    initSupabase();
  });

})();
