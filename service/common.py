"""Contracts shared by the gateway, CPU worker and deployment tooling."""
import hashlib
import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


ROOT = Path(__file__).resolve().parent.parent
REGISTRY = Path(os.environ.get("SANCTUARY_REGISTRY_DIR", ROOT / "registry"))
ARCHIVE = Path(os.environ.get("SANCTUARY_ARCHIVE_DIR", ROOT / "archive-data"))
MODEL_ID = re.compile(r"[a-z0-9][a-z0-9.-]{0,100}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")


class Sampling(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    max_tokens: int = Field(200, ge=1, le=512)
    temperature: float = Field(0.8, ge=0, le=2)
    top_p: float = Field(0.95, gt=0, le=1)
    seed: int | None = Field(None, ge=0, le=2**31 - 1)


class Generation(Sampling):
    prompt: str = Field(min_length=1, max_length=65536)


def catalog():
    records = {}
    for path in sorted(REGISTRY.glob("*.yaml")):
        row = json.loads(path.read_text(encoding="utf-8-sig"))
        if row["id"] != path.stem or not MODEL_ID.fullmatch(row["id"]):
            raise ValueError(f"Invalid registry identity in {path.name}")
        records[row["id"]] = row
    return records


def package_metadata(folder, model_id, expected=None):
    raw = (folder / "manifest.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    manifest = json.loads(raw)
    receipt = json.loads((folder / "receipt.json").read_bytes())
    if manifest.get("model_id") != model_id or receipt.get("model_id") != model_id:
        raise ValueError("Package identity mismatch")
    if receipt.get("package_sha256") != digest or (expected and expected != digest):
        raise ValueError("Package digest mismatch")
    mirrors = receipt["mirrors"]
    for field in ("location", "provider", "country", "verified_at"):
        if not all(m.get(field) for m in mirrors):
            raise ValueError("Incomplete mirror verification")
    if (not receipt.get("verified_at") or len(mirrors) != 3
            or len({m["location"] for m in mirrors}) != 3
            or len({m["provider"].casefold() for m in mirrors}) != 3
            or len({m["country"] for m in mirrors}) < 2):
        raise ValueError("Three independent verified copies are required")
    return manifest, receipt


def verify_engine_files(folder, manifest, engine):
    prefix = "converted/safetensors/"
    original = {f["path"]: f for f in manifest["files"]}
    if engine == "gguf":
        names = {"converted/model.gguf"}
    else:
        names = {k for k in original if k.startswith(prefix)}
        on_disk = {(p.relative_to(folder)).as_posix()
                   for p in (folder / prefix).rglob("*") if p.is_file()}
        if not names or names != on_disk:
            raise ValueError("Model directory does not match manifest")
    for name in names:
        entry = original[name]
        path = folder / name
        if (not path.resolve().is_relative_to(folder.resolve())
                or path.stat().st_size != entry["size"]):
            raise ValueError("Invalid inference file")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
                raise ValueError("Inference file checksum mismatch")
