"""
后端冒烟测试 - 验证 Provider + Chat 修复
不依赖真实 API key，使用 mock 服务器验证两条路径：
  1. 成功路径 - mock 返回正常 chunk
  2. 失败路径 - mock 返回 401，验证 SSE error 事件 + 日志

前提：后端已运行在 http://127.0.0.1:8003
运行：python scripts/smoke_chat.py
"""
import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx


BASE = "http://127.0.0.1:8003"
MOCK_BASE = "http://127.0.0.1:18080"


# =================== Mock OpenAI 兼容服务器 ===================
class MockHandler(BaseHTTPRequestHandler):
    """Mock 一个 OpenAI 兼容的 /chat/completions + /v1/models 接口
    行为由 query string 决定：?scenario=success|auth_fail|network_fail
    """

    def log_message(self, format, *args):
        pass  # 静默

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            self._json(200, {"data": [{"id": "MiniMax-M3"}, {"id": "MiniMax-Text-01"}]})
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self):
        if "/chat/completions" in self.path:
            scenario = MOCK_SCENARIO["value"]
            if scenario == "auth_fail":
                self._json(401, {"error": {"message": "Incorrect API key provided", "type": "auth"}})
                return
            if scenario == "network_fail":
                # 立即关闭连接模拟断网
                self.close_connection = True
                return
            # 成功：返回标准 OpenAI 流式 chunk
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunks = [
                {"id": "1", "object": "chunk", "choices": [{"delta": {"content": "你好"}}]},
                {"id": "2", "object": "chunk", "choices": [{"delta": {"content": "，"}}]},
                {"id": "3", "object": "chunk", "choices": [{"delta": {"content": "视频"}}]},
                {"id": "4", "object": "chunk", "choices": [{"delta": {"content": "分析"}}]},
                {"id": "5", "object": "chunk", "choices": [{"delta": {}}], "finish_reason": "stop"},
            ]
            for c in chunks:
                data = f"data: {json.dumps(c, ensure_ascii=False)}\n\n"
                self.wfile.write(data.encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            self._json(404, {"error": "not_found"})

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


MOCK_SCENARIO = {"value": "success"}


def start_mock_server() -> HTTPServer:
    srv = HTTPServer(("127.0.0.1", 18080), MockHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


# =================== 测试逻辑 ===================
async def list_providers(client):
    r = await client.get(f"{BASE}/api/providers")
    r.raise_for_status()
    return r.json()["data"]


async def create_provider(client, name, base_url, api_key, model="MiniMax-M3"):
    r = await client.post(
        f"{BASE}/api/providers",
        data={"name": name, "base_url": base_url, "api_key": api_key, "model": model},
    )
    r.raise_for_status()
    return r.json()["provider_id"]


async def set_default(client, pid):
    r = await client.post(f"{BASE}/api/providers/{pid}/set-default")
    r.raise_for_status()


async def test_provider(client, pid):
    r = await client.post(f"{BASE}/api/providers/{pid}/test")
    return r.json()


async def delete_provider(client, pid):
    r = await client.delete(f"{BASE}/api/providers/{pid}")
    r.raise_for_status()


async def list_conversations(client):
    r = await client.get(f"{BASE}/api/conversations")
    r.raise_for_status()
    return r.json()["data"]


async def send_chat(client, conv_id, message, provider_id):
    events = []
    async with client.stream(
        "POST",
        f"{BASE}/api/conversations/{conv_id}/chat",
        data={"message": message, "provider_id": str(provider_id)},
    ) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                continue
            events.append(json.loads(payload))
    return events


async def run_scenario(name, scenario):
    print(f"\n========== 场景: {name} (mock={scenario}) ==========")
    MOCK_SCENARIO["value"] = scenario
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. 创建 mock provider
        pid = await create_provider(client, f"smoke-{scenario}", f"{MOCK_BASE}/v1", "sk-smoke-test-key")
        print(f"  创建 provider: id={pid}")
        await set_default(client, pid)
        print(f"  设为默认")

        # 2. 测试连通性
        test = await test_provider(client, pid)
        print(f"  test endpoint: {test}")
        if not test.get("ok"):
            print(f"  ❌ test endpoint 失败: {test.get('error')}")
            await delete_provider(client, pid)
            return False

        # 3. 复用已存在的 conversation（避免触发真实视频下载）
        convs = await list_conversations(client)
        if not convs:
            print("  ❌ 没有可用 conversation，请先在前端上传过一个视频")
            await delete_provider(client, pid)
            return False
        cid = convs[0]["id"]
        print(f"  复用 conv={cid} (video_id={convs[0]['video_id']})")

        # 4. 发消息
        try:
            events = await send_chat(client, cid, "简单总结一下", pid)
        except Exception as e:
            print(f"  ❌ 发送异常: {e}")
            await delete_provider(client, pid)
            return False

        # 5. 验证事件
        chunks = [e for e in events if e.get("type") == "chunk"]
        dones = [e for e in events if e.get("type") == "done"]
        errors = [e for e in events if e.get("type") == "error"]
        full = "".join(c.get("content", "") for c in chunks)
        print(f"  事件统计: chunk={len(chunks)} done={len(dones)} error={len(errors)}")
        print(f"  拼接内容: {full!r}")

        # 6. 清理
        await delete_provider(client, pid)
        print(f"  清理 provider {pid}")

        # 7. 断言
        if scenario == "success":
            ok = len(chunks) > 0 and len(dones) == 1 and "你好" in full
            print(f"  期望: 有 chunk + 1 个 done + 内容含'你好' -> {'✅' if ok else '❌'}")
            return ok
        if scenario == "auth_fail":
            ok = len(errors) == 1 and len(chunks) == 0
            print(f"  期望: 1 个 error + 0 chunk -> {'✅' if ok else '❌'}")
            return ok
    return False


async def main():
    print("启动 mock 服务器...")
    srv = start_mock_server()
    try:
        ok1 = await run_scenario("成功路径", "success")
        ok2 = await run_scenario("鉴权失败", "auth_fail")
    finally:
        srv.shutdown()
        print("\n关闭 mock 服务器")

    print("\n========== 结果汇总 ==========")
    print(f"  成功路径: {'✅ PASS' if ok1 else '❌ FAIL'}")
    print(f"  鉴权失败: {'✅ PASS' if ok2 else '❌ FAIL'}")

    if ok1 and ok2:
        print("\n🎉 所有冒烟测试通过")
        sys.exit(0)
    else:
        print("\n⚠️  有测试失败")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
