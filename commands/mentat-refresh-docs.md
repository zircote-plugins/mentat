---
name: mentat-refresh-docs
description: "Refresh mentat's bundled Claude Code doc references against the installed claude --version so diagnostics stay version-matched"
argument-hint: ""
allowed-tools: ["Bash", "Read"]
---

# /mentat-refresh-docs

Re-sync the bundled doc references to the **installed** Claude Code version.

## Do this

1. Run the refresh script (stdlib + curl, non-destructive — writes only under
   `references/claude-code-docs/`):

   ```bash
   bash ${CLAUDE_PLUGIN_ROOT}/scripts/refresh_docs.sh
   ```

2. It pins `claude --version`, fetches the version-keyed `CHANGELOG.md` and the
   installed version's section, verifies the canonical doc URLs are reachable,
   and stamps `SYNC.md`.
3. Report the synced version and any unreachable URLs.

See `${CLAUDE_PLUGIN_ROOT}/references/REFRESH.md` for the full contract,
including the per-version-docs gap note (docs are served at HEAD; there are no
per-version doc URLs).
