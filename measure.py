"""Measure an admitted checkpoint through the public completions API."""
import argparse
import concurrent.futures
import json
import os
import time
import urllib.error
import urllib.request


def measure(base, model, tokens):
    body = json.dumps({
        "model": model, "prompt": "The library opened its doors", "max_tokens": tokens,
        "temperature": 0, "top_p": 1, "seed": 0, "stream": True,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if key := os.environ.get("SANCTUARY_BENCH_KEY"):
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(base.rstrip("/") + "/completions", data=body, headers=headers)
    start = time.monotonic()
    first = None
    provenance = None
    usage = None
    done = False
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            for raw in response:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    done = True
                    break
                event = json.loads(data)
                if "error" in event:
                    return {"model": model, "error": event["error"]}
                provenance = event.get("sanctuary") or provenance
                usage = event.get("usage") or usage
                if first is None and any(choice.get("text") for choice in event.get("choices", [])):
                    first = time.monotonic() - start
    except urllib.error.HTTPError as exc:
        return {"model": model, "http_status": exc.code, "retry_after": exc.headers.get("Retry-After")}
    except (OSError, ValueError) as exc:
        return {"model": model, "error": str(exc)}
    elapsed = time.monotonic() - start
    return {
        "model": model, "complete": done, "seconds_to_first_text": first,
        "total_seconds": round(elapsed, 4), "usage": usage, "sanctuary": provenance,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="Include /v1 in the gateway URL")
    parser.add_argument("models", nargs="+", help="A separate request runs for each model identifier")
    parser.add_argument("--tokens", type=int, default=64, choices=range(1, 513), metavar="1..512")
    args = parser.parse_args()
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(args.models))) as pool:
        runs = [pool.submit(measure, args.base_url, model, args.tokens) for model in args.models]
        results = [run.result() for run in runs]
    print(json.dumps(results, indent=2))
    return 0 if all(item.get("complete") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
