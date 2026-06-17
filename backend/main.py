import os
import json
import asyncio
import logging
import time
import uuid
import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import sys
sys.path.insert(0, str(Path(__file__).parent))

import config
from database import (
    init_db, create_video, get_video, list_videos, update_video, delete_video,
    create_frame, get_frames, get_frame, delete_frames,
    create_conversation, get_conversation, list_conversations, delete_conversation, update_conversation,
    create_message, get_messages,
    list_providers, get_provider, get_default_provider, create_provider,
    update_provider, delete_provider, set_default_provider,
)
from video_processor import VideoProcessor
from transcriber import Transcriber
from minimax_client import (
    chat_stream, build_chat_messages, build_chat_messages_with_context, get_client
)
from video_indexer import build_video_index
from video_reader_tool import (
    has_video_index, read_video_manifest, read_video_overview, build_context_pack
)
import openai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Video Reader", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 禁用静态文件缓存（开发阶段）
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR), html=False), name="static")


@app.middleware("http")
async def add_no_cache_for_static(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path == "/":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response

video_processor = VideoProcessor()
transcriber = Transcriber(model_size=config.WHISPER_MODEL_SIZE)

sse_connections: dict[int, list] = {}


@app.on_event("startup")
async def startup():
    await init_db()
    providers = await list_providers()
    if not providers and config.MINIMAX_API_KEY:
        pid = await create_provider(
            "默认（来自环境变量）",
            config.MINIMAX_BASE_URL,
            config.MINIMAX_API_KEY,
            config.MINIMAX_MODEL,
        )
        await set_default_provider(pid)
        logger.info(f"已从环境变量创建默认 provider id={pid}")
    elif providers and not await get_default_provider():
        await set_default_provider(providers[0]["id"])
        logger.info(f"已把最早一条 provider id={providers[0]['id']} 设为默认")


@app.get("/")
async def read_root():
    return FileResponse(str(config.STATIC_DIR / "index.html"))


@app.get("/api/videos")
async def api_list_videos():
    videos = await list_videos()
    return {"data": videos}


@app.post("/api/videos")
async def api_upload_video(
    file: UploadFile = File(...),
    name: str = Form(default=""),
):
    raw_name = file.filename or "upload.bin"
    if ".." in raw_name or "/" in raw_name or "\\" in raw_name:
        raise HTTPException(status_code=400, detail="Invalid filename")
    safe_name = os.path.basename(raw_name)
    ext = Path(safe_name).suffix.lower()
    if ext not in config.UPLOAD_ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    max_bytes = config.UPLOAD_MAX_MB * 1024 * 1024
    video_name = name or Path(safe_name).stem
    video_id = await create_video(video_name, source_url=None, file_path=None)

    upload_dir = config.UPLOADS_DIR / str(video_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / safe_name

    total = 0
    with open(dest, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                await delete_video(video_id)
                raise HTTPException(status_code=413, detail=f"File exceeds {config.UPLOAD_MAX_MB} MB limit")
            f.write(chunk)

    await update_video(video_id, file_path=str(dest))
    asyncio.create_task(process_video_task(video_id, str(dest)))
    return {"video_id": video_id, "message": "上传成功，正在处理..."}


@app.post("/api/videos/process-url")
async def api_process_url(
    url: str = Form(...),
    name: str = Form(default=""),
):
    video_name = name or "video"
    video_id = await create_video(video_name, source_url=url)

    upload_dir = config.UPLOADS_DIR / str(video_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    try:
        audio_path, video_title = await video_processor.download_and_convert(url, upload_dir)
        await update_video(video_id, name=video_title or video_name, file_path=audio_path)
    except Exception as e:
        await update_video(video_id, status="error", error_message=str(e))
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")

    asyncio.create_task(process_video_task(video_id, audio_path))
    return {"video_id": video_id, "message": "下载成功，正在处理..."}


@app.get("/api/videos/{video_id}")
async def api_get_video(video_id: int):
    video = await get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")
    frames = await get_frames(video_id)
    conversations = await list_conversations(video_id)
    return {"video": video, "frames": frames, "conversations": conversations}


@app.delete("/api/videos/{video_id}")
async def api_delete_video(video_id: int):
    video = await get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")

    frames_dir = config.FRAMES_DIR / str(video_id)
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    uploads_dir = config.UPLOADS_DIR / str(video_id)
    if uploads_dir.exists():
        shutil.rmtree(uploads_dir)
    transcript_file = config.TRANSCRIPTS_DIR / f"{video_id}.txt"
    if transcript_file.exists():
        transcript_file.unlink()

    await delete_video(video_id)
    return {"message": "已删除"}


@app.get("/api/videos/{video_id}/stream")
async def api_video_stream(video_id: int):
    async def event_generator():
        queue = asyncio.Queue()
        if video_id not in sse_connections:
            sse_connections[video_id] = []
        sse_connections[video_id].append(queue)

        try:
            video = await get_video(video_id)
            if video:
                await queue.put(json.dumps({
                    "status": video["status"],
                    "progress": 100 if video["status"] == "ready" else 0,
                }))

            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {data}\n\n"
                    parsed = json.loads(data)
                    if parsed.get("status") in ["ready", "error"]:
                        break
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            if video_id in sse_connections and queue in sse_connections[video_id]:
                sse_connections[video_id].remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/videos/{video_id}/frames/{frame_id}")
async def api_get_frame_image(video_id: int, frame_id: int):
    frame = await get_frame(frame_id)
    if not frame or frame["video_id"] != video_id:
        raise HTTPException(status_code=404, detail="关键帧不存在")
    path = Path(frame["file_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="图片文件不存在")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/videos/{video_id}/transcript")
async def api_get_transcript(video_id: int):
    transcript_file = config.TRANSCRIPTS_DIR / f"{video_id}.txt"
    if not transcript_file.exists():
        raise HTTPException(status_code=404, detail="转录文本不存在")
    text = transcript_file.read_text(encoding="utf-8")
    return {"transcript": text}


@app.get("/api/videos/{video_id}/index")
async def api_get_video_index(video_id: int):
    video = await get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")
    if not has_video_index(video_id):
        return {"exists": False, "video_id": video_id}
    return {
        "exists": True,
        "manifest": read_video_manifest(video_id),
        "overview": read_video_overview(video_id),
    }


@app.post("/api/videos/{video_id}/index")
async def api_build_video_index(
    video_id: int,
    provider_id: int = Form(default=None),
):
    video = await get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")
    provider = await get_provider(provider_id) if provider_id is not None else await get_default_provider()
    if not provider:
        raise HTTPException(status_code=400, detail="没有可用的 provider，请先在设置中添加一个")
    transcript_file = config.TRANSCRIPTS_DIR / f"{video_id}.txt"
    if not transcript_file.exists():
        raise HTTPException(status_code=404, detail="转录文本不存在")
    transcript_text = transcript_file.read_text(encoding="utf-8")
    frames = await get_frames(video_id)
    manifest = await build_video_index(video, frames, transcript_text, provider)
    return {"exists": True, "manifest": manifest}


@app.get("/api/conversations")
async def api_list_conversations(video_id: int = Query(default=None)):
    conversations = await list_conversations(video_id)
    return {"data": conversations}


@app.post("/api/conversations")
async def api_create_conversation(
    video_id: int = Form(...),
    title: str = Form(default=None),
):
    video = await get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")
    conv_id = await create_conversation(video_id, title)
    return {"conversation_id": conv_id}


@app.put("/api/conversations/{conversation_id}")
async def api_update_conversation(
    conversation_id: int,
    title: str = Form(default=None),
):
    conv = await get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    if title is None:
        raise HTTPException(status_code=400, detail="No fields to update")
    await update_conversation(conversation_id, title=title)
    return {"message": "已更新"}


@app.get("/api/conversations/{conversation_id}")
async def api_get_conversation(conversation_id: int):
    conv = await get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    messages = await get_messages(conversation_id)
    return {"conversation": conv, "messages": messages}


@app.delete("/api/conversations/{conversation_id}")
async def api_delete_conversation(conversation_id: int):
    await delete_conversation(conversation_id)
    return {"message": "已删除"}


@app.get("/api/providers")
async def api_list_providers():
    return {"data": await list_providers()}


@app.post("/api/providers")
async def api_create_provider(
    name: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(...),
    model: str = Form(default="MiniMax-M3"),
):
    if not name.strip() or not base_url.strip() or not api_key.strip():
        raise HTTPException(status_code=400, detail="name / base_url / api_key 不能为空")
    pid = await create_provider(name.strip(), base_url.strip(), api_key.strip(), model.strip() or "MiniMax-M3")
    return {"provider_id": pid, "message": "已创建"}


@app.put("/api/providers/{provider_id}")
async def api_update_provider(
    provider_id: int,
    name: str = Form(default=None),
    base_url: str = Form(default=None),
    api_key: str = Form(default=None),
    model: str = Form(default=None),
):
    fields = {
        k: v for k, v in
        {"name": name, "base_url": base_url, "api_key": api_key, "model": model}.items()
        if v is not None and v != ""
    }
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    if not await get_provider(provider_id):
        raise HTTPException(status_code=404, detail="Provider 不存在")
    await update_provider(provider_id, **fields)
    return {"message": "已更新"}


@app.delete("/api/providers/{provider_id}")
async def api_delete_provider(provider_id: int):
    if not await get_provider(provider_id):
        raise HTTPException(status_code=404, detail="Provider 不存在")
    await delete_provider(provider_id)
    return {"message": "已删除"}


@app.post("/api/providers/{provider_id}/set-default")
async def api_set_default_provider(provider_id: int):
    if not await get_provider(provider_id):
        raise HTTPException(status_code=404, detail="Provider 不存在")
    await set_default_provider(provider_id)
    return {"message": "已设为默认"}


@app.post("/api/providers/{provider_id}/test")
async def api_test_provider(provider_id: int):
    p = await get_provider(provider_id)
    if not p:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    t0 = time.monotonic()
    try:
        client = openai.OpenAI(api_key=p["api_key"], base_url=p["base_url"].rstrip("/"))
        resp = await asyncio.to_thread(client.models.list)
        models = [m.id for m in resp.data]
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {"ok": True, "models": models, "elapsed_ms": elapsed_ms}
    except Exception as e:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {"ok": False, "error": str(e), "elapsed_ms": elapsed_ms}


@app.post("/api/conversations/{conversation_id}/chat")
async def api_chat(
    conversation_id: int,
    message: str = Form(...),
    provider_id: int = Form(default=None),
):
    conv = await get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    if provider_id is not None:
        provider = await get_provider(provider_id)
    else:
        provider = await get_default_provider()
    if not provider:
        raise HTTPException(status_code=400, detail="没有可用的 provider，请先在设置中添加一个")

    masked = provider["api_key"][:4] + "***" + provider["api_key"][-4:] if len(provider["api_key"]) > 8 else "***"
    logger.info(
        f"[chat] conv={conversation_id} provider={provider['id']}({provider['name']}) "
        f"key={masked} model={provider['model']} msg_len={len(message)}"
    )

    await create_message(conversation_id, "user", message)

    frames = await get_frames(conv["video_id"])
    transcript_file = config.TRANSCRIPTS_DIR / f"{conv['video_id']}.txt"
    transcript_text = transcript_file.read_text(encoding="utf-8") if transcript_file.exists() else ""
    history = await get_messages(conversation_id)

    system_prompt = (
        "你是一个视频分析助手。用户会向你提问关于视频内容的问题。"
        "请根据提供的关键帧图片和音频转录文本来回答用户的问题。"
        "回答要准确、详细、有条理。如果某些信息不确定，请明确说明。"
    )

    if has_video_index(conv["video_id"]):
        context_pack = build_context_pack(conv["video_id"], message)
        messages = build_chat_messages_with_context(
            user_message=message,
            context_pack=context_pack,
            history=history[:-1],
        )
    else:
        messages = build_chat_messages(
            user_message=message,
            frames=frames,
            transcript_text=transcript_text,
            history=history[:-1],
        )

    async def stream_response():
        full_response = ""
        full_thinking = ""
        chunk_count = 0
        thinking_count = 0
        t0 = time.monotonic()
        try:
            async for kind, content in chat_stream(
                messages,
                system_prompt=system_prompt,
                api_key=provider["api_key"],
                base_url=provider["base_url"],
                model=provider["model"],
            ):
                if kind == "thinking":
                    full_thinking += content
                    thinking_count += 1
                    yield f"data: {json.dumps({'type': 'thinking', 'content': content}, ensure_ascii=False)}\n\n"
                else:
                    full_response += content
                    chunk_count += 1
                    yield f"data: {json.dumps({'type': 'chunk', 'content': content}, ensure_ascii=False)}\n\n"
            await create_message(conversation_id, "assistant", full_response)
            elapsed = time.monotonic() - t0
            logger.info(
                f"[chat] done conv={conversation_id} provider={provider['id']} "
                f"chunks={chunk_count} thinking_chunks={thinking_count} elapsed={elapsed:.1f}s"
            )
            yield f"data: {json.dumps({'type': 'done', 'elapsed': elapsed})}\n\n"
        except Exception as e:
            elapsed = time.monotonic() - t0
            err = str(e)
            logger.error(
                f"[chat] fail conv={conversation_id} provider={provider['id']} "
                f"elapsed={elapsed:.1f}s err={err}"
            )
            yield f"data: {json.dumps({'type': 'error', 'error': err}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/models")
async def list_models(base_url: str = Form(default=""), api_key: str = Form(default="")):
    import openai
    effective_key = api_key or config.MINIMAX_API_KEY
    effective_url = (base_url or config.MINIMAX_BASE_URL).rstrip("/")
    if not effective_key:
        raise HTTPException(status_code=400, detail="API key is required")
    try:
        client = openai.OpenAI(api_key=effective_key, base_url=effective_url)
        resp = await asyncio.to_thread(client.models.list)
        models = [{"id": m.id, "name": getattr(m, "name", m.id)} for m in resp.data]
        models.sort(key=lambda x: x["id"])
        return {"data": models}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


async def process_video_task(video_id: int, video_path: str):
    """视频处理后台任务，带进度报告。"""
    try:
        await update_video(video_id, status="processing")

        # 辅助函数：广播进度
        async def broadcast_progress(step: str, step_label: str, progress: int):
            await update_video(video_id, progress_step=step, progress_pct=progress)
            await broadcast_video_update(video_id, {
                "type": "progress", "step": step,
                "step_label": step_label, "progress": progress,
            })

        frames_dir = config.FRAMES_DIR / str(video_id)

        # 步骤1: 提取音频 (0-15%)
        await broadcast_progress("extracting_audio", "提取音频", 5)
        audio_path = await video_processor.extract_audio_for_whisper(
            video_path, config.TRANSCRIPTS_DIR / str(video_id)
        )
        await broadcast_progress("extracting_audio", "提取音频完成", 15)

        # 步骤2: 音频分段 (15-25%)
        await broadcast_progress("splitting_audio", "音频分段", 18)
        segments = await video_processor.split_audio_into_segments(
            audio_path, config.TRANSCRIPTS_DIR / str(video_id)
        )
        await broadcast_progress("splitting_audio", "音频分段完成", 25)

        # 步骤3: 转录 (25-60%) + 步骤4: 关键帧 (60-85%) 并行
        async def do_extract_frames():
            await broadcast_progress("extracting_frames", "提取关键帧", 60)
            frames = await video_processor.extract_keyframes_to_dir(
                video_path, frames_dir,
                interval=config.FRAME_INTERVAL_SEC,
                max_frames=config.FRAME_MAX_COUNT,
                scale=config.FRAME_SCALE,
                quality=config.FRAME_QUALITY,
            )
            for frame_path, ts in frames:
                await create_frame(video_id, frame_path, ts)
            await update_video(video_id, frame_count=len(frames))
            await broadcast_progress("extracting_frames", "关键帧提取完成", 85)
            return frames

        _TRANSCRIBE_RETRIES = 2

        async def do_transcribe():
            async def on_segment_progress(current: int, total: int):
                pct = 25 + int(35 * current / total)
                label = f"转录中 ({current}/{total})"
                await broadcast_progress("transcribing", label, pct)

            await broadcast_progress("transcribing", "开始转录", 27)

            last_error = None
            for attempt in range(1, _TRANSCRIBE_RETRIES + 1):
                try:
                    if len(segments) > 1:
                        transcript = await transcriber.transcribe_segments(
                            segments, progress_callback=on_segment_progress
                        )
                    else:
                        transcript = await transcriber.transcribe(segments[0][0])
                    break
                except Exception as e:
                    last_error = e
                    if attempt < _TRANSCRIBE_RETRIES:
                        wait = 2 * attempt
                        logger.warning(f"转录失败 (尝试 {attempt}/{_TRANSCRIBE_RETRIES}): {e}，{wait}s 后重试")
                        await broadcast_progress("transcribing", f"转录重试中 ({attempt}/{_TRANSCRIBE_RETRIES})", 27)
                        await asyncio.sleep(wait)
                    else:
                        raise last_error

            transcript_file = config.TRANSCRIPTS_DIR / f"{video_id}.txt"
            transcript_file.write_text(transcript, encoding="utf-8")
            await broadcast_progress("transcribing", "转录完成", 60)
            return transcript

        # 并行执行转录和关键帧提取
        frames_result, transcript_result = await asyncio.gather(
            do_extract_frames(), do_transcribe()
        )

        # 步骤5: 整理结果 (85-100%)
        await broadcast_progress("finalizing", "整理结果", 90)

        duration = 0
        if frames_result:
            duration = frames_result[-1][1] + config.FRAME_INTERVAL_SEC

        await update_video(video_id, duration=duration, progress_step="finalizing", progress_pct=90)
        provider = await get_default_provider()
        if provider:
            await broadcast_progress("indexing", "构建视频阅读索引", 95)
            frames = await get_frames(video_id)
            transcript_file = config.TRANSCRIPTS_DIR / f"{video_id}.txt"
            transcript_text = transcript_file.read_text(encoding="utf-8")
            await build_video_index(await get_video(video_id), frames, transcript_text, provider)
        await update_video(video_id, status="ready", duration=duration,
                           progress_step="done", progress_pct=100)
        await broadcast_video_update(video_id, {
            "status": "ready", "progress": 100, "message": "处理完成",
            "frame_count": len(frames_result),
        })

    except Exception as e:
        logger.error(f"Video processing failed: {e}")
        await update_video(video_id, status="error", error_message=str(e))
        await broadcast_video_update(video_id, {"status": "error", "error": str(e)})


async def broadcast_video_update(video_id: int, data: dict):
    if video_id in sse_connections:
        for queue in sse_connections[video_id]:
            try:
                await queue.put(json.dumps(data, ensure_ascii=False))
            except Exception:
                pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
