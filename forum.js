// ============================================================
// 论坛模块 (Forum Module)
// 三个板块：赛事讨论 / 模拟晒单 / 意见反馈
// 发帖 + 评论 + 敏感词过滤 + 频率限制
// ============================================================
(function(){
  'use strict';

  var sb = null;
  var PAGE_SIZE = 20;
  var currentSection = 'match_discuss';
  var currentPage = 0;
  var postsList = [];

  // ─── 敏感词列表（内容过滤） ───
  var SENSITIVE_WORDS = [
    '赌博', '赌球', '外围', '私彩', '黑彩', '代买', '代购',
    '必中', '包中', '内幕', '稳赢', '100%中',
    '加微信', '加QQ', '加vx', '加qq', '私聊',
    'fuck', 'shit', 'porn', 'sex', '操你', '妈的', '傻逼', '牛逼',
    '微信', 'QQ号', 'qq号', '手机号', '支付宝'
  ];

  // ─── 板块配置 ───
  var SECTIONS = {
    match_discuss: { name: '赛事讨论', icon: '⚽', desc: '围绕具体比赛的讨论分析' },
    bet_show:      { name: '模拟晒单', icon: '📋', desc: '展示模拟投注记录，分享策略' },
    feedback:      { name: '意见反馈', icon: '💬', desc: '对网站的建议与反馈' }
  };

  // ─── 等待 Supabase ───
  function waitForSupabase(){
    return new Promise(function(resolve){
      var attempts = 0;
      var interval = setInterval(function(){
        sb = window.FP_CONFIG && window.FP_CONFIG.supabase;
        if(sb || attempts > 20){ clearInterval(interval); resolve(!!sb); }
        attempts++;
      }, 200);
    });
  }

  // ─── 敏感词检测 ───
  function hasSensitiveWord(text){
    var lower = text.toLowerCase();
    for(var i = 0; i < SENSITIVE_WORDS.length; i++){
      if(lower.indexOf(SENSITIVE_WORDS[i].toLowerCase()) >= 0){
        return SENSITIVE_WORDS[i];
      }
    }
    return null;
  }

  // ─── 渲染论坛面板 ───
  function renderForum(){
    var container = document.getElementById('forum-container');
    if(!container) return;

    var html = '<div class="forum-wrapper">'
      // 板块切换
      + '<div class="forum-section-tabs">'
      + Object.keys(SECTIONS).map(function(key){
        var s = SECTIONS[key];
        return '<button class="forum-section-tab' + (key === currentSection ? ' active' : '') + '" '
          + 'data-section="' + key + '" onclick="FP_FORUM.switchSection(\'' + key + '\')">'
          + s.icon + ' ' + s.name + '</button>';
      }).join('')
      + '</div>'
      // 发帖按钮
      + '<div class="forum-actions">'
      + '<button class="forum-new-post-btn" onclick="FP_FORUM.showNewPost()">✏️ 发帖</button>'
      + '</div>'
      // 帖子列表
      + '<div class="forum-posts-list" id="forum-posts-list">'
      + '<div class="forum-loading">加载中...</div>'
      + '</div>'
      // 加载更多
      + '<div class="forum-load-more" id="forum-load-more" style="display:none">'
      + '<button onclick="FP_FORUM.loadMore()">加载更多</button>'
      + '</div>'
      + '</div>';

    container.innerHTML = html;
    loadPosts();
  }

  // ─── 切换板块 ───
  function switchSection(section){
    currentSection = section;
    currentPage = 0;
    postsList = [];
    renderForum();
  }

  // ─── 加载帖子列表 ───
  async function loadPosts(){
    if(!sb){ await waitForSupabase(); }
    if(!sb){ _showForumError('系统初始化中'); return; }

    var listEl = document.getElementById('forum-posts-list');
    if(!listEl) return;

    var from = currentPage * PAGE_SIZE;
    var to = from + PAGE_SIZE - 1;

    var result = await sb
      .from('posts')
      .select('*, profiles:profiles(username, avatar_url, role)')
      .eq('section', currentSection)
      .order('created_at', { ascending: false })
      .range(from, to);

    if(result.error){
      listEl.innerHTML = '<div class="forum-empty">加载失败: ' + _escHtml(result.error.message) + '</div>';
      return;
    }

    var posts = result.data || [];
    if(currentPage === 0 && posts.length === 0){
      var sectionInfo = SECTIONS[currentSection];
      listEl.innerHTML = '<div class="forum-empty">'
        + '<p>' + sectionInfo.icon + ' ' + sectionInfo.name + '</p>'
        + '<p>' + sectionInfo.desc + '</p>'
        + '<p style="margin-top:12px;font-size:.82rem;color:var(--text-muted)">暂无帖子，来发第一帖吧！</p>'
        + '</div>';
      return;
    }

    postsList = postsList.concat(posts);
    listEl.innerHTML = postsList.map(function(post, idx){
      return _renderPostCard(post, idx);
    }).join('');

    // 加载更多按钮
    var loadMoreEl = document.getElementById('forum-load-more');
    if(loadMoreEl){
      loadMoreEl.style.display = posts.length >= PAGE_SIZE ? 'block' : 'none';
    }

    // 渲染评论区（每帖默认折叠）
    posts.forEach(function(post){ _loadComments(post.id); });
  }

  // ─── 加载更多 ───
  function loadMore(){
    currentPage++;
    loadPosts();
  }

  // ─── 渲染帖子卡片 ───
  function _renderPostCard(post, idx){
    var profile = post.profiles || {};
    var timeStr = _formatTime(post.created_at);
    var sectionLabel = SECTIONS[post.section] ? SECTIONS[post.section].icon + ' ' + SECTIONS[post.section].name : post.section;
    var isOwner = window.FP_CONFIG.currentUser && window.FP_CONFIG.currentUser.id === post.user_id;

    var html = '<div class="forum-post-card" id="post-' + post.id + '">'
      + '<div class="forum-post-header">'
      + '<div class="forum-post-user">'
      + '<span class="forum-post-avatar">' + ((profile.username || '?').charAt(0).toUpperCase()) + '</span>'
      + '<span class="forum-post-username">' + _escHtml(profile.username || '匿名') + '</span>'
      + (profile.role === 'admin' ? '<span class="fp-admin-badge">管理员</span>' : '')
      + '</div>'
      + '<span class="forum-post-time">' + timeStr + '</span>'
      + '</div>'
      + '<h4 class="forum-post-title">' + _escHtml(post.title) + '</h4>'
      + '<div class="forum-post-content">' + _escHtml(post.content) + '</div>';

    // 晒单标签
    if(post.section === 'bet_show' && post.bet_id){
      html += '<div class="forum-bet-tag">📋 模拟晒单 | 投注#' + post.bet_id.substring(0, 8) + '</div>';
    }
    // 赛事标签
    if(post.match_id){
      html += '<div class="forum-match-tag">🏟️ 关联比赛: ' + _escHtml(post.match_id) + '</div>';
    }

    html += '<div class="forum-post-actions">'
      + '<button class="forum-action-btn" onclick="FP_FORUM.toggleComments(\'' + post.id + '\')">💬 评论</button>'
      + (isOwner ? '<button class="forum-action-btn danger" onclick="FP_FORUM.deletePost(\'' + post.id + '\')">🗑️ 删除</button>' : '')
      + '</div>'
      + '<div class="forum-comments-area" id="comments-' + post.id + '" style="display:none">'
      + '<div class="forum-comments-list" id="comments-list-' + post.id + '"></div>'
      + '<div class="forum-comment-input">'
      + '<input type="text" id="comment-input-' + post.id + '" placeholder="写评论..." maxlength="1000" onkeydown="if(event.key===\'Enter\')FP_FORUM.submitComment(\'' + post.id + '\')">'
      + '<button onclick="FP_FORUM.submitComment(\'' + post.id + '\')">发送</button>'
      + '</div>'
      + '</div>'
      + '</div>';
    return html;
  }

  // ─── 加载评论 ───
  async function _loadComments(postId){
    if(!sb) return;
    var result = await sb
      .from('comments')
      .select('*, profiles:profiles(username, avatar_url, role)')
      .eq('post_id', postId)
      .order('created_at', { ascending: true })
      .limit(50);

    if(result.error || !result.data) return;
    var listEl = document.getElementById('comments-list-' + postId);
    if(!listEl) return;

    if(result.data.length === 0){
      listEl.innerHTML = '<div class="forum-no-comments">暂无评论</div>';
      return;
    }

    listEl.innerHTML = result.data.map(function(c){
      var p = c.profiles || {};
      var isOwner = window.FP_CONFIG.currentUser && window.FP_CONFIG.currentUser.id === c.user_id;
      return '<div class="forum-comment-item">'
        + '<span class="forum-comment-user">' + _escHtml(p.username || '匿名') + '</span>'
        + (p.role === 'admin' ? '<span class="fp-admin-badge-mini">管</span>' : '')
        + '<span class="forum-comment-text">' + _escHtml(c.content) + '</span>'
        + '<span class="forum-comment-time">' + _formatTime(c.created_at) + '</span>'
        + (isOwner ? '<button class="forum-comment-del" onclick="FP_FORUM.deleteComment(\'' + c.id + '\',\'' + postId + '\')">×</button>' : '')
        + '</div>';
    }).join('');
  }

  // ─── 显示发帖弹窗 ───
  function showNewPost(){
    if(!window.FP_AUTH || !window.FP_AUTH.isLoggedIn()){
      FP_AUTH.showLogin();
      return;
    }
    if(document.getElementById('fp-newpost-modal')) return;

    var sectionOptions = Object.keys(SECTIONS).map(function(key){
      return '<option value="' + key + '"' + (key === currentSection ? ' selected' : '') + '>'
        + SECTIONS[key].icon + ' ' + SECTIONS[key].name + '</option>';
    }).join('');

    // 晒单快捷按钮
    var showBetBtn = '';
    if(currentSection === 'bet_show'){
      showBetBtn = '<button type="button" class="forum-bet-quick-btn" onclick="FP_FORUM.quickShowBet()">📋 一键晒模拟投注单</button>';
    }

    var html = '<div id="fp-newpost-modal" class="fp-auth-overlay" onclick="if(event.target===this)FP_FORUM.closeNewPost()">'
      + '<div class="fp-auth-modal fp-newpost-modal">'
      + '<button class="fp-auth-close" onclick="FP_FORUM.closeNewPost()">&times;</button>'
      + '<h3>✏️ 发布新帖</h3>'
      + '<div class="fp-auth-field">'
      + '<label>板块</label>'
      + '<select id="fp-post-section">' + sectionOptions + '</select>'
      + '</div>'
      + '<div class="fp-auth-field">'
      + '<label>标题</label>'
      + '<input type="text" id="fp-post-title" placeholder="2-100个字符" maxlength="100">'
      + '</div>'
      + '<div class="fp-auth-field">'
      + '<label>内容</label>'
      + '<textarea id="fp-post-content" placeholder="5-5000个字符" maxlength="5000" rows="6"></textarea>'
      + '</div>'
      + (currentSection === 'match_discuss' ? '<div class="fp-auth-field"><label>关联比赛ID（可选）</label><input type="text" id="fp-post-match-id" placeholder="如: 2026091001"></div>' : '')
      + showBetBtn
      + '<input type="hidden" id="fp-post-bet-id" value="">'
      + '<div id="fp-post-msg" class="fp-auth-msg"></div>'
      + '<button class="fp-auth-submit" onclick="FP_FORUM.submitPost()">发布</button>'
      + '</div></div>';

    document.body.insertAdjacentHTML('beforeend', html);
  }

  // ─── 一键晒单：从模拟投注记录生成 ───
  function quickShowBet(){
    // 从 bet_sim 模块获取最近的投注记录
    if(!window.BetSimulator || !window.BetSimulator.getRecentBets){
      _showPostMsg('投注数据加载中，请稍后', 'error');
      return;
    }
    var recentBets = window.BetSimulator.getRecentBets(5);
    if(!recentBets || recentBets.length === 0){
      _showPostMsg('暂无模拟投注记录', 'error');
      return;
    }
    // 自动填充内容
    var content = '【模拟晒单】最近投注记录：\n\n';
    recentBets.forEach(function(bet, i){
      content += (i + 1) + '. ' + (bet.matchNum || '') + ' ' + (bet.home || '') + ' vs ' + (bet.away || '')
        + ' | ' + (bet.playName || '') + ' | ' + (bet.selections || []).join(',')
        + ' | ' + (bet.parlayType === 'single' ? '单关' : bet.parlayType)
        + ' | ¥' + (bet.amount || '0') + '\n';
    });
    content += '\n#模拟投注 #策略验证';

    var contentEl = document.getElementById('fp-post-content');
    if(contentEl) contentEl.value = content;
    var titleEl = document.getElementById('fp-post-title');
    if(titleEl) titleEl.value = '我的模拟投注晒单 ' + new Date().toLocaleDateString('zh-CN');

    // 记录最后一个 bet_id
    var betIdEl = document.getElementById('fp-post-bet-id');
    if(betIdEl && recentBets[0] && recentBets[0].id) betIdEl.value = recentBets[0].id;
  }

  // ─── 提交发帖 ───
  async function submitPost(){
    if(!sb){ await waitForSupabase(); }
    if(!sb){ _showPostMsg('系统未就绪', 'error'); return; }
    if(!window.FP_AUTH.isLoggedIn()){ FP_AUTH.showLogin(); return; }

    var section = document.getElementById('fp-post-section').value;
    var title = document.getElementById('fp-post-title').value.trim();
    var content = document.getElementById('fp-post-content').value.trim();
    var matchId = document.getElementById('fp-post-match-id');
    var betId = document.getElementById('fp-post-bet-id');

    // 校验
    if(!title || title.length < 2){ _showPostMsg('标题至少2个字符', 'error'); return; }
    if(!content || content.length < 5){ _showPostMsg('内容至少5个字符', 'error'); return; }

    // 敏感词检查
    var word = hasSensitiveWord(title + ' ' + content);
    if(word){
      _showPostMsg('内容包含敏感词"' + word + '"，请修改', 'error');
      return;
    }

    var postData = {
      user_id: window.FP_CONFIG.currentUser.id,
      section: section,
      title: title,
      content: content
    };
    if(matchId && matchId.value.trim()) postData.match_id = matchId.value.trim();
    if(betId && betId.value.trim()) postData.bet_id = betId.value.trim();

    var result = await sb.from('posts').insert(postData).select().single();
    if(result.error){
      if(result.error.message.indexOf('rate_limit') >= 0 || result.error.message.indexOf('1 minute') >= 0){
        _showPostMsg('发帖太频繁，请1分钟后再试', 'error');
      } else {
        _showPostMsg('发帖失败: ' + result.error.message, 'error');
      }
      return;
    }

    closeNewPost();
    currentPage = 0;
    postsList = [];
    currentSection = section;
    renderForum();
    _showToast('发帖成功！');
  }

  // ─── 提交评论 ───
  async function submitComment(postId){
    if(!sb){ await waitForSupabase(); }
    if(!window.FP_AUTH.isLoggedIn()){ FP_AUTH.showLogin(); return; }

    var inputEl = document.getElementById('comment-input-' + postId);
    if(!inputEl) return;
    var content = inputEl.value.trim();
    if(!content){ return; }
    if(content.length > 1000){ _showToast('评论不超过1000字'); return; }

    // 敏感词
    var word = hasSensitiveWord(content);
    if(word){
      _showToast('评论包含敏感词"' + word + '"');
      return;
    }

    var result = await sb.from('comments').insert({
      post_id: postId,
      user_id: window.FP_CONFIG.currentUser.id,
      content: content
    });

    if(result.error){
      _showToast('评论失败: ' + result.error.message);
      return;
    }

    inputEl.value = '';
    _loadComments(postId);
  }

  // ─── 切换评论区 ───
  function toggleComments(postId){
    if(!window.FP_AUTH.isLoggedIn()){ FP_AUTH.showLogin(); return; }
    var area = document.getElementById('comments-' + postId);
    if(area){
      area.style.display = area.style.display === 'none' ? 'block' : 'none';
    }
  }

  // ─── 删除帖子 ───
  async function deletePost(postId){
    if(!confirm('确定删除这条帖子？')) return;
    if(!sb){ await waitForSupabase(); }
    var result = await sb.from('posts').delete().eq('id', postId);
    if(result.error){ _showToast('删除失败'); return; }
    var el = document.getElementById('post-' + postId);
    if(el) el.remove();
    _showToast('已删除');
  }

  // ─── 删除评论 ───
  async function deleteComment(commentId, postId){
    if(!sb){ await waitForSupabase(); }
    var result = await sb.from('comments').delete().eq('id', commentId);
    if(result.error){ _showToast('删除失败'); return; }
    _loadComments(postId);
  }

  // ─── 关闭发帖弹窗 ───
  function closeNewPost(){
    var el = document.getElementById('fp-newpost-modal');
    if(el) el.remove();
  }

  // ─── 刷新论坛 ───
  function refresh(){
    currentPage = 0;
    postsList = [];
    renderForum();
  }

  // ─── 工具函数 ───
  function _escHtml(s){
    var d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }
  function _formatTime(isoStr){
    if(!isoStr) return '';
    var d = new Date(isoStr);
    var now = new Date();
    var diff = (now - d) / 1000;
    if(diff < 60) return '刚刚';
    if(diff < 3600) return Math.floor(diff / 60) + '分钟前';
    if(diff < 86400) return Math.floor(diff / 3600) + '小时前';
    if(diff < 604800) return Math.floor(diff / 86400) + '天前';
    return d.toLocaleDateString('zh-CN');
  }
  function _showPostMsg(text, type){
    var el = document.getElementById('fp-post-msg');
    if(el){ el.textContent = text; el.className = 'fp-auth-msg ' + (type || ''); }
  }
  function _showForumError(text){
    var listEl = document.getElementById('forum-posts-list');
    if(listEl) listEl.innerHTML = '<div class="forum-empty">' + _escHtml(text) + '</div>';
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
  window.FP_FORUM = {
    render: renderForum,
    switchSection: switchSection,
    showNewPost: showNewPost,
    closeNewPost: closeNewPost,
    submitPost: submitPost,
    submitComment: submitComment,
    toggleComments: toggleComments,
    deletePost: deletePost,
    deleteComment: deleteComment,
    loadMore: loadMore,
    quickShowBet: quickShowBet,
    refresh: refresh
  };

})();
