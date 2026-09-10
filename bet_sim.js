// ============================================================
// 模拟投注模块 (Bet Simulator)
// 依赖: 全局竞彩赔率数据 data/sporttery_odds/latest.json
// 依赖: 战绩数据 data/bet_sim/stats.json, bets.json
// ============================================================
(function(){
  'use strict';

  // ─── 常量 ───
  var UNIT_BET_FEN = 200; // 每注2元 = 200分
  var PRIZE_CAPS = {1:10000000, 2:20000000, 3:20000000, 4:50000000, 5:50000000};
  var PRIZE_CAP_6PLUS = 100000000; // 100万

  var PLAY_NAMES = {
    had:'胜平负', hhad:'让球胜平负', crs:'比分', ttg:'总进球', hafu:'半全场', mixed:'混合过关'
  };
  var PARLAY_NAMES = {single:'单关', parlay_2:'2串1', parlay_3:'3串1', parlay_4:'4串1'};

  // 玩法选项映射
  var HAD_LABELS = {h:'主胜', d:'平', a:'客胜'};
  var HHAD_LABELS = {h:'让球主胜', d:'让球平', a:'让球客胜'};
  var TTG_LABELS = {'0':'0球', '1':'1球', '2':'2球', '3':'3球', '4':'4球', '5':'5球', '6':'6球', '7':'7+球'};
  var HAFU_LABELS = {hh:'胜胜', hd:'胜平', ha:'胜负', dh:'平胜', dd:'平平', da:'平负', ah:'负胜', ad:'负平', aa:'负负'};

  // ─── 状态 ───
  var oddsData = null;       // 赔率数据
  var currentPlay = 'had';   // 当前玩法
  var betSlip = [];          // 投注单 [{matchId, matchNumStr, home, away, play, selections, oddsMap, singleAvailable, allupAvailable}]
  var multiplier = 1;
  var parlayType = 'single';
  var statsData = null;
  var betsData = null;

  // ─── 工具函数 ───
  function fenToYuan(fen){ return (fen / 100).toFixed(2); }
  function yuanToFen(yuan){ return Math.round(yuan * 100); }

  function loadJSON(url, callback){
    var xhr = new XMLHttpRequest();
    xhr.open('GET', url + '?t=' + Date.now(), true);
    xhr.onreadystatechange = function(){
      if(xhr.readyState === 4){
        if(xhr.status === 200){
          try { callback(JSON.parse(xhr.responseText)); }
          catch(e){ callback(null); }
        } else { callback(null); }
      }
    };
    xhr.send();
  }

  function getPoolCode(play){
    return play.toUpperCase();
  }

  function getSingleAvailable(match, play){
    if(!match.poolInfo) return false;
    var info = match.poolInfo[getPoolCode(play)];
    return info ? info.bettingSingle : false;
  }

  function getAllupAvailable(match, play){
    if(!match.poolInfo) return true;
    var info = match.poolInfo[getPoolCode(play)];
    return info ? info.bettingAllup : true;
  }

  // ─── Tab切换 ───
  window.switchBetTab = function(tab){
    document.querySelectorAll('.betsim-tab-btn').forEach(function(b){
      b.classList.toggle('active', b.dataset.btab === tab);
    });
    document.querySelectorAll('.betsim-panel').forEach(function(p){
      p.classList.toggle('active', p.id === 'btab-' + tab);
    });
    if(tab === 'stats'){ loadStats(); }
    if(tab === 'auto-bets'){
      if(!isAuthed()){
        renderAutoBetGate();
      } else {
        loadAutoBetsDates();
      }
    }
  };

  // ─── 自动模拟单：仅注册/登录用户可见 ───
  function isAuthed(){
    return !!(window.FP_CONFIG && window.FP_CONFIG.currentUser);
  }

  function renderAutoBetGate(){
    var sel = document.getElementById('auto-bets-date-select');
    var list = document.getElementById('auto-bets-list');
    if(sel) sel.style.display = 'none';
    if(list){
      list.innerHTML = '<div class="calc-loading" style="padding:32px 16px;text-align:center">'
        + '<div style="font-size:2.2rem;margin-bottom:10px">🔒</div>'
        + '<div style="font-size:.95rem;color:var(--text);margin-bottom:6px">每日自动模拟单仅对注册用户开放</div>'
        + '<div style="font-size:.78rem;color:var(--text-muted);margin-bottom:16px">注册登录后可查看每日21:00生成的策略模拟单与历史战绩</div>'
        + '<button onclick="FP_AUTH.showLogin()" style="background:linear-gradient(135deg,#62fad3,#4cc9f0);color:#06121f;border:none;padding:10px 28px;border-radius:8px;font-size:.9rem;font-weight:700;cursor:pointer">登录 / 注册</button>'
        + '</div>';
    }
  }

  window.refreshAutoBetGate = function(){
    // 登录成功后由 auth 流程调用，解锁自动模拟单
    var active = document.querySelector('#btab-auto-bets.active');
    if(active && isAuthed()){
      var sel = document.getElementById('auto-bets-date-select');
      if(sel) sel.style.display = '';
      loadAutoBetsDates();
    }
  };

  // ─── 玩法切换 ───
  window.setCalcPlay = function(play){
    currentPlay = play;
    document.querySelectorAll('.calc-play-btn').forEach(function(b){
      b.classList.toggle('active', b.dataset.play === play);
    });
    renderMatchList();
    // 清空投注单中与当前玩法不匹配的项（混合过关保留）
    if(play !== 'mixed'){
      betSlip = betSlip.filter(function(item){ return item.play === play; });
    }
    renderBetSlip();
    updateBetSummary();
  };

  // ─── 加载赔率数据 ───
  function loadOddsData(){
    loadJSON('data/sporttery_odds/latest.json', function(data){
      if(!data || !data.matches_by_date){
        document.getElementById('calc-match-list').innerHTML =
          '<div class="calc-loading">暂无赔率数据<br><small>竞彩官方数据加载失败</small></div>';
        return;
      }
      oddsData = data;
      // 取最近的比赛日
      var dates = data.dates || [];
      if(dates.length > 0){
        var latestDate = dates[dates.length - 1];
        document.getElementById('calc-match-date').textContent = latestDate;
      }
      renderMatchList();
    });
  }

  // ─── 渲染场次列表 ───
  function renderMatchList(){
    var container = document.getElementById('calc-match-list');
    if(!oddsData || !oddsData.dates || oddsData.dates.length === 0){
      container.innerHTML = '<div class="calc-loading">暂无数据</div>';
      return;
    }

    // 取最近一个比赛日的场次
    var latestDate = oddsData.dates[oddsData.dates.length - 1];
    var matches = oddsData.matches_by_date[latestDate] || [];

    var html = '';
    for(var i = 0; i < matches.length; i++){
      html += renderMatchItem(matches[i]);
    }
    if(!html){
      container.innerHTML = '<div class="calc-loading">当前比赛日无在售场次</div>';
      return;
    }
    container.innerHTML = html;
  }

  function renderMatchItem(match){
    var odds = match.odds || {};
    var wantPlay = currentPlay === 'mixed' ? 'had' : currentPlay;
    // 该玩法未开售时，回退到第一个有赔率的玩法（混合过关/避免场次整体消失）
    var PLAY_ORDER = ['had','hhad','crs','ttg','hafu'];
    var playOdds = odds[wantPlay];
    var effPlay = wantPlay;
    if(!playOdds){
      for(var pi = 0; pi < PLAY_ORDER.length; pi++){
        if(odds[PLAY_ORDER[pi]]){ effPlay = PLAY_ORDER[pi]; playOdds = odds[PLAY_ORDER[pi]]; break; }
      }
    }
    if(!playOdds){
      return ''; // 该场所有玩法均无赔率，不显示
    }

    var singleAvail = getSingleAvailable(match, effPlay);
    var allupAvail = getAllupAvailable(match, effPlay);

    var singleBadge = singleAvail ? '<span class="calc-single-badge">单关</span>' : '';
    // 当前选中玩法无赔率、回退到其他玩法时，标注实际显示的玩法
    var playFallbackTag = effPlay !== wantPlay ? '<span class="calc-play-fallback">' + PLAY_NAMES[effPlay] + '</span>' : '';

    var oddsHtml = renderOddsButtons(match, effPlay, playOdds);

    var handicap = '';
    if(effPlay === 'hhad' && playOdds.goalLine){
      handicap = ' (让' + playOdds.goalLine + '球)';
    }

    return '<div class="calc-match-item" data-match-num="' + match.matchNum + '">' +
      '<div class="calc-match-header">' +
        '<div>' +
          '<span class="calc-match-id">' + (match.matchNumStr || '') + '</span>' +
          singleBadge + playFallbackTag +
        '</div>' +
        '<span class="calc-match-league">' + (match.league || '') + '</span>' +
      '</div>' +
      '<div class="calc-match-teams">' + match.home + ' vs ' + match.away + handicap + '</div>' +
      '<div style="font-size:.72rem;color:var(--text-muted);margin-bottom:4px">' + (match.kickoff || '') + '</div>' +
      oddsHtml +
    '</div>';
  }

  function renderOddsButtons(match, play, odds){
    var matchId = match.matchNum;
    var html = '<div class="calc-odds-grid">';

    if(play === 'had'){
      var sels = ['h','d','a'];
      html += '<div class="calc-odds-row">';
      for(var i = 0; i < sels.length; i++){
        var s = sels[i];
        var v = odds[s];
        var label = HAD_LABELS[s];
        var selClass = isSelected(matchId, play, s) ? ' selected' : '';
        var valStr = v ? fenToYuan(v) : '--';
        html += '<button class="calc-odds-btn' + selClass + '" onclick="toggleSelection(\'' + matchId + '\',\'' + play + '\',\'' + s + '\')">' +
          label + '<span class="odds-val">' + valStr + '</span></button>';
      }
      html += '</div>';
    }
    else if(play === 'hhad'){
      var sels = ['h','d','a'];
      html += '<div class="calc-odds-row">';
      for(var i = 0; i < sels.length; i++){
        var s = sels[i];
        var v = odds[s];
        var label = HHAD_LABELS[s];
        var selClass = isSelected(matchId, play, s) ? ' selected' : '';
        var valStr = v ? fenToYuan(v) : '--';
        html += '<button class="calc-odds-btn' + selClass + '" onclick="toggleSelection(\'' + matchId + '\',\'' + play + '\',\'' + s + '\')">' +
          label + '<span class="odds-val">' + valStr + '</span></button>';
      }
      html += '</div>';
    }
    else if(play === 'crs'){
      var scorePairs = [
        ['s00s00','0:0'],['s01s00','1:0'],['s02s00','2:0'],['s03s00','3:0'],['s04s00','4:0'],['s05s00','5:0'],
        ['s00s01','0:1'],['s01s01','1:1'],['s02s01','2:1'],['s03s01','3:1'],['s04s01','4:1'],['s05s01','5:1'],
        ['s00s02','0:2'],['s01s02','1:2'],['s02s02','2:2'],['s03s02','3:2'],['s04s02','4:2'],['s05s02','5:2'],
      ];
      html = '<div class="calc-odds-grid crs-grid">';
      for(var i = 0; i < scorePairs.length; i++){
        var key = scorePairs[i][0];
        var label = scorePairs[i][1];
        var v = odds[key];
        var selClass = isSelected(matchId, play, key) ? ' selected' : '';
        var valStr = v ? fenToYuan(v) : '--';
        html += '<button class="calc-odds-btn' + selClass + '" onclick="toggleSelection(\'' + matchId + '\',\'' + play + '\',\'' + key + '\')">' +
          label + '<span class="odds-val">' + valStr + '</span></button>';
      }
      // 其他比分
      var others = [['s1sh','胜其他'],['s1sd','平其他'],['s1sa','负其他']];
      for(var i = 0; i < others.length; i++){
        var key = others[i][0];
        var label = others[i][1];
        var v = odds[key];
        var selClass = isSelected(matchId, play, key) ? ' selected' : '';
        var valStr = v ? fenToYuan(v) : '--';
        html += '<button class="calc-odds-btn' + selClass + '" onclick="toggleSelection(\'' + matchId + '\',\'' + play + '\',\'' + key + '\')">' +
          label + '<span class="odds-val">' + valStr + '</span></button>';
      }
      html += '</div>';
    }
    else if(play === 'ttg'){
      html += '<div class="calc-odds-row">';
      for(var i = 0; i <= 7; i++){
        var key = String(i);
        var v = odds[key];
        var label = TTG_LABELS[key];
        var selClass = isSelected(matchId, play, key) ? ' selected' : '';
        var valStr = v ? fenToYuan(v) : '--';
        html += '<button class="calc-odds-btn' + selClass + '" onclick="toggleSelection(\'' + matchId + '\',\'' + play + '\',\'' + key + '\')">' +
          label + '<span class="odds-val">' + valStr + '</span></button>';
      }
      html += '</div>';
    }
    else if(play === 'hafu'){
      var pairs = [
        ['hh','胜胜'],['hd','胜平'],['ha','胜负'],
        ['dh','平胜'],['dd','平平'],['da','平负'],
        ['ah','负胜'],['ad','负平'],['aa','负负'],
      ];
      html = '<div class="calc-odds-grid" style="grid-template-columns:repeat(3,1fr)">';
      for(var i = 0; i < pairs.length; i++){
        var key = pairs[i][0];
        var label = pairs[i][1];
        var v = odds[key];
        var selClass = isSelected(matchId, play, key) ? ' selected' : '';
        var valStr = v ? fenToYuan(v) : '--';
        html += '<button class="calc-odds-btn' + selClass + '" onclick="toggleSelection(\'' + matchId + '\',\'' + play + '\',\'' + key + '\')">' +
          label + '<span class="odds-val">' + valStr + '</span></button>';
      }
      html += '</div>';
    }

    html += '</div>';
    return html;
  }

  // ─── 选/取消 选项 ───
  window.toggleSelection = function(matchNum, play, selection){
    var matchInfo = findMatch(matchNum);
    if(!matchInfo) return;

    var odds = matchInfo.odds[play];
    if(!odds || !odds[selection]) return;

    // 检查单关限制
    var singleAvail = getSingleAvailable(matchInfo, play);
    var allupAvail = getAllupAvailable(matchInfo, play);

    // 查找投注单中是否已有这场
    var slipItem = null;
    for(var i = 0; i < betSlip.length; i++){
      if(String(betSlip[i].matchId) === String(matchNum) && betSlip[i].play === play){
        slipItem = betSlip[i];
        break;
      }
    }

    if(!slipItem){
      // 新增
      slipItem = {
        matchId: matchNum,
        matchNumStr: matchInfo.matchNumStr || '',
        home: matchInfo.home,
        away: matchInfo.away,
        league: matchInfo.league || '',
        play: play,
        selections: [selection],
        oddsMap: {},
        singleAvailable: singleAvail,
        allupAvailable: allupAvail,
        handicap: play === 'hhad' ? (odds.goalLine || 0) : 0,
      };
      slipItem.oddsMap[selection] = odds[selection];
      betSlip.push(slipItem);
    } else {
      // 切换该选项
      var idx = slipItem.selections.indexOf(selection);
      if(idx >= 0){
        // 取消选择
        slipItem.selections.splice(idx, 1);
        delete slipItem.oddsMap[selection];
        if(slipItem.selections.length === 0){
          // 移除整行
          var pos = betSlip.indexOf(slipItem);
          if(pos >= 0) betSlip.splice(pos, 1);
        }
      } else {
        // 添加选项
        slipItem.selections.push(selection);
        slipItem.oddsMap[selection] = odds[selection];
      }
    }

    renderMatchList();
    renderBetSlip();
    updateBetSummary();
  };

  function isSelected(matchId, play, selection){
    for(var i = 0; i < betSlip.length; i++){
      if(String(betSlip[i].matchId) === String(matchId) && betSlip[i].play === play){
        return betSlip[i].selections.indexOf(selection) >= 0;
      }
    }
    return false;
  }

  function findMatch(matchNum){
    if(!oddsData || !oddsData.dates) return null;
    for(var d = 0; d < oddsData.dates.length; d++){
      var matches = oddsData.matches_by_date[oddsData.dates[d]] || [];
      for(var i = 0; i < matches.length; i++){
        if(String(matches[i].matchNum) === String(matchNum)){
          return matches[i];
        }
      }
    }
    return null;
  }

  // ─── 渲染投注单 ───
  function renderBetSlip(){
    var container = document.getElementById('bet-slip-items');
    if(betSlip.length === 0){
      container.innerHTML = '<div class="bet-slip-empty">暂未选场次<br><small>点击左侧场次的选项加入投注单</small></div>';
      return;
    }

    var html = '';
    for(var i = 0; i < betSlip.length; i++){
      var item = betSlip[i];
      var selLabels = item.selections.map(function(s){
        var sp = item.oddsMap[s];
        return getSelectionLabel(item.play, s) + (sp ? ' <span class="bsi-sp">' + fenToYuan(sp) + '</span>' : '');
      }).join('、');
      html += '<div class="bet-slip-item">' +
        '<div class="bsi-header">' +
          '<span class="bsi-match">' + item.matchNumStr + ' ' + item.home + ' vs ' + item.away + '</span>' +
          '<button class="bsi-remove" onclick="removeSlipItem(' + i + ')" title="移除">×</button>' +
        '</div>' +
        '<div class="bsi-detail">' +
          '<span class="bsi-selline">' + selLabels + '</span>' +
        '</div>' +
        '<div class="bsi-detail" style="margin-top:4px">' +
          '<span class="bsi-play">' + PLAY_NAMES[item.play] + '</span>' +
          '<span style="font-size:.72rem;color:' + (item.singleAvailable ? 'var(--success)' : 'var(--warn)') + '">' +
            (item.singleAvailable ? '✓ 可单关' : '⚠ 非单关') +
          '</span>' +
        '</div>' +
      '</div>';
    }
    container.innerHTML = html;
  }

  function getSelectionLabel(play, sel){
    if(play === 'had') return HAD_LABELS[sel] || sel;
    if(play === 'hhad') return HHAD_LABELS[sel] || sel;
    if(play === 'ttg') return TTG_LABELS[sel] || sel;
    if(play === 'hafu') return HAFU_LABELS[sel] || sel;
    if(play === 'crs'){
      if(sel === 's1sh') return '胜其他';
      if(sel === 's1sd') return '平其他';
      if(sel === 's1sa') return '负其他';
      // s02s01 → 2:1
      var m = sel.match(/s(\d{2})s(\d{2})/);
      if(m) return parseInt(m[1]) + ':' + parseInt(m[2]);
      return sel;
    }
    return sel;
  }

  window.removeSlipItem = function(idx){
    var item = betSlip[idx];
    if(!item) return;
    betSlip.splice(idx, 1);
    renderBetSlip();
    renderMatchList();
    updateBetSummary();
  };

  window.clearBetSlip = function(){
    betSlip = [];
    renderBetSlip();
    renderMatchList();
    updateBetSummary();
  };

  // ─── 倍数控制 ───
  window.changeMultiplier = function(delta){
    var input = document.getElementById('bet-multiplier');
    var val = parseInt(input.value) || 1;
    val = Math.max(1, Math.min(50, val + delta));
    input.value = val;
    multiplier = val;
    updateBetSummary();
  };

  // ─── 计算汇总 ───
  window.updateBetSummary = function(){
    var parlaySel = document.getElementById('bet-parlay-type');
    parlayType = parlaySel.value;

    var multInput = document.getElementById('bet-multiplier');
    multiplier = Math.max(1, Math.min(50, parseInt(multInput.value) || 1));
    multInput.value = multiplier;

    // 单关且多场 → 自动改为2串1提示
    if(parlayType === 'single' && betSlip.length > 1){
      parlaySel.value = 'parlay_2';
      parlayType = 'parlay_2';
    }

    var matchCount = betSlip.length;
    if(matchCount === 0){
      document.getElementById('summary-combos').textContent = '0 注';
      document.getElementById('summary-stake').textContent = '¥0.00';
      document.getElementById('summary-max-prize').textContent = '¥0.00';
      document.getElementById('summary-cap-note').style.display = 'none';
      return;
    }

    // 校验单关限制
    if(parlayType === 'single'){
      if(matchCount !== 1){
        // 不应该发生
      } else {
        if(!betSlip[0].singleAvailable){
          // 非单关场单独买 → 拦截提示
          document.getElementById('summary-combos').innerHTML = '<span style="color:var(--danger)">⚠ 该场未开售单关，需至少串2场</span>';
          document.getElementById('summary-stake').textContent = '—';
          document.getElementById('summary-max-prize').textContent = '—';
          document.getElementById('summary-cap-note').style.display = 'none';
          return;
        }
      }
    }

    // 计算组合数
    var combos = 1;
    for(var i = 0; i < betSlip.length; i++){
      combos *= betSlip[i].selections.length;
    }

    // 单关：1场多选项 = 多注
    // 串关：每场选项数相乘
    var totalCombos = combos;
    var stakeFen = totalCombos * UNIT_BET_FEN * multiplier;

    // 计算最高奖金（取每场最高赔率连乘）
    var maxOddsProduct = 1.0;
    for(var i = 0; i < betSlip.length; i++){
      var maxOdds = 0;
      var oddsMap = betSlip[i].oddsMap;
      for(var k in oddsMap){
        if(oddsMap[k] > maxOdds) maxOdds = oddsMap[k];
      }
      maxOddsProduct *= (maxOdds / 100.0);
    }

    var parlaySize = parlayType === 'single' ? 1 : parseInt(parlayType.split('_')[1]) || matchCount;
    var cap = PRIZE_CAPS[parlaySize] || PRIZE_CAP_6PLUS;

    // 理论最高奖金 = 最高赔率组合的奖金（1注最高）
    var maxPrizeFen = Math.round(maxOddsProduct * UNIT_BET_FEN * multiplier);
    var hitCap = maxPrizeFen > cap;
    if(hitCap) maxPrizeFen = cap;

    // 总最高奖金（如果有多个组合都命中，每个组合单独封顶再相加）
    // 简化：只显示单注最高奖金
    document.getElementById('summary-combos').textContent = totalCombos + ' 注';
    document.getElementById('summary-stake').textContent = '¥' + fenToYuan(stakeFen);
    document.getElementById('summary-max-prize').textContent = '¥' + fenToYuan(maxPrizeFen);
    document.getElementById('summary-cap-note').style.display = hitCap ? 'flex' : 'none';
  };

  // ─── 保存 / 导出 ───
  window.saveBetSlip = function(){
    if(betSlip.length === 0){
      alert('投注单为空');
      return;
    }
    var betData = {
      createdAt: new Date().toISOString(),
      parlayType: parlayType,
      multiplier: multiplier,
      matches: betSlip,
    };
    try{
      var saved = JSON.parse(localStorage.getItem('bet_slips') || '[]');
      saved.push(betData);
      localStorage.setItem('bet_slips', JSON.stringify(saved));
      alert('已保存到本地！共保存 ' + saved.length + ' 张投注单');
    }catch(e){
      alert('保存失败: ' + e.message);
    }
  };

  window.exportBetSlip = function(){
    if(betSlip.length === 0){
      alert('投注单为空');
      return;
    }
    var betData = {
      createdAt: new Date().toISOString(),
      parlayType: parlayType,
      multiplier: multiplier,
      matches: betSlip,
      totalCombos: parseInt(document.getElementById('summary-combos').textContent) || 0,
      maxPrizeYuan: parseFloat(document.getElementById('summary-max-prize').textContent.replace('¥','')),
    };
    var blob = new Blob([JSON.stringify(betData, null, 2)], {type:'application/json'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'bet_slip_' + Date.now() + '.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  // ─── 战绩统计 ───
  function loadStats(){
    loadJSON('data/bet_sim/stats.json', function(data){
      if(!data){
        statsData = null;
        renderStatsEmpty();
        return;
      }
      statsData = data;
      renderStatsOverview();
      renderPnlChart();
      renderGroupStats();
      loadRecentBets();
    });
  }

  function renderStatsEmpty(){
    document.getElementById('stat-total-stake').textContent = '¥0.00';
    document.getElementById('stat-total-return').textContent = '¥0.00';
    document.getElementById('stat-pnl').textContent = '¥0.00';
    document.getElementById('stat-roi').textContent = '0.00%';
    document.getElementById('stat-win-rate').textContent = '0%';
    document.getElementById('stat-pending').textContent = '0';
    document.getElementById('stats-group-body').innerHTML =
      '<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">暂无数据，运行模拟投注后将显示战绩</td></tr>';
  }

  function renderStatsOverview(){
    if(!statsData || !statsData.overall){
      renderStatsEmpty();
      return;
    }
    var o = statsData.overall;
    document.getElementById('stat-total-stake').textContent = '¥' + fenToYuan(o.total_stake_fen);
    document.getElementById('stat-total-return').textContent = '¥' + fenToYuan(o.total_return_fen);

    var pnlEl = document.getElementById('stat-pnl');
    var pnl = o.pnl_fen;
    pnlEl.textContent = (pnl >= 0 ? '+¥' : '-¥') + fenToYuan(Math.abs(pnl));
    pnlEl.style.color = pnl >= 0 ? 'var(--success)' : 'var(--danger)';

    document.getElementById('stat-roi').textContent = (o.roi_pct >= 0 ? '+' : '') + o.roi_pct + '%';
    document.getElementById('stat-roi').style.color = o.roi_pct >= 0 ? 'var(--success)' : 'var(--danger)';

    document.getElementById('stat-win-rate').textContent = o.win_rate_pct + '%';
    document.getElementById('stat-pending').textContent = o.pending_count || 0;
  }

  function renderPnlChart(){
    var canvas = document.getElementById('pnl-canvas');
    if(!canvas || !statsData || !statsData.last_30_curve || statsData.last_30_curve.length === 0){
      return;
    }
    var ctx = canvas.getContext('2d');
    var curve = statsData.last_30_curve;

    // 适配canvas尺寸
    var rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * 2;
    canvas.height = rect.height * 2;
    ctx.scale(2, 2);

    var w = rect.width;
    var h = rect.height;
    var padding = {top:20, right:10, bottom:24, left:50};
    var cw = w - padding.left - padding.right;
    var ch = h - padding.top - padding.bottom;

    // 计算Y范围
    var values = curve.map(function(d){ return d.cumulative_pnl_fen / 100; });
    var maxY = Math.max.apply(null, values.concat([0]));
    var minY = Math.min.apply(null, values.concat([0]));
    var range = maxY - minY || 1;
    maxY += range * 0.1;
    minY -= range * 0.1;

    // 绘制网格
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    ctx.font = '10px sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    for(var i = 0; i <= 4; i++){
      var y = padding.top + (ch / 4) * i;
      var val = maxY - (maxY - minY) * (i / 4);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(w - padding.right, y);
      ctx.stroke();
      ctx.fillText(val.toFixed(0), 4, y + 3);
    }
    // 零线
    var zeroY = padding.top + ch * ((maxY - 0) / (maxY - minY));
    ctx.strokeStyle = 'rgba(255,184,107,0.3)';
    ctx.beginPath();
    ctx.moveTo(padding.left, zeroY);
    ctx.lineTo(w - padding.right, zeroY);
    ctx.stroke();

    if(curve.length < 2) return;

    // 绘制曲线
    ctx.strokeStyle = 'var(--success, #62FAD3)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for(var i = 0; i < curve.length; i++){
      var x = padding.left + (cw / (curve.length - 1)) * i;
      var val = values[i];
      var y = padding.top + ch * ((maxY - val) / (maxY - minY));
      if(i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // 填充区域
    ctx.lineTo(padding.left + cw, zeroY);
    ctx.lineTo(padding.left, zeroY);
    ctx.closePath();
    ctx.fillStyle = 'rgba(98,250,211,0.1)';
    ctx.fill();

    // X轴日期标签（简化：只显示首尾）
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = '9px sans-serif';
    if(curve.length > 0){
      ctx.fillText(curve[0].date.slice(4), padding.left, h - 6);
      ctx.fillText(curve[curve.length-1].date.slice(4), w - padding.right - 30, h - 6);
    }
  }

  function renderGroupStats(){
    if(!statsData || !statsData.groups || statsData.groups.length === 0){
      document.getElementById('stats-group-body').innerHTML =
        '<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">暂无分组数据</td></tr>';
      return;
    }
    var html = '';
    for(var i = 0; i < statsData.groups.length; i++){
      var g = statsData.groups[i];
      var pnlClass = g.pnl_fen >= 0 ? 'win' : 'lose';
      var pnlSign = g.pnl_fen >= 0 ? '+' : '';
      html += '<tr>' +
        '<td>' + (g.play_name || g.play_type) + '</td>' +
        '<td>' + (g.parlay_name || g.parlay_type) + '</td>' +
        '<td>' + g.bet_count + '</td>' +
        '<td>' + g.win_rate_pct + '%</td>' +
        '<td>¥' + fenToYuan(g.total_stake_fen) + '</td>' +
        '<td>¥' + fenToYuan(g.total_return_fen) + '</td>' +
        '<td style="color:var(--' + pnlClass + ')">' + pnlSign + '¥' + fenToYuan(Math.abs(g.pnl_fen)) + '</td>' +
        '<td style="color:var(--' + pnlClass + ')">' + (g.roi_pct >= 0 ? '+' : '') + g.roi_pct + '%</td>' +
      '</tr>';
    }
    document.getElementById('stats-group-body').innerHTML = html;
  }

  function loadRecentBets(){
    loadJSON('data/bet_sim/bets.json', function(data){
      if(!data || !data.bets){
        document.getElementById('recent-bets-list').innerHTML =
          '<div class="calc-loading">暂无投注记录</div>';
        return;
      }
      betsData = data;
      renderRecentBets(data.bets.slice(0, 20));
    });
  }

  function renderRecentBets(bets){
    var container = document.getElementById('recent-bets-list');
    if(!bets || bets.length === 0){
      container.innerHTML = '<div class="calc-loading">暂无投注记录</div>';
      return;
    }

    var html = '';
    for(var i = 0; i < bets.length; i++){
      var b = bets[i];
      var isWin = b.win === 1 || b.win === true;
      var statusClass = '';
      var statusText = '';
      var pnlText = '';

      if(b.status === 'settled'){
        statusClass = isWin ? 'win' : 'lose';
        var pnl = b.pnl_fen || 0;
        pnlText = (pnl >= 0 ? '+' : '') + '¥' + fenToYuan(Math.abs(pnl));
        statusText = isWin ? '赢' : '输';
      } else {
        statusClass = 'pending';
        pnlText = '待结算';
        statusText = '待结算';
      }

      var matchDesc = '';
      if(b.matches && b.matches.length > 0){
        var m0 = b.matches[0];
        matchDesc = (m0.matchNumStr || m0.matchId) + ' ' + (m0.home || '') + ' vs ' + (m0.away || '');
        if(b.matches.length > 1){
          matchDesc += ' 等' + b.matches.length + '场';
        }
      }

      var playName = PLAY_NAMES[b.play_type] || b.play_type || '';
      var parlayName = PARLAY_NAMES[b.parlay_type] || b.parlay_type || '';

      html += '<div class="recent-bet-item">' +
        '<div class="rbi-info">' +
          '<div class="rbi-title">' + matchDesc + '</div>' +
          '<div class="rbi-meta">' +
            '<span>' + playName + '</span>' +
            '<span>' + parlayName + '</span>' +
            '<span>' + b.bet_date + '</span>' +
            '<span>' + b.combos + '注×' + b.multiplier + '倍</span>' +
          '</div>' +
        '</div>' +
        '<div class="rbi-pnl ' + statusClass + '">' + pnlText + '</div>' +
      '</div>';
    }
    container.innerHTML = html;
  }

  // ─── 自动模拟单 ───
  function loadAutoBetsDates(){
    var sel = document.getElementById('auto-bets-date-select');
    // 从predictions/bets目录加载（需要后端列目录，前端只能列已知文件）
    // 简化：加载latest和stats中出现的日期
    var dates = [];
    if(statsData && statsData.daily){
      for(var i = 0; i < statsData.daily.length; i++){
        if(statsData.daily[i].stat_date) dates.push(statsData.daily[i].stat_date);
      }
    }
    dates = dates.slice().reverse();
    if(dates.length === 0) dates = [new Date().toISOString().slice(0,10).replace(/-/g,'')];

    sel.innerHTML = '';
    for(var i = 0; i < dates.length; i++){
      var opt = document.createElement('option');
      opt.value = dates[i];
      opt.textContent = dates[i];
      sel.appendChild(opt);
    }
    if(dates.length > 0) loadAutoBets();
  }

  window.loadAutoBets = function(){
    var sel = document.getElementById('auto-bets-date-select');
    var date = sel.value;
    if(!date) return;

    var container = document.getElementById('auto-bets-list');
    container.innerHTML = '<div class="calc-loading">加载中...</div>';

    loadJSON('predictions/bets/' + date + '.json', function(data){
      if(!data || !data.bets || data.bets.length === 0){
        container.innerHTML = '<div class="calc-loading">当日无自动模拟单<br><small>赛前60分钟自动生成</small></div>';
        return;
      }

      var html = '';
      for(var i = 0; i < data.bets.length; i++){
        var b = data.bets[i];
        var parlayName = PARLAY_NAMES[b.parlay_type] || b.parlay_type;
        var playName = PLAY_NAMES[b.play_type] || b.play_type;

        var statusClass = 'pending';
        var statusText = '待结算';
        if(b.status === 'settled'){
          statusClass = (b.win ? 'win' : 'lose');
          statusText = b.win ? '已赢' : '已输';
        }

        var matchesHtml = '';
        if(b.matches){
          for(var j = 0; j < b.matches.length; j++){
            var m = b.matches[j];
            var selStr = (m.selections || []).join(',');
            matchesHtml += '<div class="auto-bet-match">' +
              '<span class="abm-teams">' + (m.matchNumStr || m.match_id) + ' ' + (m.home || '') + ' vs ' + (m.away || '') + '</span>' +
              '<span class="abm-sel">' + selStr + '</span>' +
            '</div>';
          }
        }

        html += '<div class="auto-bet-card">' +
          '<div class="auto-bet-header">' +
            '<span class="auto-bet-type">' + playName + ' · ' + parlayName + '</span>' +
            '<span class="auto-bet-status ' + statusClass + '">' + statusText + '</span>' +
          '</div>' +
          '<div class="auto-bet-matches">' + matchesHtml + '</div>' +
          '<div style="margin-top:10px;padding-top:8px;border-top:1px solid rgba(255,255,255,.06);font-size:.78rem;color:var(--text-dim);display:flex;justify-content:space-between">' +
            '<span>' + b.combos + '注 × ' + b.multiplier + '倍 = ¥' + fenToYuan(b.total_stake_fen) + '</span>' +
            '<span>最高奖 ¥' + fenToYuan(b.max_prize_fen) + '</span>' +
          '</div>' +
        '</div>';
      }
      container.innerHTML = html;
    });
  };

  // ─── 初始化 ───
  function init(){
    loadOddsData();

    // 恢复本地投注单
    try{
      var saved = localStorage.getItem('current_bet_slip');
      if(saved){
        var data = JSON.parse(saved);
        if(Array.isArray(data)) betSlip = data;
      }
      var savedMult = localStorage.getItem('bet_multiplier');
      if(savedMult){
        multiplier = parseInt(savedMult) || 1;
        var input = document.getElementById('bet-multiplier');
        if(input) input.value = multiplier;
      }
    }catch(e){}

    // 自动保存投注单
    setInterval(function(){
      try{
        localStorage.setItem('current_bet_slip', JSON.stringify(betSlip));
        localStorage.setItem('bet_multiplier', multiplier);
      }catch(e){}
    }, 5000);
  }

  // DOM加载后初始化
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
