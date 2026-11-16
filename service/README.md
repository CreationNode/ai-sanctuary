# CPU serving

The FastAPI gateway and every model worker run separately. Inference requires a matching receipt issued by the archive pipeline. The public status API reports a model awaiting preservation when its package is absent or fails verification. Each admitted worker checks the SHA-256 of the files that it actually loads and authenticates calls from the gateway.

## Start on a Linux x86-64 host

Install Docker with Compose, Python 3.12, Node.js 22+ and npm. Run these commands from the repository root. Use a DNS name pointing to this host for Caddy automatic HTTPS. Allocate an unused bridge subnet if 172.30.84.0/28 conflicts with an existing network. If changing that subnet, update the pinned reverse-proxy trust address as well.

```sh
npm ci && npm run build
export SANCTUARY_HOST=your-sanctuary.example
export SANCTUARY_WORKER_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
python3 service/compose.py --archive /srv/sanctuary/packages > /srv/sanctuary/compose.json
docker compose -f /srv/sanctuary/compose.json up -d --build
```

Before starting, run `preservation/archive.py ... verify --sha256 ...` for each admitted package against the independent custodian inventory, then `docker load --input /srv/sanctuary/packages/MODEL/runtime/image.tar`. Compose references those saved image IDs with pull disabled. Generate a fresh Compose file and apply it after admitting or replacing a release. Keep the token in your deployment secret store. Its environment reference is resolved when Compose runs. Only Caddy publishes host ports. An empty package directory starts the hall and discovery gateway with inference pending.

One Uvicorn process coordinates bounded per-model queues. Each worker serializes generation. Resident workers load at startup. Warm workers unload after 15 idle minutes and reload on the next request. The status endpoint reports an estimated wait based on queue depth and observed completions. Initial estimates need benchmarking. The default CPU thread budget is four per worker and can be changed using SANCTUARY_CPU_THREADS. Start with a single host. Deploying multiple gateway replicas requires shared queue and quota coordination.

The input is passed without a template. The compatibility chat route joins message bodies using a newline. Research requests include a top-level `package_sha256`. Every output includes the concrete seed, sampling values, package digest, quantization and untrusted-output indicator.

## Keys and data

Anonymous HTTP users omit Authorization. An OpenAI SDK can use `api_key="anonymous"`. Register keys through an operator-controlled email process. Send each generated key privately to its intended recipient. No public email address or delivery service has been configured. Issue keys in the gateway container with `python store.py issue --tier registered` or `python store.py issue --tier research --daily-limit 2000`. The number for a research key must match the actual agreement. Revoke a key with `python store.py revoke`. The revoke command reads the key without echo.

The gateway stores keyed digests of identities for quotas, hashed API keys, aggregate counts, and time-limited abuse records. Anonymous and registered prompt records expire after seven days and are purged on startup and at minute intervals. Research requests omit that record. SQLite enables secure deletion and checkpoints its WAL after purging. Protect the data volume and its parent directory, use encrypted storage and exclude the abuse database from long-lived backups. Keep HTTP access logging disabled for both the gateway and the internal workers. Caddy access logging is off in the provided configuration.

## Local gateway smoke

Install service/gateway.lock in a virtual environment, set SANCTUARY_DB to a private writable SQLite file, then run `python -m uvicorn gateway:app --app-dir service --host 127.0.0.1 --port 8000 --no-access-log`. With no configured worker URLs the gateway serves the registry and accurately rejects generation. The full OpenAPI schema comes from this FastAPI application.

The full image and real-mirror rebuild require a Docker host and provisioned storage. The repository verification record distinguishes offline CPU testing from deployment testing.

The GPT-J record uses the warm Transformers path. Its Q4 conversion has not been qualified against the pinned llama.cpp build. An unquantized GPT-J worker has a higher memory requirement that must be included in capacity testing.
