"""Exercise the public HTTP contract with an explicitly synthetic worker transport."""
import asyncio
import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
import common
import gateway


class GatewayContract(unittest.TestCase):
    def test_entry_points_and_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry, archive = root/"registry", root/"archive"
            mid = "fixture-model"
            registry.mkdir()
            pkg = archive/mid
            pkg.mkdir(parents=True)
            record = dict(id=mid, name="Fixture", lab="Test", release_date="2020-01-01",
                          tier="resident", quantization=None)
            (registry/(mid+".yaml")).write_text(json.dumps(record))
            env = {"SANCTUARY_DB":str(root/"test.db"),"SANCTUARY_WORKERS":json.dumps({mid:"http://fixture"}),
                   "SANCTUARY_WORKER_TOKEN":"test-fixture-only-"*3}
            with patch.dict(os.environ,env), patch.object(common,"ARCHIVE",archive), patch.object(common,"REGISTRY",registry), TestClient(gateway.app) as api:
                req = {"model":mid,"prompt":"A precise prompt.  "}
                assert api.get("/v1/models").json()["data"][0]["id"] == mid
                assert api.get("/v1/status").json()["data"][0]["state"] == "awaiting-preservation"
                assert api.post("/v1/completions",json=req).status_code == 503
                assert api.post("/v1/completions",json={**req,"max_tokens":513}).status_code == 400
                raw = json.dumps(dict(schema=1,model_id=mid,revision="fixture",files=[
                    {"path":"fixture.txt","sha256":hashlib.sha256(b"fixture").hexdigest(),"size":7}])).encode()
                (pkg/"manifest.json").write_bytes(raw)
                digest=hashlib.sha256(raw).hexdigest()
                stamp="2026-01-01T00:00:00Z"
                mirrors=[dict(location=f"https://mirror{i}.invalid",provider=f"test-{i}",country=c,verified_at=stamp)
                         for i,c in enumerate(("DE","NL","US"))]
                receipt=dict(schema=1,model_id=mid,package_sha256=digest,verified_at=stamp,mirrors=mirrors)
                (pkg/"receipt.json").write_text(json.dumps(receipt))
                assert api.get("/v1/models/"+mid+"/package").json()["package_sha256"] == digest
                seen=[]
                def upstream(request):
                    assert request.headers["Authorization"] == "Bearer "+env["SANCTUARY_WORKER_TOKEN"]
                    if request.url.path=="/health":
                        return httpx.Response(200,json=dict(model=mid,state="ready",package_sha256=digest))
                    assert request.headers["X-Package-SHA256"]==digest
                    seen.append(json.loads(request.content))
                    data="\n".join(map(json.dumps,[{"text":" fixture"},{"finish_reason":"length",
                                                  "prompt_tokens":3,"completion_tokens":1}]))
                    return httpx.Response(200,text=data,headers={"X-Package-SHA256":digest})
                original=gateway.app.state.client
                mocked=httpx.AsyncClient(transport=httpx.MockTransport(upstream))
                gateway.app.state.client=mocked
                try:
                    value=api.post("/v1/completions",json=req,headers={"Authorization":"Bearer anonymous"}).json()
                    assert value["choices"][0]["text"]==" fixture" and seen[-1]["prompt"]==req["prompt"]
                    assert seen[-1]["seed"]==value["sanctuary"]["sampling"]["seed"]
                    assert value["sanctuary"]["untrusted"] and value["usage"]["total_tokens"]==4
                    chat={"model":mid,"messages":[{"role":"system","content":"One"},{"role":"user","content":"Two"}],"stream":True}
                    stream=api.post("/v1/chat/completions",json=chat)
                    assert "data: [DONE]" in stream.text and seen[-1]["prompt"]=="One\nTwo"
                    assert api.get("/v1/status").json()["data"][0]["requests_this_month"]==2
                    db=gateway.app.state.db
                    auth={"Authorization":"Bearer "+db.issue("research",1)}
                    assert api.post("/v1/completions",json=req,headers=auth).status_code==400
                    private=dict(req,prompt="private-fixture",package_sha256=digest)
                    assert api.post("/v1/completions",json=private,headers=auth).status_code==200
                    limited=api.post("/v1/completions",json=private,headers=auth)
                    assert limited.status_code==429 and int(limited.headers["Retry-After"])>0
                    with db.connection() as conn:
                        assert conn.execute("SELECT count(*) FROM abuse").fetchone()[0]==2
                        assert not conn.execute("SELECT 1 FROM abuse WHERE prompt=?",("private-fixture",)).fetchone()
                        conn.execute("UPDATE abuse SET expires=?",(int(time.time())-1,))
                    db.purge()
                    with db.connection() as conn:
                        assert conn.execute("SELECT count(*) FROM abuse").fetchone()[0]==0
                    (pkg/"manifest.json").write_bytes(raw+b" ")
                    assert api.post("/v1/completions",json=req).status_code==503
                finally:
                    asyncio.run(mocked.aclose())
                    gateway.app.state.client=original
