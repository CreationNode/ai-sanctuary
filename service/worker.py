"""Private per-model CPU process with package-verified lazy or resident loading."""
import asyncio
import gc
import hmac
import json
import os
import threading
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from common import Generation, package_metadata, verify_engine_files
from engine import PromptTooLong, engine_name, load_engine


class Runtime:
    def __init__(self):
        self.model = os.environ["SANCTUARY_MODEL_ID"]
        self.folder = Path(os.environ.get("SANCTUARY_ARCHIVE_DIR", "/archive")) / self.model
        self.pin = os.environ["SANCTUARY_PACKAGE_SHA256"]
        self.token = os.environ["SANCTUARY_WORKER_TOKEN"]
        if len(self.token) < 32:
            raise ValueError("Configure at least 32 characters for the worker token")
        self.warm = os.environ.get("SANCTUARY_TIER") == "warm"
        self.lock = asyncio.Lock()
        self.engine = None
        self.digest = None
        self.last = time.monotonic()
        self.loading = False

    def authorize(self, header):
        if not hmac.compare_digest((header or "").encode(), ("Bearer " + self.token).encode()):
            raise HTTPException(401, "Worker authentication required")

    def load(self, expected):
        if expected != self.pin:
            raise ValueError("Worker configured with a different package")
        manifest, receipt = package_metadata(self.folder, self.model, self.pin)
        if self.engine is not None:
            if self.digest != receipt["package_sha256"]:
                raise ValueError("Restart worker to apply changed package")
            return
        self.loading = True
        try:
            verify_engine_files(self.folder, manifest, engine_name(self.folder))
            self.engine = load_engine(self.folder)
            self.digest = receipt["package_sha256"]
        finally:
            self.loading = False

    def unload(self):
        if self.engine is not None:
            self.engine.close()
            self.engine = None
            self.digest = None
            gc.collect()

    async def reap(self):
        while True:
            await asyncio.sleep(15)
            if self.warm and self.engine and time.monotonic() - self.last >= 900 and not self.lock.locked():
                async with self.lock:
                    await asyncio.to_thread(self.unload)


@asynccontextmanager
async def lifespan(app):
    global runtime
    runtime = Runtime()
    package_metadata(runtime.folder, runtime.model, runtime.pin)
    if not runtime.warm:
        await asyncio.to_thread(runtime.load, runtime.pin)
    task = asyncio.create_task(runtime.reap())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await asyncio.to_thread(runtime.unload)


app = FastAPI(lifespan=lifespan, docs_url=None, openapi_url=None, redoc_url=None)


@app.get("/health")
async def health(authorization: str | None = Header(None)):
    runtime.authorize(authorization)
    if runtime.loading:
        state = "loading"
    elif runtime.lock.locked():
        state = "busy"
    else:
        state = "ready" if runtime.engine else "standby"
    return {"model":runtime.model, "state":state, "package_sha256":runtime.digest or runtime.pin}


@app.post("/generate")
async def generate(req: Generation, authorization: str | None = Header(None), x_package_sha256: str = Header()):
    runtime.authorize(authorization)
    if runtime.lock.locked():
        raise HTTPException(429, "Worker is busy", headers={"Retry-After":"3"})
    await runtime.lock.acquire()
    cancel = threading.Event()

    def produce(channel, loop):
        def send(kind, value):
            loop.call_soon_threadsafe(channel.put_nowait, (kind, value))
        try:
            runtime.load(x_package_sha256)
            for event in runtime.engine.events(req, cancel):
                if cancel.is_set():
                    break
                send("event", event)
        except PromptTooLong as exc:
            send("error", (400, str(exc)))
        except Exception:
            send("error", (503, "Worker could not verify or execute this package"))
        finally:
            send("end", None)

    channel = asyncio.Queue()
    job = asyncio.create_task(asyncio.to_thread(produce, channel, asyncio.get_running_loop()))
    def release(_):
        runtime.last = time.monotonic()
        runtime.lock.release()
    job.add_done_callback(release)
    try:
        kind, first = await channel.get()
        if kind == "error":
            raise HTTPException(first[0], first[1])
        if kind != "event":
            raise HTTPException(503, "Worker produced no completion")
    except BaseException:
        cancel.set()
        raise

    async def stream():
        try:
            yield json.dumps(first) + "\n"
            while True:
                kind, value = await channel.get()
                if kind == "event":
                    yield json.dumps(value) + "\n"
                elif kind == "error":
                    yield json.dumps({"error": value[1]}) + "\n"
                    return
                else:
                    return
        finally:
            cancel.set()

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"X-Package-SHA256": x_package_sha256})
