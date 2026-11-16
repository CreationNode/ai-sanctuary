# Operating checks

The public status page reads the gateway's current worker state, per-model counts for the UTC month and last three-mirror verification. The private catalogue preview has no production readings.

On an independent monitoring host, run `docker compose -f monitoring.compose.yaml up -d`. The included Uptime Kuma service binds to loopback on port 3001. Open its administrator interface over an SSH tunnel and set the initial admin password. Create an HTTPS monitor for the hall and a JSON monitor for `/v1/status`. For each admitted resident, check its record for a successful serving state. For warm models include standby as healthy. Include loading and busy in a short grace period. A successful HTTP response from the static hall alone cannot establish inference uptime.

Configure the archive host's monthly mirror audit and weekly golden checks using the preservation runbook. Route failures to the custodian's monitored destination, then deliberately fail one fixture audit and verify that the custodian receives the notification. Keep monitor credentials outside the repository.

Use `python measure.py https://YOUR-GATEWAY/v1 pythia-70m` for a streamed HTTP measurement. Supplying two model IDs measures concurrent requests. The optional SANCTUARY_BENCH_KEY environment variable carries a registered testing key. Each run consumes one quota unit per model. On the chosen CPU host, record hardware and OS, image digest, package digest, thread count, model precision and context length. Measure first-token time from a truly unloaded warm worker, steady-state tokens per second, total time and peak resident memory. Repeat while two visitors request different models. Check queue saturation and an abandoned stream. Use these measurements to choose the warm-tier concurrency and publish realistic wait estimates.

A procurement estimate should include original snapshots, all conversions, uncompressed image archives, three independent copies, monthly verification read traffic and recovery egress. Measure one complete package before extrapolating. Funding, hardware capacity, provider prices, quotas and operator time have not been validated.

[Uptime Kuma project](https://github.com/louislam/uptime-kuma) · [PyTorch reproducibility notes](https://docs.pytorch.org/docs/stable/notes/randomness.html)

## Founding collection sizing

The eleven resident registry entries contain approximately 27.1 GiB of FP32 weights, before the tokenizer, allocator, activations, context cache, concurrent requests or the warm GPT-J worker. The five Pythia source inventories alone sum to about 50.8 GB in decimal units because native training checkpoints retain additional state. Neither calculation is a latency or hosting quote.