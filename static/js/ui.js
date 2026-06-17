/* UI Rendering Functions */

const UI = {
  // 处理步骤定义
  PROCESSING_STEPS: [
    { key: 'extracting_audio', label: '提取音频' },
    { key: 'splitting_audio', label: '音频分段' },
    { key: 'transcribing', label: '语音转录' },
    { key: 'extracting_frames', label: '提取关键帧' },
    { key: 'finalizing', label: '整理结果' },
    { key: 'indexing', label: '构建阅读索引' },
  ],

  // 转义 HTML
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  splitThinkContent(text) {
    const startTag = '<think>';
    const endTag = '</think>';
    const source = text || '';
    const answerParts = [];
    const thinkingParts = [];
    let pos = 0;

    while (pos < source.length) {
      const start = source.indexOf(startTag, pos);
      if (start === -1) {
        answerParts.push(source.slice(pos));
        break;
      }
      answerParts.push(source.slice(pos, start));
      const thinkingStart = start + startTag.length;
      const end = source.indexOf(endTag, thinkingStart);
      if (end === -1) {
        thinkingParts.push(source.slice(thinkingStart));
        pos = source.length;
      } else {
        thinkingParts.push(source.slice(thinkingStart, end));
        pos = end + endTag.length;
      }
    }

    return {
      thinking: thinkingParts.join('\n\n').trim(),
      content: answerParts.join('').trimStart(),
    };
  },

  createCopyButton(text) {
    const btn = document.createElement('button');
    btn.className = 'bubble-action';
    btn.title = '复制';
    btn.innerHTML = '<i class="far fa-copy"></i>';
    btn.dataset.copyText = text || '';
    btn.addEventListener('click', () => this.copyFromButton(btn));
    return btn;
  },

  copyFromButton(btn) {
    const text = btn.dataset.copyText || '';
    const markCopied = () => {
      btn.classList.add('copied');
      btn.innerHTML = '<i class="fas fa-check"></i>';
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.innerHTML = '<i class="far fa-copy"></i>';
      }, 1200);
    };

    if (window.navigator?.clipboard && window.isSecureContext) {
      window.navigator.clipboard.writeText(text).then(markCopied, () => {
        if (this.copyWithTextArea(text)) markCopied();
      });
    } else if (this.copyWithTextArea(text)) {
      markCopied();
    }
  },

  copyWithTextArea(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    const ok = document.execCommand('copy');
    textarea.remove();
    return ok;
  },

  // 格式化时长
  formatDuration(seconds) {
    if (!seconds) return '';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${m}:${String(s).padStart(2, '0')}`;
  },

  // 格式化相对时间
  formatRelativeTime(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    const now = new Date();
    const diff = now - d;
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`;
    return d.toLocaleDateString('zh-CN');
  },

  // 渲染视频列表
  renderVideoList(container, videos, currentVideoId, onSelect, onDelete) {
    if (!videos.length) {
      container.innerHTML = '<div class="tab-empty">暂无视频</div>';
      return;
    }

    container.innerHTML = videos.map(v => {
      const isActive = v.id === currentVideoId;
      const statusClass = v.status;
      const statusText = v.status === 'ready' ? '就绪'
        : v.status === 'processing' ? '处理中'
          : v.status === 'error' ? '错误' : v.status;
      const progress = v.progress_pct || 0;
      const progressLabel = v.progress_step || '';

      return `
        <div class="video-card ${isActive ? 'active' : ''}" data-id="${v.id}">
          <button class="video-card-menu" data-delete="${v.id}" title="删除">
            <i class="fas fa-ellipsis-v"></i>
          </button>
          <div class="video-card-name">${this.escapeHtml(v.name)}</div>
          <div class="video-card-meta">
            <span class="status-indicator">
              <span class="status-dot ${statusClass}"></span>
              <span>${statusText}</span>
            </span>
            ${v.duration ? `<span>${this.formatDuration(v.duration)}</span>` : ''}
          </div>
          ${v.status === 'processing' && progress > 0 ? `
            <div class="progress-bar-container">
              <div class="progress-bar">
                <div class="progress-bar-fill" style="width:${progress}%"></div>
              </div>
              <div class="progress-label">${progressLabel} ${progress}%</div>
            </div>
          ` : ''}
        </div>
      `;
    }).join('');

    // 绑定事件
    container.querySelectorAll('.video-card').forEach(card => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('.video-card-menu')) return;
        const id = parseInt(card.dataset.id);
        onSelect(id);
      });
    });

    container.querySelectorAll('.video-card-menu').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(btn.dataset.delete);
        onDelete(id);
      });
    });
  },

  // 更新视频卡片进度
  updateVideoCardProgress(videoId, step, progress, label) {
    const card = document.querySelector(`.video-card[data-id="${videoId}"]`);
    if (!card) return;

    let progressContainer = card.querySelector('.progress-bar-container');
    if (!progressContainer) {
      progressContainer = document.createElement('div');
      progressContainer.className = 'progress-bar-container';
      progressContainer.innerHTML = `
        <div class="progress-bar">
          <div class="progress-bar-fill" style="width:0%"></div>
        </div>
        <div class="progress-label"></div>
      `;
      card.querySelector('.video-card-meta').after(progressContainer);
    }

    progressContainer.querySelector('.progress-bar-fill').style.width = `${progress}%`;
    progressContainer.querySelector('.progress-label').textContent = `${label} ${progress}%`;
  },

  // 渲染处理步骤
  renderProcessingSteps(container, currentStep, progress) {
    const stepIndex = this.PROCESSING_STEPS.findIndex(s => s.key === currentStep);

    container.innerHTML = this.PROCESSING_STEPS.map((step, idx) => {
      let iconClass = 'pending';
      let icon = '<i class="far fa-circle"></i>';

      if (idx < stepIndex || currentStep === 'done') {
        iconClass = 'completed';
        icon = '<i class="fas fa-check"></i>';
      } else if (idx === stepIndex) {
        iconClass = 'active';
        icon = '<i class="fas fa-spinner fa-spin"></i>';
      }

      return `
        <div class="step-item ${iconClass}">
          <div class="step-icon ${iconClass}">${icon}</div>
          <div class="step-content">
            <div class="step-label">${step.label}</div>
            <div class="step-detail">${idx === stepIndex ? `${progress}%` : ''}</div>
          </div>
        </div>
      `;
    }).join('');
  },

  // 渲染关键帧
  renderFrames(container, emptyEl, frames, videoId, apiBase, onImageClick) {
    if (!frames.length) {
      emptyEl.style.display = 'block';
      container.style.display = 'none';
      return;
    }

    emptyEl.style.display = 'none';
    container.style.display = 'grid';

    container.innerHTML = frames.map(f => `
      <div class="frame-thumb" data-frame="${f.id}">
        <img src="${apiBase}/videos/${videoId}/frames/${f.id}" alt="Frame" loading="lazy">
        <span class="frame-time">${this.formatDuration(f.timestamp_sec)}</span>
      </div>
    `).join('');

    container.querySelectorAll('.frame-thumb').forEach(thumb => {
      thumb.addEventListener('click', () => {
        const frameId = thumb.dataset.frame;
        onImageClick(`${apiBase}/videos/${videoId}/frames/${frameId}`);
      });
    });
  },

  // 渲染转录文本
  renderTranscript(contentEl, emptyEl, transcript) {
    if (!transcript) {
      emptyEl.style.display = 'block';
      contentEl.style.display = 'none';
      return;
    }

    emptyEl.style.display = 'none';
    contentEl.style.display = 'block';

    // 解析 Markdown 格式
    const html = marked.parse(transcript);
    contentEl.innerHTML = `<div class="transcript-text">${html}</div>`;
  },

  // 渲染对话列表
  renderConversations(container, emptyEl, conversations, currentConvId, onSelect) {
    if (!conversations.length) {
      emptyEl.style.display = 'block';
      container.style.display = 'none';
      return;
    }

    emptyEl.style.display = 'none';
    container.style.display = 'flex';

    container.innerHTML = conversations.map(c => `
      <div class="conv-item ${c.id === currentConvId ? 'active' : ''}" data-id="${c.id}">
        <div class="conv-item-title">${this.escapeHtml(c.title || '新对话')}</div>
        <div class="conv-item-time">${this.formatRelativeTime(c.created_at)}</div>
      </div>
    `).join('');

    container.querySelectorAll('.conv-item').forEach(item => {
      item.addEventListener('click', () => {
        const id = parseInt(item.dataset.id);
        onSelect(id);
      });
    });
  },

  // 渲染聊天消息
  renderMessages(container, messages) {
    if (!messages.length) {
      container.innerHTML = '<div class="chat-empty">开始提问关于视频内容的问题</div>';
      return;
    }

    container.innerHTML = messages.map(m => `
      <div class="msg ${m.role}">
        ${m.role === 'assistant' ? marked.parse(m.content) : this.escapeHtml(m.content)}
      </div>
    `).join('');

    container.scrollTop = container.scrollHeight;
  },

  // 添加用户消息
  appendUserMessage(container, text) {
    const emptyEl = container.querySelector('.chat-empty');
    if (emptyEl) emptyEl.remove();

    const msg = document.createElement('div');
    msg.className = 'msg user';
    msg.textContent = text;
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
    return msg;
  },

  // 添加 AI 消息（流式）
  appendAssistantMessage(container) {
    const msg = document.createElement('div');
    msg.className = 'msg assistant';
    msg.innerHTML = '<span style="color:var(--text-tertiary);">思考中...</span>';
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
    return msg;
  },

  // 更新 AI 消息内容
  updateAssistantMessage(msgEl, content) {
    msgEl.innerHTML = marked.parse(content);
    msgEl.closest('.chat-messages')?.scrollTo({ top: msgEl.closest('.chat-messages').scrollHeight });
  },

  // 显示确认对话框
  showConfirm(title, text, onConfirm) {
    const modal = document.getElementById('confirmModal');
    document.getElementById('confirmTitle').textContent = title;
    document.getElementById('confirmText').textContent = text;
    modal.classList.add('show');

    const okBtn = document.getElementById('confirmOkBtn');
    const cancelBtn = document.getElementById('confirmCancelBtn');

    const cleanup = () => {
      modal.classList.remove('show');
      okBtn.removeEventListener('click', handleOk);
      cancelBtn.removeEventListener('click', handleCancel);
    };

    const handleOk = () => {
      cleanup();
      onConfirm();
    };

    const handleCancel = () => {
      cleanup();
    };

    okBtn.addEventListener('click', handleOk);
    cancelBtn.addEventListener('click', handleCancel);
  },

  // 渲染 Provider 列表
  renderProvidersList(container, emptyEl, providers, activeId, onSelect, onSetDefault, onEdit, onDelete, onTest) {
    if (!providers.length) {
      emptyEl.style.display = 'block';
      container.style.display = 'none';
      container.innerHTML = '';
      return;
    }

    emptyEl.style.display = 'none';
    container.style.display = 'flex';

    container.innerHTML = providers.map(p => {
      const isActive = p.id === activeId;
      const classes = ['provider-row'];
      if (p.is_default) classes.push('is-default');
      if (isActive) classes.push('active');
      return `
      <div class="${classes.join(' ')}" data-id="${p.id}">
        <div class="provider-main">
          <div class="provider-name">
            ${p.is_default ? '<i class="fas fa-star" title="默认"></i> ' : ''}
            ${this.escapeHtml(p.name)}
            ${isActive ? '<span class="provider-tag-active">选用</span>' : ''}
          </div>
          <div class="provider-detail">
            <span class="provider-model">${this.escapeHtml(p.model)}</span>
            <span class="provider-url">${this.escapeHtml(p.base_url)}</span>
          </div>
        </div>
        <div class="provider-actions">
          ${p.is_default ? '' : `<button class="provider-btn" data-action="default" data-id="${p.id}" title="设为默认"><i class="far fa-star"></i></button>`}
          <button class="provider-btn" data-action="test" data-test="${p.id}" title="测试连通"><i class="fas fa-plug"></i></button>
          <span class="test-status" data-test-status="${p.id}"></span>
          <button class="provider-btn" data-action="edit" data-id="${p.id}" title="编辑"><i class="fas fa-pen"></i></button>
          <button class="provider-btn danger" data-action="delete" data-id="${p.id}" title="删除"><i class="fas fa-trash"></i></button>
        </div>
      </div>
    `;
    }).join('');

    // 行点击 = 选用（按钮区域内的点击由各自 handler stopPropagation）
    container.querySelectorAll('.provider-row').forEach(row => {
      row.addEventListener('click', (e) => {
        if (e.target.closest('.provider-btn') || e.target.closest('.provider-actions')) return;
        onSelect(parseInt(row.dataset.id));
      });
    });
    container.querySelectorAll('.provider-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(btn.dataset.id);
        const action = btn.dataset.action;
        if (action === 'default') onSetDefault(id);
        else if (action === 'edit') onEdit(id);
        else if (action === 'delete') onDelete(id);
      });
    });
    container.querySelectorAll('[data-test]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        onTest(parseInt(btn.dataset.test));
      });
    });
  },

  // 弹出 Provider 表单（行内）
  showProviderForm(container, existing, onSubmit) {
    const isEdit = !!existing;
    const formHtml = `
      <div class="provider-form">
        <div class="provider-form-title">${isEdit ? '编辑 Provider' : '添加 Provider'}</div>
        <div class="provider-form-row">
          <label>名称</label>
          <input type="text" class="pf-name" placeholder="如：MiniMax 生产" value="${existing ? this.escapeHtml(existing.name) : ''}">
        </div>
        <div class="provider-form-row">
          <label>Base URL</label>
          <input type="text" class="pf-url" placeholder="https://api.minimaxi.com/v1" value="${existing ? this.escapeHtml(existing.base_url) : 'https://api.minimaxi.com/v1'}">
        </div>
        <div class="provider-form-row">
          <label>API Key</label>
          <input type="password" class="pf-key" placeholder="API Key" value="${existing ? this.escapeHtml(existing.api_key) : ''}">
        </div>
        <div class="provider-form-row">
          <label>模型</label>
          <input type="text" class="pf-model" placeholder="MiniMax-M3" value="${existing ? this.escapeHtml(existing.model) : 'MiniMax-M3'}">
        </div>
        <div class="provider-form-actions">
          <button class="btn-secondary pf-cancel">取消</button>
          <button class="btn-primary pf-save">${isEdit ? '保存' : '创建'}</button>
        </div>
      </div>
    `;

    const formEl = document.createElement('div');
    formEl.innerHTML = formHtml;
    const form = formEl.firstElementChild;
    container.prepend(form);

    const cleanup = () => form.remove();

    form.querySelector('.pf-cancel').addEventListener('click', cleanup);
    form.querySelector('.pf-save').addEventListener('click', async () => {
      const data = {
        name: form.querySelector('.pf-name').value.trim(),
        base_url: form.querySelector('.pf-url').value.trim(),
        api_key: form.querySelector('.pf-key').value.trim(),
        model: form.querySelector('.pf-model').value.trim() || 'MiniMax-M3',
      };
      if (!data.name || !data.base_url || !data.api_key) {
        alert('名称 / Base URL / API Key 不能为空');
        return;
      }
      const btn = form.querySelector('.pf-save');
      btn.disabled = true;
      btn.textContent = '提交中...';
      const ok = await onSubmit(data);
      if (ok) cleanup();
      else { btn.disabled = false; btn.textContent = isEdit ? '保存' : '创建'; }
    });
  },

  // =================== 新版 4-Panel 渲染 ===================

  // 渲染对话列表（hover 显示重命名/删除）
  renderConvList(container, emptyEl, conversations, currentConvId, onSelect, onRename, onDelete) {
    if (!conversations.length) {
      emptyEl.style.display = 'block';
      container.style.display = 'none';
      container.innerHTML = '';
      return;
    }
    emptyEl.style.display = 'none';
    container.style.display = 'block';

    container.innerHTML = conversations.map(c => `
      <div class="conv-row ${c.id === currentConvId ? 'active' : ''}" data-id="${c.id}">
        <div class="conv-row-title">${this.escapeHtml(c.title || '新对话')}</div>
        <div class="conv-row-time">${this.formatRelativeTime(c.updated_at || c.created_at)}</div>
        <div class="conv-row-actions">
          <button class="conv-row-action" data-action="rename" data-id="${c.id}" title="重命名">
            <i class="fas fa-pen"></i>
          </button>
          <button class="conv-row-action delete" data-action="delete" data-id="${c.id}" title="删除">
            <i class="fas fa-trash"></i>
          </button>
        </div>
      </div>
    `).join('');

    container.querySelectorAll('.conv-row').forEach(row => {
      row.addEventListener('click', (e) => {
        if (e.target.closest('.conv-row-actions')) return;
        const id = parseInt(row.dataset.id);
        onSelect(id);
      });
    });
    container.querySelectorAll('[data-action="rename"]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(btn.dataset.id);
        this._startRename(container, id, conversations, onRename);
      });
    });
    container.querySelectorAll('[data-action="delete"]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(btn.dataset.id);
        onDelete(id);
      });
    });
  },

  // 行内重命名：把 title 换成 input，回车提交、Esc 取消、失焦提交
  _startRename(container, convId, conversations, onRename) {
    const row = container.querySelector(`.conv-row[data-id="${convId}"]`);
    if (!row) return;
    const conv = conversations.find(c => c.id === convId);
    if (!conv) return;
    const original = conv.title || '新对话';
    const titleEl = row.querySelector('.conv-row-title');
    const actionsEl = row.querySelector('.conv-row-actions');
    titleEl.style.display = 'none';
    if (actionsEl) actionsEl.style.display = 'none';

    const wrap = document.createElement('div');
    wrap.className = 'conv-row-rename';
    const input = document.createElement('input');
    input.type = 'text';
    input.value = original;
    wrap.appendChild(input);
    titleEl.after(wrap);
    input.focus();
    input.select();

    let done = false;
    const commit = async () => {
      if (done) return;
      done = true;
      const newTitle = input.value.trim();
      wrap.remove();
      titleEl.style.display = '';
      if (actionsEl) actionsEl.style.display = '';
      if (newTitle && newTitle !== original) {
        await onRename(convId, newTitle);
      }
    };
    const cancel = () => {
      if (done) return;
      done = true;
      wrap.remove();
      titleEl.style.display = '';
      if (actionsEl) actionsEl.style.display = '';
    };
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); commit(); }
      else if (e.key === 'Escape') { e.preventDefault(); cancel(); }
    });
    input.addEventListener('blur', commit);
  },

  // 渲染聊天消息（流式光标 + markdown）
  renderChatMessages(container, messages) {
    if (!messages.length) {
      container.innerHTML = '<div class="chat-empty">开始提问关于视频内容的问题</div>';
      return;
    }
    container.innerHTML = messages.map((m, idx) => this._renderMessage(m, idx)).join('');
    messages.forEach((m, idx) => {
      if (m.role !== 'assistant') return;
      const btn = container.querySelector(`[data-copy-index="${idx}"]`);
      if (!btn) return;
      btn.dataset.copyText = this.splitThinkContent(m.content || '').content;
      btn.addEventListener('click', () => this.copyFromButton(btn));
    });
    container.scrollTop = container.scrollHeight;
  },

  // 单条消息 HTML
  _renderMessage(m, index = 0) {
    if (m.role === 'user') {
      return `<div class="chat-bubble chat-bubble-user"><div class="bubble">${this.escapeHtml(m.content)}</div></div>`;
    }
    if (m.role === 'error') {
      return `<div class="chat-bubble chat-bubble-error"><div class="bubble">${this.escapeHtml(m.content)}</div></div>`;
    }
    const parsed = this.splitThinkContent(m.content || '');
    const html = marked.parse(parsed.content || '');
    const thinkingHtml = parsed.thinking ? `
      <details class="chat-thinking">
        <summary><i class="fas fa-brain"></i><span class="chat-thinking-label">已思考 ${parsed.thinking.length} 字</span></summary>
        <div class="chat-thinking-body">${this.escapeHtml(parsed.thinking)}</div>
      </details>
    ` : '';
    return `
      <div class="chat-bubble chat-bubble-assistant">
        ${thinkingHtml}
        <div class="bubble">${html}</div>
        <div class="bubble-actions">
          <button class="bubble-action" data-copy-index="${index}" title="复制"><i class="far fa-copy"></i></button>
        </div>
      </div>
    `;
  },

  // 流式追加用户消息
  appendChatUser(container, text) {
    const empty = container.querySelector('.chat-empty');
    if (empty) empty.remove();
    const wrap = document.createElement('div');
    wrap.className = 'chat-bubble chat-bubble-user';
    wrap.innerHTML = `<div class="bubble">${this.escapeHtml(text)}</div>`;
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
    return wrap;
  },

  // 流式追加助手消息（带 thinking 容器 + 光标）
  appendChatAssistant(container) {
    const empty = container.querySelector('.chat-empty');
    if (empty) empty.remove();
    const wrap = document.createElement('div');
    wrap.className = 'chat-bubble chat-bubble-assistant';
    const thinking = document.createElement('details');
    thinking.className = 'chat-thinking';
    thinking.innerHTML = `<summary><i class="fas fa-brain"></i><span class="chat-thinking-label">思考中…</span></summary><div class="chat-thinking-body"></div>`;
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.innerHTML = '<span class="chat-streaming-cursor"></span>';
    wrap.appendChild(thinking);
    wrap.appendChild(bubble);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
    return { wrap, thinking, thinkingBody: thinking.querySelector('.chat-thinking-body'), bubble };
  },

  // 流式追加错误消息
  appendChatError(container, text) {
    const empty = container.querySelector('.chat-empty');
    if (empty) empty.remove();
    const wrap = document.createElement('div');
    wrap.className = 'chat-bubble chat-bubble-error';
    wrap.innerHTML = `<div class="bubble">${this.escapeHtml(text)}</div>`;
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
    return wrap;
  },

  // 流式更新助手内容（每次都重渲染 markdown + 光标；可选 thinking）
  updateChatAssistant(parts, content) {
    const html = marked.parse(content || '');
    parts.bubble.innerHTML = `${html}<span class="chat-streaming-cursor"></span>`;
    if (parts.thinkingBody && parts.thinkingBody.textContent) {
      parts.thinkingBody.scrollTop = parts.thinkingBody.scrollHeight;
    }
    const parent = parts.bubble.closest('.chat-messages');
    if (parent) parent.scrollTop = parent.scrollHeight;
  },

  // 流式追加思考片段
  appendThinking(parts, chunk) {
    if (!parts.thinkingBody) return;
    parts.thinkingBody.textContent += chunk;
    const label = parts.thinking.querySelector('.chat-thinking-label');
    if (label) label.textContent = `已思考 ${parts.thinkingBody.textContent.length} 字`;
    parts.thinkingBody.scrollTop = parts.thinkingBody.scrollHeight;
  },

  // 流式结束后去掉光标 + 挂载复制按钮
  finalizeChatAssistant(parts, content) {
    if (parts.thinkingBody && parts.thinkingBody.textContent) {
      const len = parts.thinkingBody.textContent.length;
      const label = parts.thinking.querySelector('.chat-thinking-label');
      if (label) label.textContent = `已思考 ${len} 字`;
    } else if (parts.thinking) {
      // 没有思考内容，整个 details 隐藏
      parts.thinking.remove();
    }
    parts.bubble.innerHTML = marked.parse(content || '');
    // 复制按钮（带数据存原始 markdown）
    const actions = document.createElement('div');
    actions.className = 'bubble-actions';
    actions.appendChild(this.createCopyButton(content || ''));
    parts.wrap.appendChild(actions);
  },

  // 渲染测试连通状态（行内，圈圈 + 延迟）
  // status: 'idle' | 'testing' | 'ok' | 'fail'
  renderTestStatus(el, status, data) {
    el.classList.remove('testing', 'ok', 'fail');
    if (status === 'testing') {
      el.classList.add('testing');
      el.innerHTML = '<span class="test-spinner"></span>';
    } else if (status === 'ok') {
      el.classList.add('ok');
      el.innerHTML = `<i class="fas fa-check test-icon"></i> ${data && data.elapsed_ms != null ? data.elapsed_ms + 'ms' : 'OK'}`;
    } else if (status === 'fail') {
      el.classList.add('fail');
      el.innerHTML = `<i class="fas fa-times test-icon"></i> ${data && data.elapsed_ms != null ? data.elapsed_ms + 'ms' : 'FAIL'}`;
    } else {
      el.innerHTML = '';
    }
  },
};

window.UI = UI;