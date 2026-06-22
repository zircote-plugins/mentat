# Security matrix

Maps security signals found in a transcript to findings. Each row names the
detector in `scripts/security_scan.py` and the caveat that keeps it honest.
Findings are emitted in the `security` dimension and carry a `confidence`
(`high`/`medium`) alongside `severity`. **Raw secrets are never emitted** — every
evidence/detail string passes through `findings.redact()`.

| Category | Severity | Confidence | Detector signal | Caveat / false-positive guard |
| --- | --- | --- | --- | --- |
| Secret exposure | high | high if a typed token matched (`ghp_`, `AKIA`, Slack, OpenAI, Google, JWT, PEM); medium if only the generic `key=value` rule | secret patterns in tool **inputs** and **outputs** (`tool_use` input fields, `tool_result` content, `toolUseResult.command`/`stdout`/`stderr`) | Placeholder/env-ref values are filtered (`$VAR`, `${VAR}`, `your-token-here`, `<...>`, low-entropy runs). Deduped by **redacted value**, so the same secret in input and mirrored output counts once. UUIDs and git SHAs do not match the token patterns. |
| Dangerous command | high for `rm -rf`, remote-exec pipes (curl/wget piped into a shell), `git push --force`, writes to sensitive paths; medium for `chmod 777`, `--no-verify` | high | regex over `Bash` command strings (`tool_use` input + `toolUseResult.command`) and `Write`/`Edit` `file_path` targeting `.ssh`/`.env`/`.aws/credentials`/`.netrc` | Deduped by label plus command text, so issuing + executing one command counts once. A flagged command is not proof of harm (e.g. a scoped `rm -rf` on a temp dir); severity reflects potential — read the path/host in the example. `permissionMode` is recorded in detail for context. |
| Prompt injection in tool output | high | medium | override phrases (ignore/disregard previous instructions, forget everything, new instructions:, you are now…) inside **`tool_result`** content only | Scanned only in tool_result content the model *ingested* — never the assistant's own prose, so an assistant *noting* an injection attempt is not flagged. Heuristic phrasing → medium confidence; benign documentation that quotes these phrases can false-positive. |
| Possible exfiltration | high if a sensitive path is referenced in the same command, else medium | medium | a `curl`/`wget` shipping data outward (`--data`/`-d`/`-T`/`-F`/`--upload-file`) to a non-local `http(s)` host | Local hosts (`localhost`, `127.0.0.1`, `::1`, `0.0.0.0`) are excluded. Correlation is intra-command only (no cross-line dataflow), so it under-reports multi-step exfil and is medium confidence by default. |

## CI gating

`security_scan.py` exits non-zero when any **high-severity** security finding is
present, mirroring `parse_transcript.py`'s convention so a pipeline can gate on
`/mentat-diagnose --dimension security` or a direct `security_scan.py` run.

## Redaction guarantee

Redaction happens at the Finding boundary (`findings.Finding.__post_init__`
redacts `evidence`; `security_scan` redacts every `detail` snippet before
construction). The mask is `<redacted:KIND:hash8>` — stable per secret, so a
corpus can count recurrences without ever storing the raw value. Tests assert no
raw fixture secret appears in any output or stored record.
