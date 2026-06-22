#!/usr/bin/env bash
# mentat — refresh bundled Claude Code doc references against the INSTALLED
# Claude Code version. Stdlib tools only (curl). Non-destructive: writes only
# under plugins/mentat/references/claude-code-docs/ and records the synced
# version so drift is always visible.
#
# Mechanism (verified, not hardcoded to nonexistent per-version URLs):
#   1. Pin the installed version via `claude --version`.
#   2. Fetch the version-keyed CHANGELOG.md (entries are headed `## <version>`)
#      from the public repo — this is the authoritative version anchor.
#   3. Verify the current docs landing pages on code.claude.com/docs are
#      reachable and record their HTTP status in an index (docs are served at
#      HEAD as a JS app, not per-version; there are NO /v<version>/ doc URLs,
#      and the rendered HTML is a multi-MB JS shell, so we record pointers and
#      the curated index.md rather than dumping HTML into the repo).
#   4. Stamp references/claude-code-docs/SYNC.md with the version + a gap note.
#
# Usage:  bash plugins/mentat/scripts/refresh_docs.sh
set -euo pipefail

# Prefer the env var Claude Code provides; fall back to deriving from this
# script's own location when run outside the plugin runtime.
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
OUT="${ROOT}/references/claude-code-docs"
mkdir -p "$OUT"

VER="$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo unknown)"
echo "mentat: installed Claude Code version = ${VER}"

CHANGELOG_URL="https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
DOCS=(
  "overview|https://code.claude.com/docs/en/overview"
  "slash-commands|https://code.claude.com/docs/en/slash-commands"
  "sub-agents|https://code.claude.com/docs/en/sub-agents"
  "skills|https://code.claude.com/docs/en/skills"
  "plugins|https://code.claude.com/docs/en/plugins"
  "hooks|https://code.claude.com/docs/en/hooks"
  "troubleshooting|https://code.claude.com/docs/en/troubleshooting"
)

# 1. Full changelog (version-keyed).
if curl -fsSL "$CHANGELOG_URL" -o "${OUT}/CHANGELOG.md"; then
  echo "mentat: fetched CHANGELOG.md"
  # Extract just the section for the installed version, if present.
  if [[ "$VER" != "unknown" ]]; then
    awk -v v="## ${VER}" '
      $0==v {p=1; print; next}
      /^## / && p {exit}
      p {print}
    ' "${OUT}/CHANGELOG.md" > "${OUT}/changelog-${VER}.md" || true
    echo "mentat: extracted changelog section for ${VER}"
  fi
else
  echo "mentat: WARNING could not fetch changelog (offline?). Keeping bundled copy." >&2
fi

# 2. Verify current docs pages are reachable; record status (no HTML dump).
INDEX="${OUT}/doc-urls.tsv"
: > "$INDEX"
for entry in "${DOCS[@]}"; do
  name="${entry%%|*}"; url="${entry##*|}"
  status="$(curl -fsSL -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || echo 000)"
  printf '%s\t%s\t%s\n' "$name" "$status" "$url" >> "$INDEX"
  echo "mentat: doc ${name} -> HTTP ${status}"
done
echo "mentat: wrote ${INDEX}"

# 3. Stamp the sync record with an explicit gap note.
cat > "${OUT}/SYNC.md" <<EOF
# Doc reference sync record

- synced against installed Claude Code version: \`${VER}\`
- changelog source: ${CHANGELOG_URL} (version-keyed, authoritative anchor)
- docs source: code.claude.com/docs (served at HEAD)

## Known gap (do not misrepresent)
Anthropic does NOT publish per-version documentation URLs; doc pages always
reflect the latest release. mentat therefore pins the **version** via the
changelog and treats the fetched docs as "current as of this sync". If the
installed version (\`${VER}\`) is older than HEAD docs, treat doc claims about
newly-added flags/commands as possibly-not-present in \`${VER}\` and verify with
\`claude --help\` / the changelog before recommending them.
EOF
echo "mentat: wrote SYNC.md (version ${VER})"
echo "mentat: refresh complete -> ${OUT}"
