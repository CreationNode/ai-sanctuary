# AI Sanctuary

AI Sanctuary is a visitor hall and raw-completion service for historical, open-weight language models. The founding catalogue covers GPT-2, GPT-Neo, GPT-J and Pythia. Every model has a stable identifier and a reading-room plaque.

## Run the catalogue

Install Node.js 22 or later and npm. From the repository root, run:

```sh
npm ci
npm run build
node check-site.mjs
npm run preview
```

Open http://127.0.0.1:4175/. The static pages, fonts and artwork live in `dist/`. The preview also implements catalogue discovery at `/v1/models`, status at `/v1/status`, and agent documentation at `/.well-known/openapi.json`. Inference requests in this standalone preview return HTTP 503. There are no bundled model weights or claimed production statistics.

## Run the sanctuary

1. **Accession a model.** Select a record in `registry/`. Follow [the archive runbook](preservation/RUNBOOK.md) on an ingest machine with Docker, sufficient scratch space and credentials for the three archive locations. Record the original release evidence separately from the serving companion revision. Verify the original bytes, derived files, built runtime and reference output. Keep a trusted package digest with the custodian.
2. **Test recovery.** On a clean machine, restore by that digest from an independent mirror. Verify the package and load its saved image without contacting the original model publisher. Run the golden prompt and record the result and hardware profile. Repeat for a second mirror to exercise provider loss.
3. **Start serving.** Follow [the CPU service instructions](service/README.md). The production deployment serves the static hall and FastAPI gateway from one origin behind Caddy. The gateway checks admission receipts. The worker verifies its inference files. A newly catalogued model can have a plaque while its serving endpoint is unavailable.
4. **Exercise the public entry points.** Request the model list, raw completion, streamed completion, chat adapter and package manifest. Send the same opening text from a plaque and a client. Check response provenance, quotas, expiry, research retention, idle unload, cancellation and archive failure handling before announcing live inference.
5. **Establish custody.** Place archive-write credentials on the ingest host, restrict server SSH to keys, configure automatic OS security updates, enable object locking where supported and hand a tested recovery record to the designated successor. Record domain control, alert destinations, archive custody, provider accounts, billing ownership and recovery procedures outside this public repository. See [operating checks](MONITORING.md).

A production restore must include observed timings and actual mirror receipts. The one-day rebuild target, CPU latency and monthly budget remain targets until measured on the chosen infrastructure.

## Source map

| Path | Purpose |
| --- | --- |
| `registry/*.yaml` | JSON-compatible YAML records for the site, gateway and ingest |
| `plaques/*.md` | Curatorial text, one source file per checkpoint |
| `hall/`, `eleventy.config.js` | Eleventy visitor hall, reading room and discovery files |
| `service/` | Gateway, CPU workers, key issuance and deployment |
| `preservation/` | Ingest, format conversion, three-copy verification, regression and recovery |
| `catalogue-worker.js`, `build-preview.mjs` | Read-only hosted preview, built from the same registry |
| `check-site.mjs` | Static navigation, catalogue, API schema and admission-state checks |

The serving deployment routes API traffic to Python. The Sites publication is a catalogue preview for review. Current availability on either deployment is visible on its status page. A historic quotation is included only when the exact checkpoint can be tied to its source. Empty samples are identified on the plaque. The charter in the visitor hall is a founding draft.

## Licence and credits

The software and original documentation use the [MIT licence](LICENSE). Each upstream model, quoted output and upstream release document retains its own terms. Registry entries identify the applicable sources. The two locally served typefaces are Baskervville and DM Sans, distributed under the SIL Open Font License. Their licence files are copied into the static build. [Illustration credit and generation prompt](hall/illustration.txt).

[Verification record](VERIFICATION.md)

## Accession status

The initial release includes source-pinned intake recipes for all five corrected Pythia checkpoints, including their native NeoX releases. The GPT-2, GPT-Neo and GPT-J catalogue records identify their source companions. Before ingesting a model, check that its first-release evidence and format-conversion recipe have been completed and reviewed. Model packages, provider receipts, operating agreements and keys are provisioned outside Git.
The [GPT-2 124M evidence inventory](preservation/gpt2-124m-evidence.json) records 10 measured publisher files, including the surviving 117M TensorFlow checkpoint, launch-day code and the licence added six days later. The publisher blobs have later modification dates. Independent corroboration of the February 2019 bytes is still outstanding, so this evidence file does not admit the model to service.