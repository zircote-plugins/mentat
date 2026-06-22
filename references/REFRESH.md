# Staying up to date with the installed Claude Code version

mentat's diagnostics are only as good as the doc set they reference. This is the
contract for keeping the bundled references aligned with the **installed**
Claude Code version.

## Run

```bash
bash plugins/mentat/scripts/refresh_docs.sh
```

## What it does (and what it deliberately does not)

1. Reads the installed version via `claude --version`.
2. Fetches the upstream, **version-keyed** changelog
   (`anthropics/claude-code` `CHANGELOG.md`) and extracts the section for the
   installed version into `claude-code-docs/changelog-<version>.md`.
3. Verifies each canonical doc page on `code.claude.com/docs` is reachable and
   records `name<TAB>status<TAB>url` in `claude-code-docs/doc-urls.tsv`.
4. Stamps `claude-code-docs/SYNC.md` with the synced version and the gap note.

It does **not** download the rendered doc HTML (a multi-MB JS app, not useful
reference text) and does **not** invent per-version doc URLs — **those do not
exist**; docs are served at HEAD.

## The version gap, stated plainly

Because docs always reflect the latest release, a feature documented online may
not exist in an older installed version. When a diagnosis depends on a specific
flag/command/behaviour:

1. Check `claude-code-docs/changelog-<version>.md` — did it ship by this version?
2. Confirm with `claude --help` on the local install.
3. Only then recommend it.

This keeps recommendations truthful to what the user's actual binary supports.
