import json
from pathlib import Path

import config


def index_root(video_id: int) -> Path:
    return config.VIDEO_INDEXES_DIR / str(video_id)


def has_video_index(video_id: int) -> bool:
    root = index_root(video_id)
    return (root / "manifest.json").exists() and (root / "overview.md").exists()


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def read_video_manifest(video_id: int) -> dict:
    return read_json(index_root(video_id) / "manifest.json")


def read_video_overview(video_id: int) -> str:
    return (index_root(video_id) / "overview.md").read_text(encoding="utf-8")


def list_video_chapters(video_id: int) -> list[dict]:
    return read_video_manifest(video_id)["chapters"]


def read_video_chapter(video_id: int, chapter_id: str) -> dict:
    chapter_dir = index_root(video_id) / "chapters" / chapter_id
    metadata = read_json(chapter_dir / "metadata.json")
    return {
        "metadata": metadata,
        "chapter": (chapter_dir / "chapter.md").read_text(encoding="utf-8"),
        "transcript": (chapter_dir / "transcript.md").read_text(encoding="utf-8"),
        "frames": (chapter_dir / "frames.md").read_text(encoding="utf-8"),
    }


def query_terms(query: str) -> list[str]:
    terms = []
    current = []
    for ch in query.lower():
        if ch.isascii() and (ch.isalnum() or ch in {"_", "-"}):
            current.append(ch)
        else:
            if current:
                terms.append("".join(current))
                current = []
            if "\u4e00" <= ch <= "\u9fff":
                terms.append(ch)
    if current:
        terms.append("".join(current))
    merged = []
    for idx, term in enumerate(terms):
        merged.append(term)
        if idx + 1 < len(terms) and len(term) == 1 and len(terms[idx + 1]) == 1:
            merged.append(term + terms[idx + 1])
    return [term for term in dict.fromkeys(merged) if term.strip()]


def score_text(text: str, terms: list[str]) -> int:
    source = text.lower()
    score = 0
    for term in terms:
        if term and term in source:
            score += len(term)
    return score


def search_video_index(video_id: int, query: str, limit: int = 4) -> list[dict]:
    docs = read_json(index_root(video_id) / "search" / "lexical_index.json")
    terms = query_terms(query)
    scored = []
    for doc in docs:
        score = score_text(doc["text"], terms)
        if score:
            scored.append({
                "chapter_id": doc["chapter_id"],
                "time_range": doc["time_range"],
                "score": score,
            })
    scored.sort(key=lambda item: item["score"], reverse=True)
    if scored:
        return scored[:limit]
    return [
        {
            "chapter_id": item["chapter_id"],
            "time_range": item["time_range"],
            "score": 0,
        }
        for item in read_video_manifest(video_id)["chapters"][:limit]
    ]


def context_excerpt(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[内容因上下文预算截断]"


def build_context_pack(video_id: int, question: str, max_chars: int = None) -> str:
    budget = max_chars or config.VIDEO_INDEX_CHAT_CONTEXT_CHARS
    manifest = read_video_manifest(video_id)
    overview = read_video_overview(video_id)
    matches = search_video_index(video_id, question)
    parts = [
        f"# 视频阅读上下文\n\n视频：{manifest['video_name']}\n章节数：{len(manifest['chapters'])}",
        "## 全局总览\n" + overview,
        "## 命中章节",
    ]
    used = sum(len(part) for part in parts)
    for match in matches:
        chapter = read_video_chapter(video_id, match["chapter_id"])
        item = (
            f"\n### {match['chapter_id']} ({match['time_range']})\n"
            f"检索分数：{match['score']}\n\n"
            "#### 章节摘要\n"
            f"{chapter['chapter']}\n\n"
            "#### 关键帧目录\n"
            f"{chapter['frames']}\n\n"
            "#### 转录片段\n"
            f"{context_excerpt(chapter['transcript'], 2400)}\n"
        )
        if used + len(item) > budget:
            remain = budget - used
            if remain > 800:
                parts.append(context_excerpt(item, remain))
            break
        parts.append(item)
        used += len(item)
    return "\n\n".join(parts)
