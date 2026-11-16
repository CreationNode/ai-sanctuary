"""Ingest, verify, replicate, restore and exercise an AI Sanctuary preservation package."""
import argparse
import contextlib
import datetime as dt
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SHA = re.compile(r"[a-f0-9]{64}")
REV = re.compile(r"[a-f0-9]{40}")
ID = re.compile(r"[a-z0-9][a-z0-9.-]{0,79}")
EU = set("AT BE BG HR CY CZ DE DK EE ES FI FR GR HU IE IT LT LU LV MT NL PL PT RO SE SI SK".split())
BLOCK = 2 ** 20


def require(test, message):
    if not test:
        raise ValueError(message)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
        tmp = Path(out.name)
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def digest(stream, out=None):
    hasher = hashlib.sha256()
    size = 0
    while chunk := stream.read(BLOCK):
        hasher.update(chunk)
        size += len(chunk)
        if out is not None:
            out.write(chunk)
    return hasher.hexdigest(), size


def fingerprint(path):
    with path.open("rb") as stream:
        return digest(stream)


def model_id(value):
    require(isinstance(value, str) and ID.fullmatch(value), "Invalid model ID")
    return value


def relative(value):
    require(isinstance(value, str) and value and "\\" not in value and ":" not in value
            and not any(ord(c) < 32 for c in value), "Invalid package path")
    p = PurePosixPath(value)
    require(not p.is_absolute() and p.as_posix() == value and ".." not in p.parts and p.parts,
            "Package paths must be clean relative paths")
    return p.as_posix()


def https(url):
    u = urlsplit(url)
    require(u.scheme == "https" and u.hostname and not u.username and not u.password,
            "Source URLs must use HTTPS without credentials")
    return url


@contextlib.contextmanager
def reader(url):
    with urlopen(Request(https(url), headers={"User-Agent": "AI-Sanctuary-ingest/1"}), timeout=120) as stream:
        https(stream.geturl())
        yield stream


def command(*args, capture=False):
    return subprocess.run([str(a) for a in args], check=True,
                          stdout=subprocess.PIPE if capture else sys.stderr).stdout


def download(url, dest, expected=None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with reader(url) as src, dest.open("xb") as out:
        sha, size = digest(src, out)
    require(size > 0 and (expected is None or sha == expected), "Source hash/size mismatch: " + dest.name)
    return {"sha256": sha, "size": size}


def package_entries(root):
    files = []
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "Symlinks are outside the package format")
        rel = path.relative_to(root).as_posix()
        if path.is_dir() or rel in {"receipt.json", "manifest.json"}:
            continue
        relative(rel)
        require(path.is_file(), "Unsupported file type: " + rel)
        sha, size = fingerprint(path)
        files.append({"path": rel, "sha256": sha, "size": size})
    return files


def check_manifest(manifest, identifier):
    require(manifest.get("schema") == 1 and manifest.get("model_id") == identifier, "Wrong manifest")
    seen = set()
    for f in manifest["files"]:
        key = relative(f["path"])
        require(key.casefold() not in seen and key.casefold() not in {"manifest.json", "receipt.json"},
                "Duplicate or reserved path")
        seen.add(key.casefold())
        require(SHA.fullmatch(f["sha256"]) and type(f["size"]) is int and f["size"] >= 0, "Bad file entry")
    require(seen, "Empty package")


def local(root, identifier, anchor=None):
    path = root / "manifest.json"
    checksum = fingerprint(path)[0]
    require(anchor is None or checksum == anchor, "Package hash differs from custody record")
    m = read_json(path)
    check_manifest(m, identifier)
    require(sorted(m["files"], key=lambda f: f["path"]) == sorted(package_entries(root), key=lambda f: f["path"]),
            "Local inventory or SHA-256 differs from manifest")
    return m, checksum


