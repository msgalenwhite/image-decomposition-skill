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
| `skills/decompose-image/scripts/decompose.py` | The measuring command. Start reading here. |
| `skills/decompose-image/scripts/image_regions.py` | Finds the palette and splits the image into regions. |
| `skills/decompose-image/scripts/layer_order.py` | Works out which shape is in front of which. |
| `skills/decompose-image/scripts/primitives.py` | Fits a rectangle, ellipse, or polygon to a region. |
| `skills/decompose-image/scripts/breakdown_report.py` | Names shapes, writes the breakdown, and redraws the image. |
| `skills/decompose-image/scripts/rename_shapes.py` | Renames shapes and colors in a finished breakdown. |
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

## How to add a new kind of shape

1. Add a fitting function to `primitives.py` that returns a `Primitive`
   or `None`, and a mask function that says which pixels it covers.
2. Add it to the list in `fit_best_primitive`, placed by how flexible it
   is: simpler kinds come first.
3. Teach `breakdown_report.py` how to describe it.
4. Add tests that draw the shape whole, partly hidden, and next to the
   kinds it could be confused with.
5. Document its fields in `references/breakdown-format.md` and raise
   `SCHEMA_VERSION`.

## Before calling work done

1. `python3 -m pytest` passes.
2. `pylint skills tests` and `yapf --diff --recursive skills tests` are
   clean.
3. If the script's output changed, regenerate both examples and look at
   each new `breakdown-preview.png` before committing it:
   `python3 skills/decompose-image/scripts/decompose.py skills/decompose-image/examples/sun-and-hills/original.webp`
   `python3 skills/decompose-image/scripts/decompose.py skills/decompose-image/examples/balloon-over-hills/original.png`
4. Never loosen a test tolerance or a lint rule to make a check pass.
   Stop and ask the owner.
