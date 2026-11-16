# Verification record

## Offline CPU inference · 16 November 2026

The implemented Transformers engine generated a continuation from the official Pythia-70M weights on Windows with Python 3.12.10, PyTorch 2.8.0+cpu and Transformers 4.57.6. The test downloaded the weight and tokenizer files from EleutherAI's serving companion at revision `a39f36b100fe8a5377810d56c3f4789b9c53ac42`. The 166,029,852-byte safetensors file matched the upstream LFS SHA-256. The test disabled Hub network access during generation and used two CPU threads.

Two independent engine processes consumed the identical UTF-8 prompt `The library opened its doors`, without a trailing newline. They generated 16 new tokens each with greedy decoding, top-p 1 and seed 0. Both returned 61 identical bytes. Their SHA-256 was `88610844db4e2d5277d9505b24716f5584c0b1f67d1269d728290e859397beeb`.

This is a contemporary smoke test of the CPU engine. It establishes neither original-release provenance nor mirror admission. The frozen Linux container needs its own archived golden output, and recovery must be tested on the intended production hardware.

[Exact upstream revision](https://huggingface.co/EleutherAI/pythia-70m/tree/a39f36b100fe8a5377810d56c3f4789b9c53ac42)

## Archive recovery drill

The archive CLI ran with rclone v1.76.0 on a synthetic package. Three local aliases represented independent destinations for this software test. It transferred the package to each alias, streamed each file back for SHA-256 verification, issued a receipt and passed a full audit. A new directory was restored from the second copy using the independently recorded digest. Its contents matched the original bytes. After a test file was altered at the second destination, the next audit failed, wrote an alert and withdrew the receipt.

All three test aliases were on one machine. The production recovery drill requires independent storage providers, the archived model image and a verified model package.

## Visitor hall

Browser checks covered the narrow visitor layout, the desktop index, family filtering, related-model links, suggested text, prompt transfer into comparison, and the unavailable-model response. The illustration and fonts are served by the site itself.
The 12-entry build passed checks for 17 HTML pages and 307 internal links. The FastAPI contract regression passed for raw and SSE responses, the chat adapter, concrete sampling seeds, anonymous access, hashed research keys, quota and Retry-After, seven-day expiry, zero research-prompt rows and rejection after manifest tampering. This suite uses a synthetic worker transport. Four archive unit regressions passed. The Docker Compose generator produced only Caddy and the gateway for an empty-admission archive.
