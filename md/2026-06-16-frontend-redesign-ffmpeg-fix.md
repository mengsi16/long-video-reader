# AI Video Reader 修复与前端重构实施计划

## 背景

用户上传 683MB 视频后提示处理错误。根因排查结果：

| 项目 | 详情 |
|------|------|
| 数据库记录 | video_id=2, status=error |
| 错误信息 | `[WinError 2] 系统找不到指定的文件。` |
| 根因 | 系统上 **未安装 ffmpeg/ffprobe**，`subprocess.run(["ffprobe", ...])` 无法找到可执行文件 |
| 影响范围 | `video_processor.py` 中 10 处 subprocess 调用全部使用裸命令名，均受影响 |

同时用户要求参考 Google NotebookLM 风格重新设计前端，增加处理进度实时反馈、转录文本查看、视频管理操作。

## 已完成的修改

### 1. 安装 ffmpeg 依赖

- 安装 `static-ffmpeg` 包（自带 ffmpeg + ffprobe 二进制文件）
- 更新 `requirements.txt` 添加 `static-ffmpeg>=3.0`

### 2. 修复 ffmpeg 路径解析 (`backend/video_processor.py`)

新增 `_resolve_executable()` 函数，搜索顺序：
1. 环境变量 `FFMPEG_PATH` / `FFPROBE_PATH`
2. `static-ffmpeg` 自带二进制
3. `shutil.which` (系统 PATH)

修改 `VideoProcessor.__init__()` 缓存路径，替换全部 10 处裸命令调用。

### 3. 修复 start.py

`check_ffmpeg()` 改用 `static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()` 探测。

### 4. 数据库增加进度字段 (`backend/database.py`)

`videos` 表新增：
- `progress_step TEXT DEFAULT ''` - 当前处理步骤
- `progress_pct INTEGER DEFAULT 0` - 进度百分比

### 5. 后端进度报告 (`backend/main.py`)

重构 `process_video_task`，定义 6 步进度：

| 步骤 | 标签 | 进度范围 |
|------|------|---------|
| `extracting_audio` | 提取音频 | 0-15% |
| `splitting_audio` | 音频分段 | 15-25% |
| `transcribing` | 转录中 (X/N) | 25-60% |
| `extracting_frames` | 提取关键帧 | 60-85% |
| `finalizing` | 整理结果 | 85-95% |
| `done` | 完成 | 100% |

SSE 广播格式：
```json
{
  "type": "progress",
  "step": "transcribing",
  "step_label": "转录中 (2/3)",
  "progress": 45
}
```

### 6. 前端重构 - NotebookLM 风格

#### 文件拆分

| 文件 | 职责 |
|------|------|
| `static/index.html` | HTML 骨架 |
| `static/css/style.css` | 全套样式 |
| `static/app.js` | 主应用类 |
| `static/js/api.js` | API 封装 |
| `static/js/ui.js` | UI 渲染函数 |

#### 布局设计

```
+-------------------------------------------------------------------+
|  AI Video Reader (Top Bar)                    [设置] [刷新]         |
+-------------+-------------------------------+----------------------+
| Sources     |       Main Content            | Details              |
| (280px)     |       (flex: 1)               | (360px)              |
|             |                               |                      |
| [+ 添加源]  |  (空状态: 欢迎页)              | [关键帧|转录|对话]     |
|             |  (处理中: 步骤进度条)           |                      |
| [视频卡片]  |  (就绪: 对话消息流)             | 内容区               |
|  名称/时长  |                               |                      |
|  状态/进度  |                               |                      |
+-------------+-------------------------------+----------------------+
```

#### 色彩方案

| 变量 | 值 | 用途 |
|------|-----|------|
| `--bg-primary` | `#f8f9fa` | 页面背景 |
| `--bg-surface` | `#ffffff` | 卡片/面板背景 |
| `--accent` | `#1a73e8` | 主色调 (Google Blue) |
| `--success` | `#34a853` | 成功 |
| `--warning` | `#fbbc04` | 处理中 |
| `--error` | `#ea4335` | 错误 |

## 验证结果

- 服务启动成功
- 前端正确加载（CSS/JS 全部 200 OK）
- NotebookLM 风格三栏布局正确显示
- 删除确认对话框正常弹出
- 旧错误视频删除成功

## 后续建议

1. 上传小视频测试完整处理流程（进度显示、转录、关键帧）
2. 上传长视频验证 ffmpeg 修复效果
3. 配置 MiniMax API Key 测试对话功能
