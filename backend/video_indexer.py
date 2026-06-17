import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import config
from minimax_client import build_index_messages, chat_once


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_seconds(seconds: float) -> str:
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}-{m:02d}-{s:02d}"


def parse_timestamp_seconds(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    raise ValueError(f"Invalid timestamp: {value}")


def parse_transcript_blocks(transcript_text: str) -> list[dict]:
    blocks = []
    lines = transcript_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("**[") and "]**" in line and " - " in line:
            end_marker = line.find("]**")
            stamp = line[3:end_marker]
            start_text, end_text = stamp.split(" - ", 1)
            text_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("**["):
                if lines[i].strip():
                    text_lines.append(lines[i].strip())
                i += 1
            text = "\n".join(text_lines).strip()
            if text:
                blocks.append({
                    "start": parse_timestamp_seconds(start_text),
                    "end": parse_timestamp_seconds(end_text),
                    "text": text,
                })
        else:
            i += 1
    return blocks


def dedupe_frames(frames: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for frame in sorted(frames, key=lambda item: (item["timestamp_sec"], item["id"])):
        key = (round(float(frame["timestamp_sec"]), 2), Path(frame["file_path"]).name)
        if key in seen:
            continue
        seen.add(key)
        result.append(frame)
    return result


def chunk_transcript(blocks: list[dict], chunk_seconds: int) -> list[dict]:
    if not blocks:
        return []
    chunks = []
    current_start = int(blocks[0]["start"])
    current_end = current_start + chunk_seconds
    current = []
    for block in blocks:
        if block["start"] >= current_end and current:
            chunks.append({
                "start": current_start,
                "end": current[-1]["end"],
                "blocks": current,
            })
            current_start = int(block["start"])
            current_end = current_start + chunk_seconds
            current = []
        current.append(block)
    if current:
        chunks.append({
            "start": current_start,
            "end": current[-1]["end"],
            "blocks": current,
        })
    return chunks


def transcript_text_for_chunk(chunk: dict) -> str:
    lines = []
    for block in chunk["blocks"]:
        start = format_seconds(block["start"]).replace("-", ":")
        end = format_seconds(block["end"]).replace("-", ":")
        lines.append(f"[{start} - {end}] {block['text']}")
    return "\n".join(lines)


def frames_for_chunk(frames: list[dict], chunk: dict, max_frames: int) -> list[dict]:
    matched = [
        frame for frame in frames
        if chunk["start"] <= float(frame["timestamp_sec"]) <= chunk["end"]
    ]
    if len(matched) <= max_frames:
        return matched
    step = (len(matched) - 1) / (max_frames - 1)
    selected = []
    for i in range(max_frames):
        selected.append(matched[round(i * step)])
    return selected


def chapter_id(index: int, chunk: dict) -> str:
    start = format_seconds(chunk["start"])
    end = format_seconds(chunk["end"])
    return f"{index:03d}_{start}_to_{end}"


def chapter_title(summary: str, index: int, time_range: str) -> str:
    generic_titles = {"章节标题", "标题", "本章标题"}
    previous_was_generic_heading = False
    for line in summary.splitlines():
        text = line.strip()
        if text.startswith("#"):
            title = text.lstrip("#").strip()
            if title and title not in generic_titles:
                return title
            previous_was_generic_heading = title in generic_titles
        elif previous_was_generic_heading and text:
            return text
    return f"第 {index:02d} 章 {time_range}"


def write_json(path: Path, data: dict | list) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, data: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


def build_chapter_prompt(video: dict, chunk: dict, transcript_text: str, frames: list[dict]) -> str:
    frame_lines = []
    for idx, frame in enumerate(frames, start=1):
        stamp = format_seconds(float(frame["timestamp_sec"])).replace("-", ":")
        frame_lines.append(f"{idx}. frame_id={frame['id']} time={stamp} file={Path(frame['file_path']).name}")
    return (
        "你是长视频课程索引构建器。请根据本章节转录和随附关键帧，生成可供后续文件阅读工具使用的 Markdown。\n"
        "必须覆盖这一时间窗口内的课程内容，不要只总结开头。请一帧一帧说明画面内容、PPT标题、代码或图示信息。\n\n"
        f"视频：{video['name']}\n"
        f"章节时间：{format_seconds(chunk['start']).replace('-', ':')} - {format_seconds(chunk['end']).replace('-', ':')}\n\n"
        "关键帧列表：\n"
        f"{chr(10).join(frame_lines) if frame_lines else '本章节无关键帧'}\n\n"
        "转录文本：\n"
        f"{transcript_text}\n\n"
        "输出格式：\n"
        "# 章节标题\n"
        "## 时间范围\n"
        "## 本章摘要\n"
        "## 关键知识点\n"
        "## RAG实现步骤或代码线索\n"
        "## 关键帧逐帧注释\n"
        "## 可检索关键词\n"
    )


def build_overview_prompt(video: dict, chapter_summaries: list[dict]) -> str:
    chapter_text = "\n\n".join(
        f"## {item['chapter_id']}\n时间：{item['time_range']}\n\n{item['summary']}"
        for item in chapter_summaries
    )
    return (
        "你是长视频课程总目录生成器。请根据每个章节摘要生成全局课程目录，供后续问答检索使用。\n\n"
        f"视频：{video['name']}\n"
        f"章节数量：{len(chapter_summaries)}\n\n"
        f"{chapter_text}\n\n"
        "输出格式：\n"
        "# 视频总览\n"
        "## 课程主题\n"
        "## 全局时间线\n"
        "## 章节目录\n"
        "## RAG项目实现总流程\n"
        "## 高频关键词\n"
    )


async def build_video_index(video: dict, frames: list[dict], transcript_text: str, provider: dict) -> dict:
    video_id = video["id"]
    root = config.VIDEO_INDEXES_DIR / str(video_id)
    if root.exists():
        shutil.rmtree(root)
    chapters_dir = root / "chapters"
    logs_dir = root / "logs"
    search_dir = root / "search"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    search_dir.mkdir(parents=True, exist_ok=True)

    timeline_log = logs_dir / "timeline.jsonl"
    blocks = parse_transcript_blocks(transcript_text)
    unique_frames = dedupe_frames(frames)
    chunks = chunk_transcript(blocks, config.VIDEO_INDEX_CHUNK_SECONDS)
    manifest_chapters = []
    chapter_summaries = []
    lexical_docs = []

    for idx, chunk in enumerate(chunks, start=1):
        cid = chapter_id(idx, chunk)
        chapter_dir = chapters_dir / cid
        frame_dir = chapter_dir / "frames"
        frame_dir.mkdir(parents=True, exist_ok=True)
        selected_frames = frames_for_chunk(unique_frames, chunk, config.VIDEO_INDEX_MAX_FRAMES_PER_CHUNK)
        transcript_chunk = transcript_text_for_chunk(chunk)
        for frame in selected_frames:
            shutil.copy2(frame["file_path"], frame_dir / Path(frame["file_path"]).name)

        prompt = build_chapter_prompt(video, chunk, transcript_chunk, selected_frames)
        append_jsonl(timeline_log, {
            "time": utc_now(),
            "type": "chapter_prompt",
            "chapter_id": cid,
            "prompt": prompt,
            "frames": selected_frames,
        })
        summary = await chat_once(
            build_index_messages(prompt, selected_frames),
            system_prompt="你负责把长视频课程整理成可检索章节文档，输出 Markdown。",
            api_key=provider["api_key"],
            base_url=provider["base_url"],
            model=provider["model"],
            max_tokens=2048,
            temperature=0.2,
        )
        append_jsonl(timeline_log, {
            "time": utc_now(),
            "type": "chapter_response",
            "chapter_id": cid,
            "response": summary,
        })

        time_range = (
            f"{format_seconds(chunk['start']).replace('-', ':')}-"
            f"{format_seconds(chunk['end']).replace('-', ':')}"
        )
        title = chapter_title(summary, idx, time_range)
        (chapter_dir / "chapter.md").write_text(summary, encoding="utf-8")
        (chapter_dir / "transcript.md").write_text(transcript_chunk, encoding="utf-8")
        frames_md = "\n".join(
            f"| {frame['id']} | {format_seconds(float(frame['timestamp_sec'])).replace('-', ':')} | frames/{Path(frame['file_path']).name} |"
            for frame in selected_frames
        )
        (chapter_dir / "frames.md").write_text(
            "| frame_id | time | file |\n|---|---|---|\n" + frames_md + "\n",
            encoding="utf-8",
        )
        write_json(chapter_dir / "metadata.json", {
            "chapter_id": cid,
            "index": idx,
            "start": chunk["start"],
            "end": chunk["end"],
            "time_range": time_range,
            "title": title,
            "frame_ids": [frame["id"] for frame in selected_frames],
            "transcript_chars": len(transcript_chunk),
        })
        manifest_chapters.append({
            "chapter_id": cid,
            "index": idx,
            "start": chunk["start"],
            "end": chunk["end"],
            "time_range": time_range,
            "title": title,
            "path": f"chapters/{cid}",
        })
        chapter_summaries.append({
            "chapter_id": cid,
            "time_range": time_range,
            "summary": summary,
        })
        lexical_docs.append({
            "chapter_id": cid,
            "time_range": time_range,
            "text": "\n".join([summary, transcript_chunk]),
        })

    overview_prompt = build_overview_prompt(video, chapter_summaries)
    append_jsonl(timeline_log, {
        "time": utc_now(),
        "type": "overview_prompt",
        "prompt": overview_prompt,
    })
    overview = await chat_once(
        build_index_messages(overview_prompt),
        system_prompt="你负责把长视频章节摘要整理成总目录，输出 Markdown。",
        api_key=provider["api_key"],
        base_url=provider["base_url"],
        model=provider["model"],
        max_tokens=3072,
        temperature=0.2,
    )
    append_jsonl(timeline_log, {
        "time": utc_now(),
        "type": "overview_response",
        "response": overview,
    })
    (root / "overview.md").write_text(overview, encoding="utf-8")
    write_json(search_dir / "lexical_index.json", lexical_docs)
    manifest = {
        "video_id": video_id,
        "video_name": video["name"],
        "created_at": utc_now(),
        "chunk_seconds": config.VIDEO_INDEX_CHUNK_SECONDS,
        "max_frames_per_chunk": config.VIDEO_INDEX_MAX_FRAMES_PER_CHUNK,
        "transcript_chars": len(transcript_text),
        "unique_frames": len(unique_frames),
        "chapters": manifest_chapters,
    }
    write_json(root / "manifest.json", manifest)
    return manifest
