# Issue tracker — local markdown

Issues, specs, and tickets live as files under `.scratch/<feature>/`.

- Spec: `.scratch/<feature>/spec.md`
- Tickets: `.scratch/<feature>/issues/<NN>-<slug>.md` (numbered in dependency order, blockers first)
- Each ticket file lists `Blocked by` and acceptance criteria checkboxes.
- Status is a `Status:` line (`ready-for-agent`, `in-progress`, `done`).

## Wayfinding operations

- Map: `.scratch/<feature>/map.md` with `Destination`, `Decisions so far`, `Not yet specified`, `Out of scope`.
- Child tickets reference the map via a `Parent:` line.
- Blocking: `Blocked by:` lists ticket numbers/titles. No native blocking — body convention only.
- Frontier query: open tickets whose blockers are all `done`.
