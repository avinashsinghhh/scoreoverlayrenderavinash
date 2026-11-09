/**
 * Stream Like Counter Dashboard - Controller Script
 * Full dual-sync: Server API + LocalStorage + BroadcastChannel
 */

(function () {
  'use strict';

  // -------------------------------------------------------------------------
  // DOM References
  // -------------------------------------------------------------------------
  const statusBadge = document.getElementById('status-badge');
  const statusText = document.getElementById('status-text');
  const obsUrlInput = document.getElementById('obs-url-input');
  const btnCopyObs = document.getElementById('btn-copy-obs');

  // Track Mode Tabs
  const tabModeChannel = document.getElementById('tab-mode-channel');
  const tabModeUrl = document.getElementById('tab-mode-url');
  const sectionChannelMode = document.getElementById('section-channel-mode');
  const sectionUrlMode = document.getElementById('section-url-mode');

  // Channel Mode Controls
  const inputChannelHandle = document.getElementById('input-channel-handle');
  const btnSaveChannel = document.getElementById('btn-save-channel');
  const btnDetectNow = document.getElementById('btn-detect-now');

  // URL Mode Controls
  const inputYtUrl = document.getElementById('input-yt-url');
  const btnSaveStream = document.getElementById('btn-save-stream');
  const btnPollNow = document.getElementById('btn-poll-now');

  // Toggle & API Key
  const toggleAutoupdate = document.getElementById('toggle-autoupdate');
  const labelAutoupdate = document.getElementById('label-autoupdate');
  const inputApiKey = document.getElementById('input-api-key');
  const btnSaveKey = document.getElementById('btn-save-key');

  // Live Stream Status Card
  const streamInfoCard = document.getElementById('stream-info-card');
  const streamBadgeStatus = document.getElementById('stream-badge-status');
  const streamTitleText = document.getElementById('stream-title-text');
  const streamInfoDetails = document.getElementById('stream-info-details');
  const streamInfoMeta = document.getElementById('stream-info-meta');

  // Score & Steppers
  const displayLikesNumber = document.getElementById('display-likes-number');
  const btnResetLikes = document.getElementById('btn-reset-likes');
  const btnAdd1 = document.getElementById('btn-add-1');
  const btnAdd5 = document.getElementById('btn-add-5');
  const btnAdd10 = document.getElementById('btn-add-10');
  const btnSub1 = document.getElementById('btn-sub-1');
  const btnSub5 = document.getElementById('btn-sub-5');
  const inputDirectLikes = document.getElementById('input-direct-likes');
  const btnSetDirect = document.getElementById('btn-set-direct');

  // Goal & Milestone
  const inputGoalTarget = document.getElementById('input-goal-target');
  const inputGoalStep = document.getElementById('input-goal-step');
  const inputRewardText = document.getElementById('input-reward-text');
  const toggleAutobump = document.getElementById('toggle-autobump');

  // Live Preview & Test Controls
  const previewIframe = document.getElementById('preview-iframe');
  const btnTestLike = document.getElementById('btn-test-like');
  const btnTestGoal = document.getElementById('btn-test-goal');
  const btnToggleDemo = document.getElementById('btn-toggle-demo');

  // Appearance & Settings
  const selectLayout = document.getElementById('select-layout');
  const selectTheme = document.getElementById('select-theme');
  const selectIcon = document.getElementById('select-icon');
  const selectPoll = document.getElementById('select-poll');

  const togglePercentage = document.getElementById('toggle-percentage');
  const toggleGoal = document.getElementById('toggle-goal');
  const toggleRemaining = document.getElementById('toggle-remaining');
  const toggleSound = document.getElementById('toggle-sound');

  const sliderScale = document.getElementById('slider-scale');
  const valScale = document.getElementById('val-scale');
  const sliderVolume = document.getElementById('slider-volume');
  const valVolume = document.getElementById('val-volume');

  // -------------------------------------------------------------------------
  // Default State
  // -------------------------------------------------------------------------
  let state = {
    likes: 0,
    goal: 50,
    goalStep: 50,
    autoBumpGoal: true,
    rewardText: 'LIKE GOAL',
    channelHandle: '',
    trackMode: 'channel', // 'channel' or 'url'
    youtubeUrl: '',
    videoId: '',
    isLive: false,
    apiKey: '',
    autoUpdate: true,
    pollInterval: 5,
    lastPolled: null,
    lastUpdated: null,
    status: 'ready',
    statusMessage: 'Ready. Set your YouTube Channel handle to auto-track live streams.',
    streamTitle: '',
    settings: {
      layout: 'bar',
      theme: 'youtube',
      icon: 'thumb',
      soundEnabled: true,
      soundVolume: 0.5,
      scale: 100,
      showPercentage: true,
      showGoal: true,
      showRemaining: true,
      accentColor: '#ff0033'
    }
  };

  let demoInterval = null;
  let pollIntervalTimer = null;
  let isServerRunning = false;

  // BroadcastChannel for instant zero-latency cross-tab sync
  const channel = window.BroadcastChannel ? new BroadcastChannel('stream_likes_channel') : null;

  // -------------------------------------------------------------------------
  // Helper: Extract Video ID or Channel Handle
  // -------------------------------------------------------------------------
  function extractYouTubeIdentifier(urlOrId) {
    if (!urlOrId) return { type: null, value: '' };
    const str = urlOrId.trim();

    if (/^[a-zA-Z0-9_-]{11}$/.test(str)) {
      return { type: 'video_id', value: str };
    }

    if (str.startsWith('@') || str.includes('youtube.com/@')) {
      const match = str.match(/@([a-zA-Z0-9_.-]+)/);
      if (match) {
        return { type: 'channel', value: `@${match[1]}` };
      }
    }

    try {
      const parsed = new URL(str.startsWith('http') ? str : `https://${str}`);
      if (parsed.hostname.includes('youtu.be')) {
        return { type: 'video_id', value: parsed.pathname.slice(1).split('/')[0] };
      }
      if (parsed.pathname.includes('/live/')) {
        return { type: 'video_id', value: parsed.pathname.split('/live/')[1].split('/')[0] };
      }
      if (parsed.searchParams.has('v')) {
        return { type: 'video_id', value: parsed.searchParams.get('v') };
      }
      if (parsed.pathname.startsWith('/@')) {
        const handle = parsed.pathname.split('/')[1];
        return { type: 'channel', value: handle };
      }
    } catch (e) {}

    return { type: 'raw', value: str };
  }

  // -------------------------------------------------------------------------
  // State Sync
  // -------------------------------------------------------------------------
  function broadcastState() {
    if (channel) {
      channel.postMessage({ type: 'state_update', state });
    }

    try {
      localStorage.setItem('stream_likes_state', JSON.stringify(state));
    } catch (e) {}

    saveStateToServer();
  }

  async function saveStateToServer() {
    try {
      await fetch('/api/likes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(state)
      });
    } catch (e) {}
  }

  // -------------------------------------------------------------------------
  // UI Update
  // -------------------------------------------------------------------------
  function updateUI() {
    // Top status indicator
    statusBadge.className = 'status-indicator';
    if (state.isLive) {
      statusBadge.classList.add('active');
      statusText.textContent = 'LIVE NOW';
    } else if (state.autoUpdate) {
      statusBadge.classList.add('polling');
      statusText.textContent = state.channelHandle ? `Monitoring ${state.channelHandle}` : 'Auto-Tracking Active';
    } else {
      statusBadge.classList.add('idle');
      statusText.textContent = 'Ready';
    }

    // Likes number display
    displayLikesNumber.textContent = (state.likes || 0).toLocaleString();

    // Auto-update toggle
    toggleAutoupdate.checked = !!state.autoUpdate;
    labelAutoupdate.textContent = state.autoUpdate ? 'Auto-Fetch: ON' : 'Auto-Fetch: OFF';

    // Track Mode Tabs
    if (state.trackMode === 'url') {
      tabModeUrl.classList.add('active');
      tabModeChannel.classList.remove('active');
      sectionUrlMode.style.display = 'block';
      sectionChannelMode.style.display = 'none';
    } else {
      tabModeChannel.classList.add('active');
      tabModeUrl.classList.remove('active');
      sectionChannelMode.style.display = 'block';
      sectionUrlMode.style.display = 'none';
    }

    // Inputs
    inputChannelHandle.value = state.channelHandle || '';
    inputYtUrl.value = state.youtubeUrl || '';
    inputApiKey.value = state.apiKey || '';
    inputGoalTarget.value = state.goal || 50;
    inputGoalStep.value = state.goalStep || 50;
    inputRewardText.value = state.rewardText || 'LIKE GOAL';
    toggleAutobump.checked = state.autoBumpGoal !== false;

    // Appearance
    selectLayout.value = state.settings.layout || 'bar';
    selectTheme.value = state.settings.theme || 'youtube';
    selectIcon.value = state.settings.icon || 'thumb';
    selectPoll.value = state.pollInterval || 5;

    togglePercentage.checked = state.settings.showPercentage !== false;
    toggleGoal.checked = state.settings.showGoal !== false;
    toggleRemaining.checked = state.settings.showRemaining !== false;
    toggleSound.checked = state.settings.soundEnabled !== false;

    sliderScale.value = state.settings.scale || 100;
    valScale.textContent = `${sliderScale.value}%`;

    sliderVolume.value = Math.round((state.settings.soundVolume ?? 0.5) * 100);
    valVolume.textContent = `${sliderVolume.value}%`;

    // Stream info card
    renderStreamStatusCard();
  }

  function renderStreamStatusCard() {
    if (state.trackMode === 'channel') {
      if (!state.channelHandle) {
        streamBadgeStatus.className = 'stream-badge-live standby';
        streamBadgeStatus.textContent = 'NO CHANNEL';
        streamTitleText.textContent = 'Enter your YouTube Channel handle above';
        streamInfoDetails.textContent = 'Set your channel handle (e.g. @YourName) to start auto-tracking.';
        streamInfoMeta.textContent = 'Zero setup: Automatically hooks into your streams whenever you go live.';
        return;
      }

      if (state.isLive) {
        streamBadgeStatus.className = 'stream-badge-live live';
        streamBadgeStatus.textContent = '🔴 LIVE NOW';
        streamTitleText.textContent = state.streamTitle || 'Livestream Active';
        streamInfoDetails.textContent = `👍 ${state.likes.toLocaleString()} Likes · ID: ${state.videoId || 'active'}`;
        streamInfoMeta.textContent = `Channel: ${state.channelHandle} · Automatically updating every ${state.pollInterval}s`;
      } else {
        streamBadgeStatus.className = 'stream-badge-live standby';
        streamBadgeStatus.textContent = '🟡 STANDBY';
        streamTitleText.textContent = `Waiting for ${state.channelHandle} to go live...`;
        streamInfoDetails.textContent = 'Start streaming in OBS — the overlay will automatically detect it and show your likes!';
        streamInfoMeta.textContent = state.lastPolled
          ? `Last checked: ${new Date(state.lastPolled * 1000).toLocaleTimeString()} (Checking every ${state.pollInterval}s)`
          : `Standing by · Checking channel every ${state.pollInterval}s`;
      }
    } else {
      // Specific URL mode
      if (state.streamTitle || state.videoId) {
        streamBadgeStatus.className = state.isLive ? 'stream-badge-live live' : 'stream-badge-live standby';
        streamBadgeStatus.textContent = state.isLive ? '🔴 LIVE' : 'TRACKING';
        streamTitleText.textContent = state.streamTitle || `Video ID: ${state.videoId}`;
        streamInfoDetails.textContent = `👍 ${state.likes.toLocaleString()} Likes · ID: ${state.videoId}`;
        streamInfoMeta.textContent = state.lastPolled
          ? `Last checked: ${new Date(state.lastPolled * 1000).toLocaleTimeString()}`
          : 'Ready';
      } else {
        streamBadgeStatus.className = 'stream-badge-live standby';
        streamBadgeStatus.textContent = 'STANDBY';
        streamTitleText.textContent = 'Enter a YouTube stream URL or Video ID above';
        streamInfoDetails.textContent = 'Paste any livestream URL to track its likes.';
        streamInfoMeta.textContent = 'Ready';
      }
    }
  }

  // -------------------------------------------------------------------------
  // Channel Livestream Auto-Detect Engine
  // -------------------------------------------------------------------------
  async function detectChannelLivestream() {
    if (!state.channelHandle) {
      state.statusMessage = 'Enter your YouTube Channel handle (e.g. @YourName)';
      updateUI();
      return;
    }

    try {
      const res = await fetch('/api/likes/detect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel: state.channelHandle,
          apiKey: state.apiKey
        })
      });

      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          state.isLive = !!data.isLive;
          state.channelHandle = data.handle || state.channelHandle;
          state.lastPolled = Math.floor(Date.now() / 1000);

          if (data.isLive) {
            handleNewLikeCount(data.likes, data.title, data.videoId, true);
          } else {
            state.status = 'standby';
            state.statusMessage = `Waiting for ${state.channelHandle} to go live...`;
            updateUI();
            broadcastState();
          }
          return;
        }
      }
    } catch (e) {
      // Offline fallback
    }

    state.lastPolled = Math.floor(Date.now() / 1000);
    updateUI();
  }

  // -------------------------------------------------------------------------
  // Fetch Specific Live Stream URL
  // -------------------------------------------------------------------------
  async function fetchLiveLikes() {
    const ident = extractYouTubeIdentifier(state.youtubeUrl);
    if (!ident.value) {
      state.statusMessage = 'Enter a valid YouTube URL or Video ID';
      updateUI();
      return;
    }

    try {
      const res = await fetch('/api/likes/youtube', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: state.youtubeUrl,
          identifier: ident.value,
          identifierType: ident.type,
          apiKey: state.apiKey
        })
      });

      if (res.ok) {
        const data = await res.json();
        if (data.success && typeof data.likes === 'number') {
          handleNewLikeCount(data.likes, data.title, data.videoId, data.isLive ?? true);
          return;
        }
      }
    } catch (e) {}

    // Client-side fallback if API key present
    if (state.apiKey && ident.type === 'video_id') {
      try {
        const apiUrl = `https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id=${ident.value}&key=${state.apiKey}`;
        const resp = await fetch(apiUrl);
        if (resp.ok) {
          const ytData = await resp.json();
          if (ytData.items && ytData.items.length > 0) {
            const item = ytData.items[0];
            const likeCount = parseInt(item.statistics.likeCount, 10) || 0;
            const title = item.snippet.title;
            const isLive = item.snippet.liveBroadcastContent === 'live';
            handleNewLikeCount(likeCount, title, ident.value, isLive);
            return;
          }
        }
      } catch (err) {}
    }
  }

  function handleNewLikeCount(newLikes, title, videoId, isLive = true) {
    state.likes = newLikes;
    state.isLive = isLive;
    if (title) state.streamTitle = title;
    if (videoId) state.videoId = videoId;
    state.lastPolled = Math.floor(Date.now() / 1000);
    state.lastUpdated = Math.floor(Date.now() / 1000);
    state.status = isLive ? 'live' : 'active';

    if (state.autoBumpGoal && state.likes >= state.goal) {
      const step = state.goalStep || 50;
      let newGoal = state.goal;
      while (newGoal <= state.likes) {
        newGoal += step;
      }
      state.goal = newGoal;
    }

    state.statusMessage = isLive
      ? `LIVE NOW: ${newLikes.toLocaleString()} likes (${state.streamTitle || 'Livestream'})`
      : `Tracking: ${newLikes.toLocaleString()} likes`;

    updateUI();
    broadcastState();
  }

  // -------------------------------------------------------------------------
  // Auto-Update Polling Timer
  // -------------------------------------------------------------------------
  function setupPollingTimer() {
    if (pollIntervalTimer) clearInterval(pollIntervalTimer);
    if (!state.autoUpdate) return;

    const intervalMs = Math.max(3000, (state.pollInterval || 5) * 1000);
    pollIntervalTimer = setInterval(() => {
      if (!state.autoUpdate) return;

      if (state.trackMode === 'channel' && state.channelHandle) {
        detectChannelLivestream();
      } else if (state.trackMode === 'url' && state.youtubeUrl) {
        fetchLiveLikes();
      }
    }, intervalMs);
  }

  // -------------------------------------------------------------------------
  // Event Listeners: Track Mode Tabs
  // -------------------------------------------------------------------------
  tabModeChannel.addEventListener('click', () => {
    state.trackMode = 'channel';
    updateUI();
    broadcastState();
    if (state.channelHandle && state.autoUpdate) detectChannelLivestream();
  });

  tabModeUrl.addEventListener('click', () => {
    state.trackMode = 'url';
    updateUI();
    broadcastState();
    if (state.youtubeUrl && state.autoUpdate) fetchLiveLikes();
  });

  // Channel Save & Detect
  btnSaveChannel.addEventListener('click', () => {
    let raw = inputChannelHandle.value.trim();
    if (!raw) {
      alert('Please enter your YouTube Channel handle (e.g. @YourName or youtube.com/@YourName)');
      return;
    }
    if (!raw.startsWith('@') && !raw.includes('/')) {
      raw = `@${raw}`;
    }
    state.channelHandle = raw;
    state.trackMode = 'channel';
    state.autoUpdate = true;
    toggleAutoupdate.checked = true;
    state.statusMessage = `Connecting to channel ${state.channelHandle}...`;
    updateUI();
    broadcastState();
    setupPollingTimer();
    detectChannelLivestream();
  });

  inputChannelHandle.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') btnSaveChannel.click();
  });

  btnDetectNow.addEventListener('click', () => {
    if (!inputChannelHandle.value.trim()) {
      alert('Please enter a channel handle first (e.g. @YourName)');
      return;
    }
    state.channelHandle = inputChannelHandle.value.trim();
    detectChannelLivestream();
  });

  // Specific URL Save & Poll
  btnSaveStream.addEventListener('click', () => {
    state.youtubeUrl = inputYtUrl.value.trim();
    state.trackMode = 'url';
    state.autoUpdate = true;
    toggleAutoupdate.checked = true;
    updateUI();
    broadcastState();
    setupPollingTimer();
    fetchLiveLikes();
  });

  inputYtUrl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') btnSaveStream.click();
  });

  btnPollNow.addEventListener('click', () => {
    fetchLiveLikes();
  });

  // Auto-Update Toggle
  toggleAutoupdate.addEventListener('change', () => {
    state.autoUpdate = toggleAutoupdate.checked;
    state.statusMessage = state.autoUpdate ? 'Auto-tracking active' : 'Auto-tracking paused';
    updateUI();
    broadcastState();
    setupPollingTimer();
    if (state.autoUpdate) {
      if (state.trackMode === 'channel') detectChannelLivestream();
      else fetchLiveLikes();
    }
  });

  // API Key Save
  btnSaveKey.addEventListener('click', () => {
    state.apiKey = inputApiKey.value.trim();
    updateUI();
    broadcastState();
    alert('YouTube Data API key saved!');
  });

  // -------------------------------------------------------------------------
  // Manual Score Adjustments & Steppers
  // -------------------------------------------------------------------------
  function modifyLikes(delta) {
    state.likes = Math.max(0, (state.likes || 0) + delta);

    if (state.autoBumpGoal && state.likes >= state.goal) {
      const step = state.goalStep || 50;
      let newGoal = state.goal;
      while (newGoal <= state.likes) {
        newGoal += step;
      }
      state.goal = newGoal;
    }

    updateUI();
    broadcastState();
  }

  btnAdd1.addEventListener('click', () => modifyLikes(1));
  btnAdd5.addEventListener('click', () => modifyLikes(5));
  btnAdd10.addEventListener('click', () => modifyLikes(10));
  btnSub1.addEventListener('click', () => modifyLikes(-1));
  btnSub5.addEventListener('click', () => modifyLikes(-5));

  btnSetDirect.addEventListener('click', () => {
    const val = parseInt(inputDirectLikes.value, 10);
    if (!isNaN(val) && val >= 0) {
      state.likes = val;
      inputDirectLikes.value = '';
      if (state.autoBumpGoal && state.likes >= state.goal) {
        const step = state.goalStep || 50;
        let newGoal = state.goal;
        while (newGoal <= state.likes) {
          newGoal += step;
        }
        state.goal = newGoal;
      }
      updateUI();
      broadcastState();
    }
  });

  inputDirectLikes.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') btnSetDirect.click();
  });

  btnResetLikes.addEventListener('click', () => {
    if (confirm('Reset stream like counter to 0?')) {
      state.likes = 0;
      updateUI();
      broadcastState();
    }
  });

  // -------------------------------------------------------------------------
  // Goal Settings
  // -------------------------------------------------------------------------
  inputGoalTarget.addEventListener('change', () => {
    state.goal = Math.max(1, parseInt(inputGoalTarget.value, 10) || 50);
    broadcastState();
  });

  inputGoalStep.addEventListener('change', () => {
    state.goalStep = Math.max(1, parseInt(inputGoalStep.value, 10) || 50);
    broadcastState();
  });

  inputRewardText.addEventListener('input', () => {
    state.rewardText = inputRewardText.value;
    broadcastState();
  });

  toggleAutobump.addEventListener('change', () => {
    state.autoBumpGoal = toggleAutobump.checked;
    broadcastState();
  });

  // -------------------------------------------------------------------------
  // Appearance & Settings
  // -------------------------------------------------------------------------
  selectLayout.addEventListener('change', () => {
    state.settings.layout = selectLayout.value;
    broadcastState();
  });

  selectTheme.addEventListener('change', () => {
    state.settings.theme = selectTheme.value;
    broadcastState();
  });

  selectIcon.addEventListener('change', () => {
    state.settings.icon = selectIcon.value;
    broadcastState();
  });

  selectPoll.addEventListener('change', () => {
    state.pollInterval = parseInt(selectPoll.value, 10) || 5;
    broadcastState();
    setupPollingTimer();
  });

  togglePercentage.addEventListener('change', () => {
    state.settings.showPercentage = togglePercentage.checked;
    broadcastState();
  });

  toggleGoal.addEventListener('change', () => {
    state.settings.showGoal = toggleGoal.checked;
    broadcastState();
  });

  toggleRemaining.addEventListener('change', () => {
    state.settings.showRemaining = toggleRemaining.checked;
    broadcastState();
  });

  toggleSound.addEventListener('change', () => {
    state.settings.soundEnabled = toggleSound.checked;
    broadcastState();
  });

  sliderScale.addEventListener('input', () => {
    const val = parseInt(sliderScale.value, 10);
    state.settings.scale = val;
    valScale.textContent = `${val}%`;
    broadcastState();
  });

  sliderVolume.addEventListener('input', () => {
    const val = parseInt(sliderVolume.value, 10);
    state.settings.soundVolume = val / 100;
    valVolume.textContent = `${val}%`;
    broadcastState();
  });

  // -------------------------------------------------------------------------
  // Test Controls & Demo Simulation
  // -------------------------------------------------------------------------
  btnTestLike.addEventListener('click', () => {
    if (channel) {
      channel.postMessage({ type: 'test_like' });
    }
    modifyLikes(1);
  });

  btnTestGoal.addEventListener('click', () => {
    if (channel) {
      channel.postMessage({ type: 'test_goal' });
    }
  });

  btnToggleDemo.addEventListener('click', () => {
    if (demoInterval) {
      clearInterval(demoInterval);
      demoInterval = null;
      btnToggleDemo.classList.remove('active-demo');
      btnToggleDemo.textContent = '⚡ Demo Mode: OFF';
    } else {
      btnToggleDemo.classList.add('active-demo');
      btnToggleDemo.textContent = '⚡ Demo Mode: ON (Simulating)';
      demoInterval = setInterval(() => {
        modifyLikes(1);
      }, 5000);
    }
  });

  // -------------------------------------------------------------------------
  // Copy OBS URL Button
  // -------------------------------------------------------------------------
  btnCopyObs.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(obsUrlInput.value);
      const originalText = btnCopyObs.textContent;
      btnCopyObs.textContent = '✅ Copied to Clipboard!';
      setTimeout(() => {
        btnCopyObs.textContent = originalText;
      }, 2000);
    } catch (e) {
      obsUrlInput.select();
      document.execCommand('copy');
      alert('OBS URL copied!');
    }
  });

  function updateObsUrlDisplay() {
    const loc = window.location;
    if (loc.protocol.startsWith('http')) {
      obsUrlInput.value = `${loc.protocol}//${loc.host}/likes-overlay.html`;
    } else {
      obsUrlInput.value = 'likes-overlay.html';
    }
  }

  // -------------------------------------------------------------------------
  // Load State from LocalStorage / Server
  // -------------------------------------------------------------------------
  function loadLocalState() {
    try {
      const saved = localStorage.getItem('stream_likes_state');
      if (saved) {
        const parsed = JSON.parse(saved);
        state = {
          ...state,
          ...parsed,
          settings: { ...state.settings, ...parsed.settings }
        };
      }
    } catch (e) {}
  }

  async function loadServerState() {
    try {
      const res = await fetch('/api/likes', { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        if (data && typeof data.likes === 'number') {
          isServerRunning = true;
          state = {
            ...state,
            ...data,
            settings: { ...state.settings, ...data.settings }
          };
          updateUI();
          setupPollingTimer();
        }
      }
    } catch (e) {}
  }

  // -------------------------------------------------------------------------
  // Init
  // -------------------------------------------------------------------------
  loadLocalState();
  updateObsUrlDisplay();
  updateUI();
  setupPollingTimer();
  loadServerState();

  setInterval(loadServerState, 6000);
})();
