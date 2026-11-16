# Preserve and recover a release

Use Python 3.11+, Docker and rclone on the custody host. The tested Transformers image lock targets Linux x86-64 and Python 3.12. Archive writes belong here. Mount released packages read-only on serving machines. Keep the trusted digest inventory and successor access procedure under independent custody.

## Intake

1. Choose a registry record and establish the evidence for its precise release. Keep every original weight shard, tokenizer, configuration, card, licence and published inference code. Original weights and a later Transformers port can be different files. Record their roles separately.
2. Complete the model’s `preservation_recipe`, either inline, as a repository-relative file path, or in the default `preservation/recipes/<model-id>.json`. A catalogue entry with no verified recipe cannot be ingested. Review the rights to redistribute the release and the image layers. The public archive must retain the upstream notices.
3. Configure three rclone remotes with independently operated providers. Copy `mirrors.example.json` into private custody configuration and replace all example endpoints with actual locations and jurisdictions. Use an EU primary and a second provider in a different country. Make the third copy public when redistribution permits. Enable write-once controls or versioning where supported. Restrict the serving host to a read-only copy.
4. Budget space for the original release, companion files, converted weights, image tar and temporary conversion data. Build on the deployment CPU architecture. The converter image runs offline with read-only input and a separate output directory.

From the repository root, set MODEL to a registry identifier and run:

```sh
python3 preservation/archive.py --archive /srv/sanctuary/packages --id "$MODEL" prepare
python3 preservation/archive.py --archive /srv/sanctuary/packages --id "$MODEL" replicate --mirrors /etc/sanctuary/mirrors.json
```

Use `ingest --mirrors /etc/sanctuary/mirrors.json` for both phases. An explicit `--recipe` overrides the registry selection. Each intake verifies the original SHA-256 values, downloads the pinned serving companion, converts it, builds and saves the runtime image and runs the fixed greedy prompt twice. The recipe records any unsupported GGUF architecture. Check the retained image’s installed versions, runtime identity, precision and golden output before accepting the release.

The SHA-256 of the exact manifest bytes identifies the package. Its entries include hashes and lengths for all payload files. The manifest itself and the later mutable verification receipt are outside that list. Each mirror stores files under its prefix, model ID and manifest digest. Replication uses immutable writes and reads back every byte. A receipt exists only after all three inventories verify. Retry interrupted replication against the same package with `replicate`.

Record the accepted digest in the successor’s signed or access-controlled inventory. Use a JSON mapping from each model ID to its real 64-character digest. Keep old immutable prefixes. Prepare a new revision in a fresh staging root and switch its serving mount, pin and custody record together.

## Audit and alerting

Install `schedules/sanctuary.cron` on the archive host. Set its UTC timezone, user, repository path, inventory, remotes, and alert program to their actual values. The alert program receives a JSON event on stdin. Connect it to the custodian’s monitored channel. Exercise a fixture failure and confirm delivery. Monitor the scheduler itself so missed runs are detectable.

The monthly job reads all three copies in full. The weekly job loads the saved image and compares the exact UTF-8 output. Archive the CPU architecture and thread settings. A difference across kernels or hardware is a drift signal to investigate. An audit failure withdraws the local receipt. Synchronize withdrawals and new receipts promptly to serving mounts. Check for a running job before clearing a stale per-model lock following a crash.

## Clean-host recovery drill

Obtain the trusted digest and read-only mirror configuration independently. To recover from storage alone, fetch the manifest at the known digest prefix, hash it, and verify the archived `runtime/archive.py` against its manifest entry before executing it.

```sh
python3 preservation/archive.py --archive /restore/packages --id "$MODEL" restore --mirror 2 --mirrors /etc/sanctuary/mirrors.json --sha256 "$PACKAGE_SHA256"
python3 preservation/archive.py --archive /restore/packages --id "$MODEL" verify --sha256 "$PACKAGE_SHA256"
python3 preservation/archive.py --archive /restore/packages --id "$MODEL" golden --sha256 "$PACKAGE_SHA256"
python3 preservation/archive.py --archive /restore/packages --id "$MODEL" audit --mirrors /etc/sanctuary/mirrors.json --sha256 "$PACKAGE_SHA256"
```

Restore verifies the manifest against the trusted digest before interpreting its paths, rejects duplicate or unsafe entries, hashes the downloaded files and installs the package after verification. If a mirror is lost, restore from a surviving copy, provision the replacement and replicate the trusted release. Keep historic prefixes intact.

The golden command loads `runtime/image.tar`, selects its archived engine and runs the packaged prompt without network access. This establishes that the model can be exercised from the archive. For the whole venue, rebuild the hall and gateway from the repository, generate Compose with the read-only packages and test both visitor and agent entry points before switching DNS. Record actual recovery time, golden result, package hash, whole-package size, read traffic, cold-start latency and throughput. Repeat the drill at succession.
