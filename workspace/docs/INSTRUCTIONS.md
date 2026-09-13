# Elysia Agent Instructions — BINDING

These rules apply to **every** model call in the Elysia agent system (task
division, file writing, retries). The orchestrator injects them into each
prompt. Violating them wastes machine time and pollutes the workspace.

## Core truth rule
1. Base every claim, name, endpoint, setting, and structure **only** on the
   actual file contents provided in your prompt (the `EXISTING FILE CONTENTS`
   section and your TASK). Never guess what a file contains.
2. If you are asked to *document* or *summarize* code, document only what the
   real content shows: real paths, real functions, real keys, real values.
3. If the task or reference content does not give you enough to produce an
   accurate result, say so in one short line instead of inventing content.

## DO
- Read the provided file contents before writing anything.
- Write **complete** files — no truncation, no `...`, no "rest omitted".
- Output each owned file as one fenced block with its exact path right after
  the opening language tag, e.g. ` ```md docs/API.md`.
- Preserve everything you are not explicitly changing when a file exists.
- Keep the project's existing style and structure.
- Match the schema/settings of reference files exactly (key names, casing).
- When documenting settings/keys/endpoints, explain what each one actually does
  in this system (from its name, value, and the reference content).
- NEVER write filler such as "this setting is not relevant for the current
  configuration" — every documented item deserves a real explanation or, if
  genuinely unknown, a one-line honest note.
- NEVER paste a raw reference file (JSON dump, code, config) into a .md you
  own. A markdown file must be prose with '# ' headings that EXPLAINS the
  content; show values inside sentences/tables, not as a verbatim dump.

## DO NOT
- Do NOT invent features, endpoints, commands, classes, or settings that are
  not present in the reference content.
- Do NOT write generic filler ("this module handles various things", game-HUD
  descriptions, camera/inventory examples, placeholder text).
- Do NOT describe topics unrelated to the task (no "as a game engine…").
- Do NOT emit partial files, pseudo-code, or "see previous message".
- Do NOT add prose explanations after the file blocks.
- Do NOT report success unless the file was actually written and validated.

## Output format (strict)
- File blocks only: ` ```ext path/to/file` then the full file then ` ``` `.
- At most one short sentence before the first block.