def snapshot(entry, dest):
    # The registry points to the serving companion. A separate evidence list captures first-release bytes.
    url = https(entry["source_url"]).removesuffix("/").removesuffix(".git")
    repo = urlsplit(url).path.strip("/")
    rev = entry["source_revision"]
    require(urlsplit(url).hostname == "huggingface.co" and re.fullmatch(r"[\w.-]+/[\w.-]+", repo)
            and REV.fullmatch(rev), "Need a fully pinned Hugging Face serving companion")
    with reader(f"https://huggingface.co/api/models/{repo}/revision/{rev}") as f:
        info = json.load(f)
    require(info["sha"] == rev, "Hub returned a different commit")
    names = [relative(f["rfilename"]) for f in info["siblings"]]
    names = [p for p in names if "/" not in p]
    safe = any(p.endswith(".safetensors") for p in names)
    for name in names:
        metadata = name.endswith((".json", ".txt", ".model", ".tiktoken"))
        weights = name.endswith(".safetensors") if safe else name.endswith(".bin")
        if metadata or weights:
            download(f"{url}/resolve/{rev}/{quote(name)}", dest / name)
    require((dest / "config.json").is_file(), "No upstream serving config")


def runtime_context(root, dockerfile):
    src = ROOT / "service"
    dest = root / "runtime" / "source"
    dest.mkdir(parents=True, exist_ok=True)
    # Archive only released worker sources and build-time dependency inputs; runtime secrets never belong here.
    for p in src.rglob("*"):
        if not p.is_file() or p.is_symlink() or any(x.startswith(".") or x in {"__pycache__", "tests", "state"} for x in p.relative_to(src).parts):
            continue
        if p.suffix in {".py", ".toml", ".lock", ".txt", ".sh"} or p.name.startswith("Dockerfile"):
            target = dest / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copyfile(p, target)
    recipe = dest / dockerfile
    lines = []
    for line in recipe.read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^(FROM\s+)(\S+)(.*)$", line, re.I)
        if match:
            ref = match[2]
            require(not ref.startswith(("$", "-")), "Base images must be literal references")
            if "@sha256:" not in ref:
                command("docker", "pull", ref)
                ids = json.loads(command("docker", "image", "inspect", "--format", "{{json .RepoDigests}}", ref, capture=True))
                require(ids and "@sha256:" in ids[0], "Cannot resolve immutable base image")
                ref = ids[0]
            line = match[1] + ref + match[3]
        lines.append(line)
    recipe.write_bytes(("\n".join(lines) + "\n").encode())
    tag = "ai-sanctuary-build:" + uuid.uuid4().hex
    command("docker", "build", "--file", recipe, "--tag", tag, dest)
    image_id = command("docker", "image", "inspect", "--format", "{{.Id}}", tag, capture=True).decode().strip()
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", image_id), "Missing immutable Docker image ID")
    return image_id


def mount(path, target, readonly=True):
    return f"type=bind,src={path.resolve()},dst={target}" + (",readonly" if readonly else "")


def run_image(image, mounts, argv, capture=False, engine=None, threads=None):
    require(argv and isinstance(argv, list) and all(isinstance(s, str) for s in argv), "Container argv must be strings")
    options = []
    if engine is not None:
        require(engine in {"transformers", "gguf"}, "Invalid archived engine")
        options.extend(["--env", "SANCTUARY_ENGINE=" + engine])
    if threads is not None:
        require(isinstance(threads, int) and 1 <= threads <= 256, "Invalid archived thread count")
        options.extend(["--env", f"OMP_NUM_THREADS={threads}", "--env", f"MKL_NUM_THREADS={threads}"])
    for binding in mounts:
        options.extend(["--mount", binding])
    return command("docker", "run", "--rm", "--network", "none", *options, "--entrypoint", argv[0],
                   image, *argv[1:], capture=capture)


def golden(root):
    settings = read_json(root / "runtime/golden.json")
    runtime_image = read_json(root / "runtime/image.json")
    image_id = runtime_image["id"]
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", image_id), "Invalid saved image ID")
    return run_image(image_id, [mount(root, "/package")],
                     ["python", "/app/engine.py", "--package", "/package", "--prompt-file",
                      "/package/runtime/golden-prompt.txt", "--max-tokens", str(settings["max_tokens"])], capture=True, engine=runtime_image["engine"], threads=settings.get("cpu_threads", 4))


