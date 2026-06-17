/* AI Video Reader - Main Application (4-Panel Resizable Layout) */

class VideoReader {
  constructor() {
    this.api = window.api;
    this.ui = window.UI;
    this.apiBase = '/api';

    this.currentVideoId = null;
    this.currentConversationId = null;
    this.activeProviderId = null;
    this.videos = [];
    this.frames = [];
    this.conversations = [];
    this.providers = [];
    this.isStreaming = false;
    this.currentSSE = null;

    // 测试状态：{ [providerId]: { status, data } }
    this.testStatus = {};
    // 当前正在重命名的 convId
    this.renamingConvId = null;

    this._initElements();
    this._bindEvents();
    this._loadProviders();
    this._loadVideos();
    this._restorePanelWidths();
  }

  _initElements() {
    // Panel 1: sources
    this.videoList = document.getElementById('videoList');
    this.addSourceBtn = document.getElementById('addSourceBtn');
    this.manageProvidersBtn = document.getElementById('manageProvidersBtn');
    this.providerCountEl = document.getElementById('providerCount');

    // Panel 2: conversations
    this.newConvBtn = document.getElementById('newConvBtn');
    this.convList = document.getElementById('convList');
    this.convEmpty = document.getElementById('convEmpty');

    // Panel 3: chat
    this.welcomeState = document.getElementById('welcomeState');
    this.processingState = document.getElementById('processingState');
    this.processingSteps = document.getElementById('processingSteps');
    this.chatMessages = document.getElementById('chatMessages');
    this.chatInputArea = document.getElementById('chatInputArea');
    this.chatInput = document.getElementById('chatInput');
    this.chatSendBtn = document.getElementById('chatSendBtn');
    this.chatHeader = document.getElementById('chatHeader');
    this.currentVideoName = document.getElementById('currentVideoName');

    // Panel 4: details
    this.tabBtns = document.querySelectorAll('.tab-btn');
    this.framesGrid = document.getElementById('framesGrid');
    this.framesEmpty = document.getElementById('framesEmpty');
    this.transcriptContent = document.getElementById('transcriptContent');
    this.transcriptEmpty = document.getElementById('transcriptEmpty');

    // Panels + resize handles
    this.panelSources = document.getElementById('panelSources');
    this.panelConv = document.getElementById('panelConv');
    this.panelDetails = document.getElementById('panelDetails');
    this.handle1 = document.getElementById('resizeHandle1');
    this.handle2 = document.getElementById('resizeHandle2');
    this.handle3 = document.getElementById('resizeHandle3');

    // Modals
    this.imageModal = document.getElementById('imageModal');
    this.modalImg = document.getElementById('modalImg');
    this.modalClose = document.getElementById('modalClose');
    this.uploadModal = document.getElementById('uploadModal');
    this.dropZone = document.getElementById('dropZone');
    this.urlInput = document.getElementById('urlInput');
    this.uploadCancelBtn = document.getElementById('uploadCancelBtn');
    this.uploadConfirmBtn = document.getElementById('uploadConfirmBtn');
    this.fileInput = document.getElementById('fileInput');
    this.refreshBtn = document.getElementById('refreshBtn');

    // Providers modal
    this.providersModal = document.getElementById('providersModal');
    this.providersList = document.getElementById('providersList');
    this.providersEmpty = document.getElementById('providersEmpty');
    this.providersCloseBtn = document.getElementById('providersCloseBtn');
    this.providerAddBtn = document.getElementById('providerAddBtn');

    // Welcome buttons
    this.welcomeUploadBtn = document.getElementById('welcomeUploadBtn');
    this.welcomeUrlBtn = document.getElementById('welcomeUrlBtn');
  }

