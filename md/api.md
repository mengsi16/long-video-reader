# video-reader API 文档

## 视频

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/videos` | 视频列表 |
| `POST` | `/api/videos` | 上传本地视频或音频 |
| `POST` | `/api/videos/process-url` | 通过 URL 添加视频 |
| `GET` | `/api/videos/{video_id}` | 视频详情 |
| `DELETE` | `/api/videos/{video_id}` | 删除视频记录 |
| `GET` | `/api/videos/{video_id}/stream` | 处理进度 SSE |
| `GET` | `/api/videos/{video_id}/frames/{frame_id}` | 读取关键帧 |
| `GET` | `/api/videos/{video_id}/transcript` | 读取转录文本 |
| `GET` | `/api/videos/{video_id}/index` | 读取长视频索引 |
| `POST` | `/api/videos/{video_id}/index` | 构建或重建索引 |

## 对话

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/conversations` | 对话列表 |
| `POST` | `/api/conversations` | 新建对话 |
| `PUT` | `/api/conversations/{conversation_id}` | 更新对话 |
| `GET` | `/api/conversations/{conversation_id}` | 对话详情 |
| `DELETE` | `/api/conversations/{conversation_id}` | 删除对话 |
| `POST` | `/api/conversations/{conversation_id}/chat` | 围绕视频提问 |

## Provider

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/providers` | Provider 列表 |
| `POST` | `/api/providers` | 新增 Provider |
| `PUT` | `/api/providers/{provider_id}` | 更新 Provider |
| `DELETE` | `/api/providers/{provider_id}` | 删除 Provider |
| `POST` | `/api/providers/{provider_id}/set-default` | 设为默认 Provider |
| `POST` | `/api/providers/{provider_id}/test` | 测试 Provider 连通性 |
| `POST` | `/api/models` | 获取模型列表 |
