# Video Index Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use inline execution for this project because the user explicitly requested immediate implementation. Do not use TDD because project instructions forbid red-green testing.

**Goal:** Build a long-video file reading layer that turns transcript and keyframes into chapter files, then injects relevant chapter content into chat.

**Architecture:** Add a backend indexing layer that deduplicates frames, chunks transcript by time, calls MiniMax M3 sequentially per chunk, writes a file directory under `data/video_indexes/{video_id}`, and exposes a read/search tool used by chat. Keep the index builder separate from FastAPI route glue and the OpenAI-compatible client wrapper.

**Tech Stack:** FastAPI, Python, OpenAI-compatible MiniMax API, Markdown/JSONL file store, existing SQLite metadata.

---

## File Map

| File | Responsibility |
|---|---|
| `backend/config.py` | Add video index paths and chunk settings |
| `backend/minimax_client.py` | Add non-streaming M3 call and context-aware chat message builder |
| `backend/video_indexer.py` | Build chapter files from transcript and frames |
| `backend/video_reader_tool.py` | Read/search the generated video index and build chat context packs |
| `backend/main.py` | Add index endpoints, run index after processing, use context pack in chat |
| `md/2026-06-17-video-index-reader-implementation-plan.md` | This implementation plan |

## Task 1: Configuration

| Step | Action |
|---|---|
| 1 | Add `VIDEO_INDEXES_DIR`, `VIDEO_INDEX_CHUNK_SECONDS`, `VIDEO_INDEX_MAX_FRAMES_PER_CHUNK`, `VIDEO_INDEX_CHAT_CONTEXT_CHARS` to `backend/config.py` |
| 2 | Ensure index directory is created with existing data directories |

## Task 2: MiniMax Helper

| Step | Action |
|---|---|
| 1 | Add `chat_once()` to `backend/minimax_client.py` for non-streaming indexing calls |
| 2 | Add `build_index_messages()` for text plus frame image inputs |
| 3 | Add `build_chat_messages_with_context()` to replace truncated transcript injection when an index context pack exists |

## Task 3: Index Builder

| Step | Action |
|---|---|
| 1 | Create `backend/video_indexer.py` |
| 2 | Parse transcript timestamp blocks with string operations |
| 3 | Deduplicate frame rows by timestamp and file path |
| 4 | Chunk transcript into 8 to 12 minute windows |
| 5 | Match frames into each chunk |
| 6 | Call MiniMax M3 sequentially per chapter |
| 7 | Write `manifest.json`, `overview.md`, chapter `chapter.md`, `transcript.md`, `frames.md`, and `model_calls.jsonl` |
| 8 | Log every prompt and model return into JSONL timeline |

## Task 4: File Reader Tool

| Step | Action |
|---|---|
| 1 | Create `backend/video_reader_tool.py` |
| 2 | Implement `has_video_index()`, `read_video_overview()`, `list_video_chapters()` |
| 3 | Implement keyword search over chapter summaries, frame notes, and transcript text |
| 4 | Implement `build_context_pack()` for chat injection |

## Task 5: API Integration

| Step | Action |
|---|---|
| 1 | Add endpoints to inspect and build video index |
| 2 | After video processing reaches ready, build index if a provider exists |
| 3 | In chat, prefer index context pack when available |
| 4 | Fall back to the old transcript and frame path only when index is absent |

## Task 6: Verification

| Step | Action |
|---|---|
| 1 | Compile Python modules |
| 2 | Run a dry build on existing video with the local mock provider when available |
| 3 | Run index build endpoint for video 4 with real provider only if available |
| 4 | Verify files exist under `data/video_indexes/4` |
| 5 | Send a chat request and confirm context pack references chapters beyond the first 18 minutes |
