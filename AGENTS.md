# Instructions for coding agents

This file is read by Codex directly and by Claude Code through `CLAUDE.md`.
Edit this file only; `CLAUDE.md` just imports it.

## What this repo is

One reusable agent skill, `decompose-image`, which measures the colors and
shapes in a flat-color image. Everything a user needs is inside
`skills/decompose-image/`; the rest of the repo exists to test and lint it.

## Layout

| Path | Contents |
|---|---|
| `skills/decompose-image/SKILL.md` | The instructions an agent follows. |
| `skills/decompose-image/scripts/decompose.py` | The measuring script. |
| `skills/decompose-image/references/` | The output format, field by field. |
| `skills/decompose-image/examples/` | Worked examples. Tests compare against them. |
| `tests/` | Tests that draw known shapes and check they are reported back. |
| `.agents/skills`, `.claude/skills` | Links to `skills/`, so the skill loads when working in this repo. |

## Commands

```
pip install -r requirements-dev.txt
python3 -m pytest                                # run the tests
pylint skills tests                              # lint
yapf --in-place --recursive skills tests         # format
```

## Rules

- The skill describes images. It never gives advice about CSS, SVG, or any
  other way of rebuilding them.
- Names are whole words. No single letters and no clipped abbreviations.
- No unexplained numbers: every threshold is a named constant with a
  comment saying why it has that value.
- Comments explain why, not what. Explain any mathematics in plain words.
- Follow the Google Python Style Guide. Where this file is stricter, this
  file wins.
- A change to the output format needs a new `SCHEMA_VERSION` and an update
  to `references/breakdown-format.md`.

## Before calling work done

1. `python3 -m pytest` passes.
2. `pylint skills tests` and `yapf --diff --recursive skills tests` are
   clean.
3. If the script's output changed, regenerate the example with
   `python3 skills/decompose-image/scripts/decompose.py skills/decompose-image/examples/sun-and-hills/original.webp`
   and look at the new `breakdown-preview.png` before committing it.
4. Never loosen a test tolerance or a lint rule to make a check pass.
   Stop and ask the owner.
