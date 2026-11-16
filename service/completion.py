"""Raw completion routing and the newline-only compatibility adapter."""
import asyncio
import json
import secrets
import time
import uuid
from typing import Literal

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from common import Sampling


class Options(Sampling):
    model: str = Field(min_length=1, max_length=101)
    stream: bool = False
    n: Literal[1] = 1
    package_sha256: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")


class Completion(Options):
    prompt: str = Field(min_length=1, max_length=65536)


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system","developer","user","assistant","tool"]
    content: str = Field(max_length=65536)


class Chat(Options):
    messages: list[Message] = Field(min_length=1, max_length=128)


def sse(obj):
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def register(app, record, package):
    async def complete(req, prompt, request, chat):
        state, model = app.state, req.model
        row = record(model)
        if not prompt or len(prompt) > 65536:
            raise HTTPException(400, "Joined prompt must contain 1 to 65536 characters")
        ip = request.client.host if request.client else "unknown"
        who = state.db.identify(request.headers.get("authorization"), ip)
        _, receipt = package(model)
        digest = receipt["package_sha256"]
        if req.package_sha256 and req.package_sha256 != digest:
            raise HTTPException(409, "Requested package differs from the mounted package")
        if who[0] == "research" and not req.package_sha256:
            raise HTTPException(400, "Research requests require package_sha256")
        url = state.urls.get(model)
        if not url:
            raise HTTPException(503, "No worker configured for the preserved model")
        lock = state.locks[model]
        wait = round((state.waiting[model] + lock.locked()) * state.seconds[model])
        if state.waiting[model] >= 4:
            raise HTTPException(429, "Model queue is full", headers={"Retry-After": str(max(1, wait))})
        state.db.charge(who)
        state.waiting[model] += 1
        try:
            await asyncio.wait_for(lock.acquire(), timeout=120)
        except TimeoutError:
            raise HTTPException(429, "Model queue timed out", headers={"Retry-After": str(max(1, wait))})
        finally:
            state.waiting[model] -= 1

        started = time.monotonic()
        response = None
        handed_off = False
        async def close():
            try:
                if response is not None:
                    await response.aclose()
            finally:
                state.seconds[model] = state.seconds[model] * 0.75 + (time.monotonic() - started) * 0.25
                lock.release()

        try:
            # A queued request may outlive a changed or revoked admission receipt.
            if package(model)[1]["package_sha256"] != digest:
                raise HTTPException(409, "Package changed while waiting")
            sampling = {k: getattr(req, k) for k in Sampling.model_fields}
            if sampling["seed"] is None:
                sampling["seed"] = secrets.randbelow(2**31) if req.temperature else 0
            headers = {"Authorization": "Bearer " + state.token, "X-Package-SHA256": digest}
            try:
                upstream = state.client.build_request("POST", url + "/generate", headers=headers,
                                                      json={"prompt": prompt, **sampling})
                response = await state.client.send(upstream, stream=True)
                if response.status_code in (400, 413):
                    raise HTTPException(400, "Prompt and continuation exceed the model context")
                if response.status_code == 429:
                    raise HTTPException(429, "Worker is busy", headers={"Retry-After": "3"})
                if response.status_code != 200 or response.headers.get("X-Package-SHA256") != digest:
                    raise HTTPException(503, "Worker unavailable or package verification failed")
            except httpx.HTTPError:
                raise HTTPException(503, "Worker connection failed")
            state.db.record(model, who[0], prompt)
            meta = {"package_sha256": digest, "sampling": sampling, "quantization": row.get("quantization"),
                    "untrusted": True, "notice": "Unmoderated text from a historical base model.",
                    "base_model": True, "estimated_wait_seconds": wait}
            if chat:
                meta["adapter"] = "Message contents joined with a newline in supplied order."
            base = {"id": ("chatcmpl-" if chat else "cmpl-") + uuid.uuid4().hex,
                    "created": int(time.time()), "model": model, "sanctuary": meta}

            async def events():
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    if "error" in event:
                        raise RuntimeError("Worker interrupted")
                    if "text" in event:
                        yield event
                    elif event.get("finish_reason") in ("length", "stop"):
                        yield event
                        return
                raise RuntimeError("Incomplete worker stream")

            def token_usage(event):
                usage = {"prompt_tokens": event["prompt_tokens"], "completion_tokens": event["completion_tokens"]}
                usage["total_tokens"] = sum(usage.values())
                return usage

            if req.stream:
                async def stream():
                    try:
                        if chat:
                            yield sse({**base, "object":"chat.completion.chunk",
                                       "choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":None}]})
                        async for event in events():
                            piece = event.get("text", "")
                            choice = {"index": 0, "finish_reason": event.get("finish_reason")}
                            if chat:
                                choice["delta"] = {"content": piece} if piece else {}
                            else:
                                choice.update(text=piece, logprobs=None)
                            chunk = {**base, "object":"chat.completion.chunk" if chat else "text_completion", "choices":[choice]}
                            if choice["finish_reason"]:
                                chunk["usage"] = token_usage(event)
                            yield sse(chunk)
                    except (ValueError, KeyError, httpx.HTTPError, RuntimeError):
                        yield sse({"error":{"type":"server_error","message":"Generation interrupted"}})
                    finally:
                        await close()
                    yield "data: [DONE]\n\n"
                reply = StreamingResponse(stream(), media_type="text/event-stream", headers={
                    "Cache-Control":"no-store","X-Accel-Buffering":"no","X-Estimated-Wait":str(wait)})
                handed_off = True
                return reply

            parts = []
            try:
                async for event in events():
                    if "text" in event:
                        parts.append(event["text"])
                choice = {"index":0,"finish_reason":event["finish_reason"]}
                if chat:
                    choice["message"] = {"role":"assistant","content":"".join(parts)}
                else:
                    choice.update(text="".join(parts), logprobs=None)
                return {**base,"object":"chat.completion" if chat else "text_completion",
                        "choices":[choice],"usage":token_usage(event)}
            except (ValueError, KeyError, httpx.HTTPError, RuntimeError):
                raise HTTPException(503, "Generation interrupted")
        finally:
            if not handed_off:
                await close()

    @app.post("/v1/completions")
    async def completions(req: Completion, request: Request):
        """Return newly generated text. Use stream=true for server-sent events."""
        return await complete(req, req.prompt, request, False)

    @app.post("/v1/chat/completions")
    async def chats(req: Chat, request: Request):
        """Join message contents with LF in supplied order without adding roles or templates."""
        return await complete(req, "\n".join(m.content for m in req.messages), request, True)
