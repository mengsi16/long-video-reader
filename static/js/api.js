/* API Service - 封装所有后端 API 调用 */

class ApiService {
  constructor() {
    this.apiBase = '/api';
  }

  async _formFetch(path, fields, method = 'POST') {
    const fd = new FormData();
    for (const [k, v] of Object.entries(fields)) {
      if (v !== undefined && v !== null) fd.append(k, v);
    }
    const resp = await fetch(`${this.apiBase}${path}`, { method, body: fd });
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const body = await resp.json();
        detail = body.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    return await resp.json();
  }

  // ----- 视频 -----
  async listVideos() {
    const resp = await fetch(`${this.apiBase}/videos`);
    const data = await resp.json();
    return data.data || [];
  }

  async getVideo(videoId) {
    const resp = await fetch(`${this.apiBase}/videos/${videoId}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  }

  async uploadVideo(file, name = '') {
    const fd = new FormData();
    fd.append('file', file, file.name);
    if (name) fd.append('name', name);
    const resp = await fetch(`${this.apiBase}/videos`, { method: 'POST', body: fd });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || '上传失败');
    }
    return await resp.json();
  }

  async processUrl(url, name = '') {
    const fd = new FormData();
    fd.append('url', url);
    if (name) fd.append('name', name);
    const resp = await fetch(`${this.apiBase}/videos/process-url`, { method: 'POST', body: fd });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || '处理失败');
    }
    return await resp.json();
  }

  async deleteVideo(videoId) {
    const resp = await fetch(`${this.apiBase}/videos/${videoId}`, { method: 'DELETE' });
    return await resp.json();
  }

  async getTranscript(videoId) {
    const resp = await fetch(`${this.apiBase}/videos/${videoId}/transcript`);
    if (!resp.ok) return null;
    return await resp.json();
  }

  // ----- 对话 -----
  async createConversation(videoId, title = null) {
    return await this._formFetch('/conversations', { video_id: videoId, title });
  }

  async getConversation(convId) {
    const resp = await fetch(`${this.apiBase}/conversations/${convId}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  }

  async deleteConversation(convId) {
    const resp = await fetch(`${this.apiBase}/conversations/${convId}`, { method: 'DELETE' });
    return await resp.json();
  }

  async updateConversation(convId, { title }) {
    return await this._formFetch(`/conversations/${convId}`, { title }, 'PUT');
  }

  // ----- Provider -----
  async listProviders() {
    const resp = await fetch(`${this.apiBase}/providers`);
    const data = await resp.json();
    return data.data || [];
  }

  async createProvider({ name, base_url, api_key, model }) {
    return await this._formFetch('/providers', { name, base_url, api_key, model });
  }

  async updateProvider(id, { name, base_url, api_key, model }) {
    return await this._formFetch(`/providers/${id}`, { name, base_url, api_key, model }, 'PUT');
  }

  async deleteProvider(id) {
    const resp = await fetch(`${this.apiBase}/providers/${id}`, { method: 'DELETE' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  }

  async setDefaultProvider(id) {
    return await this._formFetch(`/providers/${id}/set-default`, {});
  }

  async testProvider(id) {
    return await this._formFetch(`/providers/${id}/test`, {});
  }

  // ----- 聊天 (SSE) -----
  async sendMessage(convId, message, providerId, onChunk, onDone, onError, onThinking) {
    const fd = new FormData();
    fd.append('message', message);
    if (providerId != null) fd.append('provider_id', providerId);
    const resp = await fetch(`${this.apiBase}/conversations/${convId}/chat`, {
      method: 'POST', body: fd,
    });
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const body = await resp.json();
        detail = body.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));
          if (data.type === 'thinking') {
            onThinking && onThinking(data.content);
          } else if (data.type === 'chunk') {
            onChunk(data.content);
          } else if (data.type === 'done') {
            onDone(data);
          } else if (data.type === 'error') {
            onError(data.error || '未知错误');
          }
        } catch (e) {
          onError(`SSE 解析失败: ${e.message}`);
        }
      }
    }
  }

  // ----- 视频处理进度 (SSE) -----
  subscribeProgress(videoId, onProgress, onStatus, onError) {
    const es = new EventSource(`${this.apiBase}/videos/${videoId}/stream`);

    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === 'heartbeat') return;
        if (data.type === 'progress') {
          onProgress(data);
        } else if (data.status === 'ready' || data.status === 'error') {
          onStatus(data);
          es.close();
        }
      } catch (e) {
        // ignore parse error
      }
    };

    es.onerror = () => {
      if (onError) onError();
      es.close();
    };

    return es;
  }
}

window.api = new ApiService();