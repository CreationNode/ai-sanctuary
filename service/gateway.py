"""Public gateway. The production deployment runs one process for its bounded worker queues."""
import asyncio
import json
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

import common
from store import database
from completion import register


@asynccontextmanager
async def lifespan(app):
    state = app.state
    state.records = common.catalog()
    state.urls = json.loads(os.getenv("SANCTUARY_WORKERS", "{}"))
    state.token = os.getenv("SANCTUARY_WORKER_TOKEN", "")
    if state.urls and len(state.token) < 32:
        raise ValueError("Worker token needs 32 or more characters")
    state.locks = {m: asyncio.Lock() for m in state.records}
    state.waiting = dict.fromkeys(state.records, 0)
    state.seconds = dict.fromkeys(state.records, 5.0)
    state.db = database()
    state.client = httpx.AsyncClient(timeout=httpx.Timeout(360, connect=3), trust_env=False)

    async def expire():
        while True:
            await asyncio.to_thread(state.db.purge)
            await asyncio.sleep(60)

    task = asyncio.create_task(expire())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await state.client.aclose()


app = FastAPI(title="AI Sanctuary", version="1.0.0", lifespan=lifespan,
              openapi_url="/.well-known/openapi.json", docs_url=None, redoc_url=None)


@app.exception_handler(HTTPException)
async def error(request, exc):
    return JSONResponse({"error": {"message": exc.detail,
                        "type": "request_error" if exc.status_code < 500 else "server_error",
                        "code": str(exc.status_code), "param": None}},
                        status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation(request, exc):
    return await error(request, HTTPException(400, "Invalid request. See /.well-known/openapi.json."))


def record(model):
    if model not in app.state.records:
        raise HTTPException(404, "Unknown model")
    return app.state.records[model]


def package(model):
    record(model)
    try:
        return common.package_metadata(common.ARCHIVE / model, model)
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Awaiting a verified three-copy preservation package")


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [
        {**r, "object": "model", "owned_by": r["lab"],
         "created": int(datetime.fromisoformat(r["release_date"][:10]).replace(tzinfo=timezone.utc).timestamp())}
        for r in app.state.records.values()]}


@app.get("/v1/models/{model}/package")
async def manifest(model: str):
    contents, receipt = package(model)
    return {"manifest": contents, **receipt}


@app.get("/v1/status")
async def status():
    state = app.state
    totals = state.db.monthly()

    async def one(model):
        row = dict(id=model, state="awaiting-preservation", verified_at=None, package_sha256=None,
                   requests_this_month=totals.get(model, 0),
                   estimated_wait_seconds=round((state.waiting[model] + state.locks[model].locked()) * state.seconds[model]))
        try:
            _, receipt = package(model)
            row.update(state="offline", verified_at=receipt["verified_at"], package_sha256=receipt["package_sha256"])
            if model in state.urls:
                response = await state.client.get(state.urls[model] + "/health",
                    headers={"Authorization": "Bearer " + state.token}, timeout=2)
                response.raise_for_status()
                info = response.json()
                if (info["model"] == model and info["state"] in ("ready", "standby", "loading", "busy")
                        and (info["state"] in ("standby", "loading") or info.get("package_sha256") == row["package_sha256"])):
                    row["state"] = info["state"]
        except (HTTPException, httpx.HTTPError, ValueError, KeyError):
            pass
        return row

    return {"month": datetime.now(timezone.utc).strftime("%Y-%m"), "requests_this_month": sum(totals.values()),
            "data": await asyncio.gather(*(one(m) for m in state.records))}


register(app, record, package)
