# Doc reference sync record

- synced against installed Claude Code version: `2.1.185`
- changelog source: https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md (version-keyed, authoritative anchor)
- docs source: code.claude.com/docs (served at HEAD)

## Known gap (do not misrepresent)
Anthropic does NOT publish per-version documentation URLs; doc pages always
reflect the latest release. mentat therefore pins the **version** via the
changelog and treats the fetched docs as "current as of this sync". If the
installed version (`2.1.185`) is older than HEAD docs, treat doc claims about
newly-added flags/commands as possibly-not-present in `2.1.185` and verify with
`claude --help` / the changelog before recommending them.