def prepare(args, root, entry):
    declared = entry.get("preservation_recipe", "preservation/recipes/" + entry["id"] + ".json")
    if args.recipe is not None:
        recipe = read_json(args.recipe)
    elif isinstance(declared, dict):
        recipe = declared
    else:
        declared_path = ROOT / relative(declared)
        require(declared_path.is_file(), "Missing first-release recipe: " + str(declared_path))
        recipe = read_json(declared_path)
    require(recipe["model_id"] == entry["id"] and recipe["serving_revision"] == entry["source_revision"],
            "Recipe does not match the selected registry revision")
    require(not root.exists(), "Package already exists. Use replicate, audit or a new staging root.")
    originals = recipe["original_files"]
    roles = {x["role"] for x in originals}
    require({"weights", "license", "card", "tokenizer", "config"} <= roles and
            ("code" in roles or recipe.get("original_code_unavailable_reason")), "Incomplete original release evidence")
    require(recipe.get("release_evidence") and recipe.get("redistribution_basis"),
            "Record release and redistribution evidence before admission")
    backend = recipe["serving_engine"]
    require(backend in {"transformers", "gguf"}, "Unknown serving engine")
    require("gguf" in recipe or recipe.get("gguf_unavailable_reason"), "Document GGUF support for this architecture")
    require(backend != "gguf" or "gguf" in recipe, "GGUF serving requires GGUF conversion")
    if entry.get("quantization"):
        require(backend == "gguf", "Registry quantization requires the matching quantized worker")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent, prefix=".prepare-") as tmp:
        stage = Path(tmp) / "package"
        stage.mkdir()
        evidence = []
        for spec in originals:
            path = relative(spec["path"])
            require(SHA.fullmatch(spec["sha256"]) and spec["revision"], "Original needs its upstream release revision and SHA-256")
            stats = download(spec["url"], stage / "original" / path, spec["sha256"])
            evidence.append({**spec, **stats, "downloaded_at": now()})
        companion = Path(tmp) / "companion"
        snapshot(entry, companion)
        safe = stage / "converted/safetensors"
        safe.mkdir(parents=True)
        runtime = stage / "runtime"
        cpu = runtime_context(stage, "Dockerfile.worker")
        shutil.copyfile(HERE / "convert.py", runtime / "convert.py")
        run_image(cpu, [mount(companion, "/input"), mount(safe, "/output", False), mount(runtime, "/workflow")],
                  ["python", "/workflow/convert.py"])
        require(any(safe.glob("*.safetensors")), "Conversion produced no safetensors weights")
        if "gguf" in recipe:
            g = recipe["gguf"]
            require(re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", g["image"]), "Pin GGUF converter by OCI digest")
            command("docker", "pull", g["image"])
            convert_out = Path(tmp) / "gguf"
            convert_out.mkdir()
            for argv in g["steps"]:
                run_image(g["image"], [mount(safe, "/input"), mount(convert_out, "/output", False)], argv)
            generated = convert_out / "model.gguf"
            with generated.open("rb") as f:
                require(f.read(4) == b"GGUF", "Missing GGUF output")
            shutil.copyfile(generated, stage / "converted/model.gguf")
        image_id = runtime_context(stage, "Dockerfile.gguf") if backend == "gguf" else cpu
        command("docker", "save", "--output", runtime / "image.tar", image_id)
        machine = command("docker", "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", image_id, capture=True).decode().strip()
        atomic_write(runtime / "image.json", encoded({"id": image_id, "platform": machine, "engine": backend}))
        freeze = run_image(image_id, [], ["python", "-m", "pip", "freeze", "--all"], capture=True)
        atomic_write(runtime / "installed-requirements.txt", freeze)
        atomic_write(runtime / "golden-prompt.txt", recipe["golden_prompt"].encode("utf-8"))
        atomic_write(runtime / "golden.json", encoded({"max_tokens": 32, "temperature": 0, "top_p": 1, "seed": 0, "cpu_threads": 4}))
        atomic_write(stage / "golden.txt", golden(stage))
        require(golden(stage) == (stage / "golden.txt").read_bytes(), "Repeated greedy baseline differs")
        atomic_write(stage / "registry.yaml", encoded(entry))
        atomic_write(stage / "release-recipe.json", encoded(recipe))
        atomic_write(stage / "source-evidence.json", encoded(evidence))
        lines = ["# Provenance", "", f"Model: {entry['id']}", f"Prepared: {now()}",
                 f"Author source: {entry['original_source_url']}", f"Serving companion: {entry['source_url']} at {entry['source_revision']}",
                 "", recipe["release_evidence"], "", recipe["redistribution_basis"], "",
                 "Originals and their source revisions, byte counts, SHA-256 and acquisition dates are recorded in source-evidence.json."]
        atomic_write(stage / "provenance.md", "\n".join(lines).encode("utf-8"))
        shutil.copyfile(HERE / "archive.py", runtime / "archive.py")
        shutil.copyfile(HERE / "RUNBOOK.md", runtime / "RUNBOOK.md")
        manifest = {"schema": 1, "model_id": entry["id"], "revision": entry["source_revision"],
                    "files": package_entries(stage)}
        atomic_write(stage / "manifest.json", encoded(manifest))
        local(stage, entry["id"])
        stage.rename(root)


def read_mirrors(path):
    mirrors = read_json(path)["mirrors"]
    require(len(mirrors) == 3 and len({m["provider"].lower() for m in mirrors}) == 3,
            "Configure three independently operated mirrors")
    require(mirrors[0]["country"] in EU and mirrors[0]["country"] != mirrors[1]["country"],
            "Primary archive must be in the EU, and secondary in a different country")
    require(len({m["remote"].rstrip("/") for m in mirrors}) == 3 and
            len({m["location"].rstrip("/") for m in mirrors}) == 3, "Mirror addresses must be distinct")
    for m in mirrors:
        require(re.fullmatch(r"[a-zA-Z0-9_-]+:[a-zA-Z0-9._/-]+", m["remote"]) and ".." not in m["remote"],
                "Expected rclone remote:bucket/path")
        u = urlsplit(m["location"])
        require(u.scheme in {"https", "s3"} and u.netloc and not u.username and not u.password and not u.query and not u.fragment,
                "Use a stable, credential-free archive URI")
        require(re.fullmatch(r"[A-Z]{2}", m["country"]), "Set ISO country code for storage jurisdiction")
    return mirrors


def remote_key(m, identifier, sha):
    return m["remote"].rstrip("/") + "/" + identifier + "/" + sha


def remote_fingerprint(key):
    proc = subprocess.Popen(["rclone", "cat", key], stdout=subprocess.PIPE)
    try:
        with proc.stdout:
            result = digest(proc.stdout)
        require(proc.wait() == 0, "Read-back failed: " + key)
        return result
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def replicate(root, identifier, mirrors, *, upload):
    m, sha = local(root, identifier)
    files = [*m["files"], {"path": "manifest.json", "sha256": sha, "size": (root / "manifest.json").stat().st_size}]
    results = []
    for mirror in mirrors:
        prefix = remote_key(mirror, identifier, sha)
        for f in files:
            uri = prefix + "/" + f["path"]
            if upload:
                command("rclone", "copyto", "--immutable", "--no-traverse", root / f["path"], uri)
            actual = remote_fingerprint(uri)
            require(actual == (f["sha256"], f["size"]), "Remote SHA-256/size differs: " + uri)
        results.append({k: mirror[k] for k in ("provider", "country")} |
                       {"location": mirror["location"].rstrip("/") + "/" + identifier + "/" + sha,
                        "verified_at": now()})
    receipt = {"schema": 1, "model_id": identifier, "package_sha256": sha, "verified_at": now(), "mirrors": results}
    atomic_write(root / "receipt.json", encoded(receipt))
    return receipt


def restore(root, identifier, mirror, anchor):
    require(SHA.fullmatch(anchor), "Use the manifest SHA-256 from the independent custody record")
    require(not root.exists(), "Restore to an empty destination")
    prefix = remote_key(mirror, identifier, anchor)
    with tempfile.TemporaryDirectory(dir=root.parent, prefix=".restore-") as tmp:
        stage = Path(tmp) / "package"
        stage.mkdir()
        command("rclone", "copyto", prefix + "/manifest.json", stage / "manifest.json")
        require(fingerprint(stage / "manifest.json")[0] == anchor, "Untrusted manifest")
        m = read_json(stage / "manifest.json")
        check_manifest(m, identifier)
        for f in m["files"]:
            dest = stage / f["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            command("rclone", "copyto", prefix + "/" + f["path"], dest)
        local(stage, identifier, anchor)
        stage.rename(root)


@contextlib.contextmanager
def locked(root):
    lock = root.parent / (".lock-" + root.name)
    lock.mkdir()
    try:
        yield
    finally:
        lock.rmdir()


def regress(root, identifier):
    local(root, identifier)
    command("docker", "load", "--input", root / "runtime/image.tar")
    expected = (root / "golden.txt").read_bytes()
    actual = golden(root)
    if expected != actual:
        diff = difflib.unified_diff(expected.decode().splitlines(True), actual.decode().splitlines(True),
                                    fromfile="archived", tofile="current")
        raise ValueError("Greedy output differs\n" + "".join(diff))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, required=True, help="Local mounted packages root")
    p.add_argument("--id", required=True, type=model_id)
    sub = p.add_subparsers(dest="action", required=True)
    for name in ("prepare", "ingest", "replicate", "audit", "restore", "golden", "verify"):
        op = sub.add_parser(name)
        if name in {"prepare", "ingest"}:
            op.add_argument("--registry", type=Path, default=ROOT / "registry", help="Registry directory")
            op.add_argument("--recipe", type=Path, help="Override the registry preservation_recipe")
        if name in {"ingest", "replicate", "audit", "restore"}:
            op.add_argument("--mirrors", type=Path, required=True)
        if name in {"restore", "verify", "audit", "golden", "replicate"}:
            op.add_argument("--sha256", required=name == "restore")
        if name == "restore":
            op.add_argument("--mirror", type=int, choices=(1, 2, 3), default=1)
    args = p.parse_args()
    base = args.archive.resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / args.id
    alert = base / ".alerts" / f"{args.id}-{args.action}.json"
    with locked(root):
        try:
            if args.action in {"audit", "golden", "replicate"} and args.sha256:
                require(fingerprint(root / "manifest.json")[0] == args.sha256, "Custody digest differs")
            if args.action in {"prepare", "ingest"}:
                entry = read_json(args.registry / (args.id + ".yaml"))
                require(entry["id"] == args.id, "Registry ID mismatch")
                prepare(args, root, entry)
            if args.action in {"ingest", "replicate", "audit"}:
                receipt = replicate(root, args.id, read_mirrors(args.mirrors), upload=args.action != "audit")
                print(json.dumps(receipt))
            if args.action == "restore":
                mirrors = read_mirrors(args.mirrors)
                restore(root, args.id, mirrors[args.mirror - 1], args.sha256)
            if args.action == "golden":
                regress(root, args.id)
            if args.action in {"verify", "prepare", "restore"}:
                print(local(root, args.id, getattr(args, "sha256", None))[1])
            alert.unlink(missing_ok=True)
        except Exception as exc:
            if args.action in {"audit", "replicate"}:
                (root / "receipt.json").unlink(missing_ok=True)
            atomic_write(alert, encoded({"model_id": args.id, "action": args.action, "at": now(), "error": str(exc)}))
            raise


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
