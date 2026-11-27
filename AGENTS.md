# Agent Instructions for raad.virtualize

## Writing style

Documentation in this project (README.md, markdown files, code comments) must
use a purely technical voice. Specific rules:

- **No first-person plural.** Do not use "we", "our", or "let's". Write in
  third person or imperative where a subject is needed.
- **No editorial framing.** Avoid sentences that exist only to characterize
  the approach rather than describe it. Examples to avoid:
  - "We invert that."
  - "That is the whole schema."
  - "For a taster of..."
  - "The beauty of this approach is..."
- **No colloquialisms or superlatives.** Avoid informal phrases and
  unqualified praise ("incredibly fast", "elegant solution", "game-changing").
- **Acknowledgements are factual, not effusive.** Credit contributors and
  prior work by stating what they contributed; do not characterize their
  effort or vision.
- **Section headings are noun phrases**, not questions or exclamations.
- **Adverbs that add no information should be cut** ("richly", "simply",
  "easily", "just").

These rules apply when writing or editing any `.md` file in this repository.

## Repository state

- `STATUS.md`: pull requests in flight, the republish queue, open issues,
  decisions and dangling threads. A PR that starts, finishes or parks a
  thread updates it, and its "Last updated" date.
- `LEDGER.md`: facts learned, each with the check that guards it. Add a row
  when a fact is learned; re-run the check before relying on a fact.
- `requests/`: work requests any session can pick up, each with its own
  progress log.

## Credentials and publishing

- Never print credentials, or write them to the repository, logs or tool
  output. Export source.coop keys from the `source-coop` AWS profile, or
  with `source-coop creds --format env`, without echoing them.
- A write to source.coop or any other bucket runs only on an explicit go
  from the maintainer. A session that cannot publish hands over the
  commands as a script for the maintainer to run.
- Check build logs for temporary keys and private paths before they reach a
  public repository.
- Build in the container from a plain clone, not a git worktree (LEDGER,
  2026-11-27).
