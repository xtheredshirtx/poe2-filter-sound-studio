# Project notes for Claude

## Working preferences

- **The user does not use git/GitHub directly. Always handle all version-control
  and GitHub steps for them automatically — they should never have to run a
  command or click through GitHub themselves.** Specifically:
  - After completing a piece of work, commit it (on a feature branch, never
    directly on `main`), push the branch, and open or update the pull request
    with a clear title and description — without being asked each time.
  - Use the `gh` CLI for PRs/issues (the user is authenticated as
    `xtheredshirtx`). Remote is `origin`
    (https://github.com/xtheredshirtx/poe2-filter-sound-studio).
  - Explain in plain language what was pushed and give the PR link; don't assume
    git knowledge.
  - Still pause for confirmation before anything destructive (force-push, history
    rewrite, deleting branches, merging a PR).
  - Commit author identity for this repo: `xtheredshirtx
    <xtheredshirtx@users.noreply.github.com>` (set repo-locally).

## Project layout

This is a Windows desktop app (customtkinter) that edits Path of Exile 2
`.filter` files. Key areas: `main.py` (app/UI), `core/`, `features/`, `ui/`, and
the additive `economy_tier/` package (Economy Tier Visual Preset). Tests live in
`tests/` (`pytest`); lint/type config in `pyproject.toml`. See `README.md` and
`docs/` for details.