  _bindEvents() {
    // Upload
    this.addSourceBtn.addEventListener('click', () => this._showUploadModal());
    this.welcomeUploadBtn.addEventListener('click', () => this._showUploadModal());
    this.welcomeUrlBtn.addEventListener('click', () => this._showUploadModal(true));
    this.uploadCancelBtn.addEventListener('click', () => this._hideUploadModal());
    this.uploadConfirmBtn.addEventListener('click', () => this._confirmUpload());
    this.dropZone.addEventListener('click', () => this.fileInput.click());
    this.dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      this.dropZone.classList.add('dragover');
    });
    this.dropZone.addEventListener('dragleave', () => this.dropZone.classList.remove('dragover'));
    this.dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      this.dropZone.classList.remove('dragover');
      const file = e.dataTransfer.files[0];
      if (file) this._uploadFile(file);
    });
    this.fileInput.addEventListener('change', () => {
      const file = this.fileInput.files[0];
      this.fileInput.value = '';
      if (file) this._uploadFile(file);
    });

    // Refresh
    this.refreshBtn.addEventListener('click', () => this._loadVideos());

    // Providers modal
    this.manageProvidersBtn.addEventListener('click', () => this._showProvidersModal());
    this.providersCloseBtn.addEventListener('click', () => this._hideProvidersModal());
    this.providersModal.addEventListener('click', (e) => {
      if (e.target === this.providersModal) this._hideProvidersModal();
    });
    this.providerAddBtn.addEventListener('click', () => this._showProviderForm());

    // Tabs
    this.tabBtns.forEach(btn => {
      btn.addEventListener('click', () => this._switchTab(btn.dataset.tab));
    });

    // New conversation
    this.newConvBtn.addEventListener('click', () => this._createConversation());

    // Chat
    this.chatSendBtn.addEventListener('click', () => this._sendMessage());
    this.chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this._sendMessage();
      }
    });
    this.chatInput.addEventListener('input', () => {
      this.chatInput.style.height = 'auto';
      this.chatInput.style.height = Math.min(this.chatInput.scrollHeight, 120) + 'px';
    });

    // Image modal
    this.modalClose.addEventListener('click', () => this._hideImageModal());
    this.imageModal.addEventListener('click', (e) => {
      if (e.target === this.imageModal) this._hideImageModal();
    });

    // URL input Enter
    this.urlInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); this._confirmUpload(); }
    });

    // Resize handles
    this._initResize(this.handle1, this.panelSources, 'right');
    this._initResize(this.handle2, this.panelConv, 'right');
    this._initResize(this.handle3, this.panelDetails, 'left');
  }

  // =================== Resize Handlers ===================
  _initResize(handle, panel, side) {
    if (!handle || !panel) return;
    const startResize = (e) => {
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = panel.getBoundingClientRect().width;
      const min = parseInt(getComputedStyle(panel).minWidth) || 160;
      const max = parseInt(getComputedStyle(panel).maxWidth) || 1000;
      document.body.classList.add('is-resizing-columns');

      const onMove = (ev) => {
        const dx = ev.clientX - startX;
        const next = side === 'right' ? startWidth + dx : startWidth - dx;
        panel.style.width = `${Math.max(min, Math.min(max, next))}px`;
      };
      const onUp = () => {
        document.body.classList.remove('is-resizing-columns');
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        this._savePanelWidths();
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    };
    handle.addEventListener('mousedown', startResize);
  }

  _savePanelWidths() {
    try {
      localStorage.setItem('vr.panel.sources', this.panelSources.style.width || '');
      localStorage.setItem('vr.panel.conv', this.panelConv.style.width || '');
      localStorage.setItem('vr.panel.details', this.panelDetails.style.width || '');
    } catch (_) {}
  }

  _restorePanelWidths() {
    try {
      const s = localStorage.getItem('vr.panel.sources');
      const c = localStorage.getItem('vr.panel.conv');
      const d = localStorage.getItem('vr.panel.details');
      if (s) this.panelSources.style.width = s;
      if (c) this.panelConv.style.width = c;
      if (d) this.panelDetails.style.width = d;
    } catch (_) {}
  }

  // =================== Video ===================
  async _loadVideos() {
    try {
      this.videos = await this.api.listVideos();
      this.ui.renderVideoList(
        this.videoList, this.videos, this.currentVideoId,
        (id) => this._selectVideo(id),
        (id) => this._confirmDeleteVideo(id)
      );
    } catch (e) {
      console.error('Load videos failed:', e);
    }
  }

  async _selectVideo(videoId) {
    this.currentVideoId = videoId;
    this._loadVideos();

    try {
      const data = await this.api.getVideo(videoId);
      this.currentVideoName.textContent = data.video.name;
      this.frames = data.frames || [];
      this.conversations = data.conversations || [];
      this._renderConvList();
      this.chatHeader.style.display = 'flex';

      this.ui.renderFrames(
        this.framesGrid, this.framesEmpty, this.frames,
        videoId, this.apiBase, (url) => this._showImage(url)
      );

      const transcript = await this.api.getTranscript(videoId);
      this.ui.renderTranscript(
        this.transcriptContent, this.transcriptEmpty,
        transcript ? transcript.transcript : null
      );

      if (data.video.status === 'processing') {
        this._showProcessingState(data.video.progress_step || 'extracting_audio', data.video.progress_pct || 0);
        this._pollVideoStatus(videoId);
      } else if (data.video.status === 'error') {
        this._showChatState();
        this.ui.appendChatError(this.chatMessages, '处理失败: ' + (data.video.error_message || '未知错误'));
      } else {
        this._showChatState();
        if (this.conversations.length) {
          this._selectConversation(this.conversations[0].id);
        } else {
          this.chatMessages.innerHTML = '<div class="chat-empty">点击左侧"新对话"开始提问</div>';
        }
      }
    } catch (e) {
      console.error('Load video failed:', e);
    }
  }

  _showWelcomeState() {
    this.welcomeState.style.display = 'flex';
    this.processingState.style.display = 'none';
    this.chatMessages.style.display = 'none';
    this.chatInputArea.style.display = 'none';
    this.chatHeader.style.display = 'none';
    this.currentVideoId = null;
    this.currentConversationId = null;
    this.conversations = [];
    this._renderConvList();
  }

  _showProcessingState(step, progress) {
    this.welcomeState.style.display = 'none';
    this.processingState.style.display = 'flex';
    this.chatMessages.style.display = 'none';
    this.chatInputArea.style.display = 'none';
    this.ui.renderProcessingSteps(this.processingSteps, step, progress);
  }

  _showChatState() {
    this.welcomeState.style.display = 'none';
    this.processingState.style.display = 'none';
    this.chatMessages.style.display = 'flex';
    this.chatInputArea.style.display = 'block';
  }

  _switchTab(tabName) {
    this.tabBtns.forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    document.querySelectorAll('.tab-content').forEach(content => {
      content.classList.toggle('active', content.id === `${tabName}Tab`);
    });
  }

  _showImage(url) {
    this.modalImg.src = url;
    this.imageModal.classList.add('show');
  }

  _hideImageModal() {
    this.imageModal.classList.remove('show');
    this.modalImg.src = '';
  }

  _showUploadModal(focusUrl = false) {
    this.uploadModal.classList.add('show');
    this.urlInput.value = '';
    if (focusUrl) setTimeout(() => this.urlInput.focus(), 100);
  }

  _hideUploadModal() {
    this.uploadModal.classList.remove('show');
  }

  async _confirmUpload() {
    const url = this.urlInput.value.trim();
    if (url) await this._uploadUrl(url);
    this._hideUploadModal();
  }

  async _uploadFile(file) {
    this._hideUploadModal();
    try {
      const result = await this.api.uploadVideo(file);
      await this._loadVideos();
      this._selectVideo(result.video_id);
      this._pollVideoStatus(result.video_id);
    } catch (e) {
      alert('上传失败: ' + e.message);
    }
  }

  async _uploadUrl(url) {
    try {
      const result = await this.api.processUrl(url);
      await this._loadVideos();
      this._selectVideo(result.video_id);
      this._pollVideoStatus(result.video_id);
    } catch (e) {
      alert('处理失败: ' + e.message);
    }
  }

  _pollVideoStatus(videoId) {
    if (this.currentSSE) { this.currentSSE.close(); this.currentSSE = null; }
    this.currentSSE = this.api.subscribeProgress(
      videoId,
      (data) => {
        this.ui.updateVideoCardProgress(videoId, data.step, data.progress, data.step_label);
        this.ui.renderProcessingSteps(this.processingSteps, data.step, data.progress);
      },
      async (data) => {
        await this._loadVideos();
        if (this.currentVideoId === videoId) await this._selectVideo(videoId);
      },
      () => { this.currentSSE = null; }
    );
  }

  _confirmDeleteVideo(videoId) {
    const video = this.videos.find(v => v.id === videoId);
    if (!video) return;
    if (!confirm(`确定要删除 "${video.name}" 吗？相关的关键帧和转录文本也会被删除。`)) return;
    this.api.deleteVideo(videoId).then(() => {
      if (this.currentVideoId === videoId) this._showWelcomeState();
      this._loadVideos();
    });
  }

  // =================== Conversations ===================
  _renderConvList() {
    this.ui.renderConvList(
      this.convList, this.convEmpty,
      this.conversations, this.currentConversationId,
      (id) => this._selectConversation(id),
      (id, title) => this._renameConv(id, title),
      (id) => this._deleteConv(id)
    );
  }

  async _createConversation() {
    if (!this.currentVideoId) {
      alert('请先在左侧选择一个视频');
      return;
    }
    try {
      const result = await this.api.createConversation(this.currentVideoId);
      // 重新加载当前视频以刷新 conv 列表
      await this._selectVideo(this.currentVideoId);
      this._selectConversation(result.conversation_id);
    } catch (e) {
      console.error('Create conversation failed:', e);
    }
  }

  async _selectConversation(convId) {
    if (this.renamingConvId) return;  // 正在重命名时不切换
    this.currentConversationId = convId;
    this._renderConvList();
    try {
      const data = await this.api.getConversation(convId);
      this.ui.renderChatMessages(this.chatMessages, data.messages || []);
    } catch (e) {
      console.error('Load conversation failed:', e);
    }
  }

  async _renameConv(convId, newTitle) {
    try {
      await this.api.updateConversation(convId, { title: newTitle });
      const conv = this.conversations.find(c => c.id === convId);
      if (conv) conv.title = newTitle;
      this._renderConvList();
    } catch (e) {
      alert('重命名失败: ' + e.message);
      this._renderConvList();
    }
  }

  async _deleteConv(convId) {
    try {
      await this.api.deleteConversation(convId);
      this.conversations = this.conversations.filter(c => c.id !== convId);
      if (this.currentConversationId === convId) {
        this.currentConversationId = null;
        if (this.conversations.length) {
          this._selectConversation(this.conversations[0].id);
        } else {
          this.chatMessages.innerHTML = '<div class="chat-empty">点击"新对话"开始提问</div>';
        }
      }
      this._renderConvList();
    } catch (e) {
      alert('删除失败: ' + e.message);
    }
  }

  // =================== Providers ===================
  async _loadProviders() {
    try {
      const providers = await this.api.listProviders();
      this.providers = providers;
      // 保留用户已选；首次进入或选择已失效时回退到默认
      const stillExists = this.activeProviderId && providers.some(p => p.id === this.activeProviderId);
      if (!stillExists) {
        const def = providers.find(p => p.is_default) || providers[0];
        this.activeProviderId = def ? def.id : null;
      }
      if (this.providerCountEl) {
        this.providerCountEl.textContent = String(providers.length);
        this.providerCountEl.classList.toggle('zero', providers.length === 0);
      }
    } catch (e) {
      console.error('Load providers failed:', e);
    }
  }

  async _showProvidersModal() {
    await this._loadProviders();
    this._renderProviders();
    this.providersModal.classList.add('show');
  }

  _hideProvidersModal() {
    this.providersModal.classList.remove('show');
  }

  _renderProviders() {
    this.ui.renderProvidersList(
      this.providersList, this.providersEmpty, this.providers,
      this.activeProviderId,
      (id) => this._selectProvider(id),
      (id) => this._setDefaultProvider(id),
      (id) => this._showProviderForm(id),
      (id) => this._deleteProvider(id),
      (id) => this._testProvider(id)
    );
    this._refreshAllTestStatus();
  }

  _refreshAllTestStatus() {
    this.providers.forEach(p => {
      const statusEl = this.providersList.querySelector(`[data-test-status="${p.id}"]`);
      if (!statusEl) return;
      const s = this.testStatus[p.id];
      this.ui.renderTestStatus(statusEl, s ? s.status : 'idle', s ? s.data : null);
    });
  }

  async _setDefaultProvider(id) {
    try {
      await this.api.setDefaultProvider(id);
      await this._loadProviders();
      this._renderProviders();
    } catch (e) {
      alert('设置默认失败: ' + e.message);
    }
  }

  _selectProvider(id) {
    if (id === this.activeProviderId) return;
    this.activeProviderId = id;
    this._renderProviders();
  }

  async _testProvider(id) {
    // 立即在行内显示圈圈
    this.testStatus[id] = { status: 'testing' };
    this._refreshAllTestStatus();
    try {
      const result = await this.api.testProvider(id);
      this.testStatus[id] = { status: result.ok ? 'ok' : 'fail', data: result };
      this._refreshAllTestStatus();
    } catch (e) {
      this.testStatus[id] = { status: 'fail', data: { error: e.message, elapsed_ms: 0 } };
      this._refreshAllTestStatus();
    }
  }

  _showProviderForm(editId = null) {
    const existing = editId ? this.providers.find(p => p.id === editId) : null;
    this.ui.showProviderForm(this.providersList, existing, async (data) => {
      try {
        if (editId) await this.api.updateProvider(editId, data);
        else await this.api.createProvider(data);
        await this._loadProviders();
        this._renderProviders();
        return true;
      } catch (e) {
        alert((editId ? '更新' : '创建') + '失败: ' + e.message);
        return false;
      }
    });
  }

  async _deleteProvider(id) {
    const p = this.providers.find(x => x.id === id);
    if (!p) return;
    if (!confirm(`确定要删除 Provider "${p.name}" 吗？`)) return;
    try {
      await this.api.deleteProvider(id);
      await this._loadProviders();
      this._renderProviders();
    } catch (e) {
      alert('删除失败: ' + e.message);
    }
  }

  // =================== Chat ===================
  async _sendMessage() {
    const text = this.chatInput.value.trim();
    if (!text || this.isStreaming) return;
    if (!this.currentVideoId) {
      alert('请先在左侧选择一个视频');
      return;
    }

    if (!this.activeProviderId) {
      this.ui.appendChatError(this.chatMessages, '请先在左侧"AI Provider"中添加并设置默认 Provider');
      this._showProvidersModal();
      return;
    }

    if (!this.currentConversationId) {
      try {
        const result = await this.api.createConversation(this.currentVideoId);
        this.currentConversationId = result.conversation_id;
        const videoData = await this.api.getVideo(this.currentVideoId);
        this.conversations = videoData.conversations || [];
        this._renderConvList();
      } catch (e) {
        console.error('Auto-create conversation failed:', e);
        return;
      }
    }

    this.isStreaming = true;
    this.chatSendBtn.disabled = true;
    this.chatInput.value = '';
    this.chatInput.style.height = 'auto';

    this.ui.appendChatUser(this.chatMessages, text);
    const parts = this.ui.appendChatAssistant(this.chatMessages);

    let fullContent = '';

    try {
      await this.api.sendMessage(
        this.currentConversationId,
        text,
        this.activeProviderId,
        (chunk) => {
          fullContent += chunk;
          this.ui.updateChatAssistant(parts, fullContent);
        },
        () => {
          this.ui.finalizeChatAssistant(parts, fullContent || ' ');
          this._refreshConvListAfter();
        },
        (err) => {
          this.ui.appendChatError(this.chatMessages, '发送失败: ' + err);
        },
        (thinkingChunk) => {
          this.ui.appendThinking(parts, thinkingChunk);
        }
      );
    } catch (e) {
      this.ui.appendChatError(this.chatMessages, '发送失败: ' + e.message);
    } finally {
      this.isStreaming = false;
      this.chatSendBtn.disabled = false;
    }
  }

  async _refreshConvListAfter() {
    if (!this.currentVideoId) return;
    try {
      const data = await this.api.getVideo(this.currentVideoId);
      this.conversations = data.conversations || [];
      this._renderConvList();
    } catch (_) {}
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.vr = new VideoReader();
});
