# CPU自适应多进程 + 配色方案改造

## 1. CPU自适应多进程加速

### 1.1 现状分析

| 模块 | 当前方式 | 并行潜力 |
|------|---------|---------|
| `split_audio_into_segments()` | 逐段串行 ffmpeg stream copy | 高：各段独立，可并发 |
| `extract_keyframes_to_dir()` | 单次 ffmpeg 命令，filter chain | 无：单 pass 已最优 |
| `extract_audio_for_whisper()` | 单次 ffmpeg 命令 | 无：单文件转换 |
| Whisper 转录 | 逐段串行 | 无：单模型实例不能并发 |

### 1.2 并行策略

**仅对 `split_audio_into_segments()` 做并发化**，原因：
- 音频分段各段完全独立，天然可并行
- stream copy 虽快，但长视频（>1h）拆 10+ 段时串行仍需等待
- 关键帧提取是单次 ffmpeg filter，无法拆分
- Whisper 是单模型实例，并发会争抢 GPU/CPU 资源

### 1.3 自适应 worker 数计算

新增 `_get_adaptive_workers()` 函数：

```python
import psutil

def _get_adaptive_workers():
    cpu_cores = psutil.cpu_count(logical=False) or 4
    cpu_usage = psutil.cpu_percent(interval=0.5)

    if cpu_usage >= 70:
        return 1
    elif cpu_usage >= 50:
        return min(2, cpu_cores)
    elif cpu_usage >= 30:
        return min(3, cpu_cores)
    else:
        return min(4, cpu_cores)
```

规则：
- CPU >= 70% → 1 worker（最小化额外负载）
- CPU >= 50% → 最多 2 worker
- CPU >= 30% → 最多 3 worker
- CPU < 30% → 最多 4 worker
- 上限为物理核心数，避免超线程导致卡顿

### 1.4 实现方案

`split_audio_into_segments()` 改为分批并发：

```python
workers = _get_adaptive_workers()
for batch_start in range(0, num_segments, workers):
    batch = segments_info[batch_start : batch_start + workers]
    await asyncio.gather(*[
        asyncio.to_thread(_run_seg, cmd) for cmd in batch
    ])
```

每批执行前重新检测 CPU 负载，动态调整下一批 worker 数。

### 1.5 依赖

`requirements.txt` 添加 `psutil>=5.9`

## 2. 配色方案改造

### 2.1 目标风格

灰黑（NotebookLM） + 橙色（Claude） + 白色

### 2.2 CSS 变量对照表

| 变量 | 旧值 | 新值 | 用途 |
|------|------|------|------|
| `--bg-primary` | `#f8f9fa` | `#1a1a1a` | 页面背景（深灰黑） |
| `--bg-surface` | `#ffffff` | `#242424` | 面板/卡片背景 |
| `--bg-hover` | `#f1f3f4` | `#2d2d2d` | 悬停状态 |
| `--bg-active` | `#e8f0fe` | `#3d2a1a` | 选中/激活状态（橙色透明底） |
| `--accent` | `#1a73e8` | `#f97316` | 主色调（橙色） |
| `--accent-hover` | `#1557b0` | `#ea580c` | 悬停橙 |
| `--text-primary` | `#202124` | `#e8e8e8` | 主文字（亮白） |
| `--text-secondary` | `#5f6368` | `#a0a0a0` | 次要文字（灰） |
| `--text-tertiary` | `#9aa0a6` | `#666666` | 占位/弱文字 |
| `--border` | `#dadce0` | `#333333` | 边框 |
| `--success` | `#34a853` | `#4ade80` | 成功（亮绿） |
| `--warning` | `#fbbc04` | `#fbbf24` | 处理中 |
| `--error` | `#ea4335` | `#ef4444` | 错误 |

### 2.3 额外样式调整

- Modal overlay 改为 `rgba(0,0,0,0.7)`（暗色遮罩）
- Scrollbar thumb 颜色调亮
- Frame time 标签背景保持半透明黑

## 3. 实施步骤

1. `requirements.txt` 添加 `psutil>=5.9`
2. `video_processor.py` 添加 `_get_adaptive_workers()` + 重构 `split_audio_into_segments()`
3. `static/css/style.css` 更新 `:root` 变量 + 修正暗色主题下的特殊样式
4. 重启服务验证

## 4. 验证结果

### 4.1 CPU 自适应多进程

| 验证项 | 结果 |
|--------|------|
| psutil 安装 | v7.2.2 正常 |
| `_get_adaptive_workers()` 调用 | CPU 7.2% → 返回 4 worker |
| 物理核心检测 | 10 核 |
| 模块导入无语法错误 | 通过 |

### 4.2 配色方案

| 验证项 | 结果 |
|--------|------|
| 服务启动 (port 8001) | 正常 |
| 前端页面加载 | 暗色主题正确显示 |
| 深灰黑背景 (#1a1a1a) | 通过 |
| 橙色主色调 (#f97316) | 按钮/Tab/进度条均为橙色 |
| 白色文字 | 标题和正文文字为亮白色 |
| 三栏布局 | 正常 |
| 暗色输入框/弹窗 | 已适配 |

### 4.3 待验证

- 上传视频测试完整处理流程（HF 镜像下载模型 → 转录 → 关键帧提取 → 自适应分段）
- 数据库中有一条旧错误视频（id=3, HuggingFace 超时），需清理后重新测试
