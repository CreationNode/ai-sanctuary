"""Generate a Compose JSON file for the static hall, gateway, and admitted models."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CADDY = "caddy:2-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0"
TOKEN = "${SANCTUARY_WORKER_TOKEN:?set a random worker bearer token}"



def mount(source, target):
    return {"type": "bind", "source": str(source.resolve()), "target": target, "read_only": True}


def admitted(folder, model_id):
    receipt_path = folder / "receipt.json"
    if not receipt_path.exists():
        return None
    manifest = (folder / "manifest.json").read_bytes()
    metadata = json.loads(manifest)
    receipt = json.loads(receipt_path.read_bytes())
    digest = hashlib.sha256(manifest).hexdigest()
    if not (receipt.get("model_id") == metadata.get("model_id") == model_id and receipt.get("package_sha256") == digest):
        raise ValueError("Unmatched receipt for " + model_id)
    mirrors = receipt.get("mirrors", [])
    if len(mirrors) != 3 or len({m["location"] for m in mirrors}) != 3 or not all(m.get("verified_at") for m in mirrors):
        raise ValueError("Incomplete admission evidence for " + model_id)
    image_file = (folder / "runtime/image.json").read_bytes()
    recorded = next(row for row in metadata["files"] if row["path"] == "runtime/image.json")
    if hashlib.sha256(image_file).hexdigest() != recorded["sha256"]:
        raise ValueError("Image identity file changed for " + model_id)
    image = json.loads(image_file)
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image["id"]) or image["engine"] not in ("gguf", "transformers"):
        raise ValueError("Invalid worker image identity for " + model_id)
    return digest, image


def generate(archive):
    registry = ROOT / "registry"
    workers = {}
    endpoints = {}
    for record in sorted(registry.glob("*.yaml")):
        model = json.loads(record.read_text(encoding="utf-8-sig"))
        mid = model["id"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", mid) or record.stem != mid:
            raise ValueError("Unsafe model identity " + mid)
        package = admitted(archive / mid, mid)
        if package is None:
            continue
        digest, image = package
        host = "worker-" + mid.replace(".", "-")
        if host in workers:
            raise ValueError("Worker DNS name collision " + mid)
        endpoints[mid] = "http://" + host + ":8001"
        workers[host] = {
            "image": image["id"], "pull_policy": "never", "restart": "unless-stopped",
            "read_only": True, "init": True, "cap_drop": ["ALL"], "tmpfs": ["/tmp"],
            "security_opt": ["no-new-privileges:true"], "networks": ["workers"],
            "environment": {
                "SANCTUARY_WORKER_TOKEN": TOKEN, "SANCTUARY_MODEL_ID": mid,
                "SANCTUARY_TIER": model["tier"], "SANCTUARY_ENGINE": image["engine"],
                "SANCTUARY_PACKAGE_SHA256": digest, "SANCTUARY_ARCHIVE_DIR": "/archive",
                "SANCTUARY_REGISTRY_DIR": "/registry", "OMP_NUM_THREADS": "${SANCTUARY_CPU_THREADS:-4}",
                "MKL_NUM_THREADS": "${SANCTUARY_CPU_THREADS:-4}", "HF_HOME": "/tmp/hub",
            },
            "volumes": [mount(archive / mid, "/archive/" + mid), mount(registry, "/registry")],
        }
    gateway = {
        "build": {"context": str((ROOT / "service").resolve()), "dockerfile": "Dockerfile.gateway"},
        "command": ["uvicorn","gateway:app","--host","0.0.0.0","--port","8000","--workers","1",
                    "--no-access-log","--proxy-headers","--forwarded-allow-ips","172.30.84.2"],
        "restart": "unless-stopped", "networks": ["front","workers"], "cap_drop": ["ALL"],
        "environment": {"SANCTUARY_WORKER_TOKEN": TOKEN, "SANCTUARY_WORKERS": json.dumps(endpoints),
                        "SANCTUARY_ARCHIVE_DIR": "/archive","SANCTUARY_REGISTRY_DIR": "/registry",
                        "SANCTUARY_DB": "/data/sanctuary.sqlite3"},
        "volumes": [mount(registry, "/registry"), mount(archive, "/archive"), "gateway-data:/data"],
    }
    web = {
        "image": CADDY, "restart": "unless-stopped","ports": ["80:80","443:443"],
        "networks": {"front":{"ipv4_address":"172.30.84.2"}},
        "environment":{"SANCTUARY_HOST":"${SANCTUARY_HOST:-localhost}"},
        "volumes":[mount(ROOT/"dist","/srv"),mount(ROOT/"service/Caddyfile","/etc/caddy/Caddyfile"),
                   "caddy-data:/data","caddy-config:/config"],
    }
    return {"name":"ai-sanctuary","services":{"caddy":web,"gateway":gateway,**workers},
            "networks":{"front":{"ipam":{"config":[{"subnet":"172.30.84.0/28"}]}}, "workers":{"internal":True}},
            "volumes":{"gateway-data":{},"caddy-data":{},"caddy-config":{}}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    if not args.archive.is_dir():
        parser.error("Supply an existing local package directory")
    json.dump(generate(args.archive.resolve()),sys.stdout,indent=2)
    print()
