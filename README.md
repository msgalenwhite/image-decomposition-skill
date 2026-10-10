# image-decomposition-skill

An agent skill that breaks a flat-color image down into a palette, a list of simple shapes, and their layer order.

It works with Claude Code, Codex, and any other agent that reads the open [Agent Skills](https://agentskills.io) format. The skill only measures: it says what is in a picture and where, and leaves how to rebuild it (CSS, SVG, embroidery, paint-by-number) to you.

![The original image beside a redraw made only from the measured shapes](skills/decompose-image/examples/sun-and-hills/breakdown-preview.png)

*Left: the original. Right: a redraw made only from the four shapes the skill measured. They match on 99.41% of pixels.*

## What you get

For the image above, the skill reports:

| Shape | Primitive | Color | Position and size (percent of canvas width) |
|---|---|---|---|
| background | rectangle | `#74c6f3` | fills the canvas |
| pink-circle | circle | `#f8bab0` | center 50.0, 49.6; radius 18.6 |
| green-ellipse | ellipse | `#94deba` | center 33.6, 96.5; radii 34.2, 42.5; tilted 3.3 degrees |
| purple-ellipse | ellipse | `#c2a1e3` | center 66.1, 111.5; radii 35.1, 51.0; tilted 10.2 degrees |

Both hills are mostly hidden, one behind the other and both below the frame. The skill works out which shape is in front and completes each hidden shape from the part of its outline that shows.

The full output is in [`skills/decompose-image/examples/sun-and-hills/`](skills/decompose-image/examples/sun-and-hills/), and every field is explained in [`breakdown-format.md`](skills/decompose-image/references/breakdown-format.md).

## Install

The skill is the single folder `skills/decompose-image/`. Copy it to where your agent looks for skills.

```
git clone https://github.com/msgalenwhite/image-decomposition-skill
```

| Agent | For one project | For every project |
|---|---|---|
| Claude Code | `cp -r image-decomposition-skill/skills/decompose-image YOUR-PROJECT/.claude/skills/` | `cp -r image-decomposition-skill/skills/decompose-image ~/.claude/skills/` |
| Codex | `cp -r image-decomposition-skill/skills/decompose-image YOUR-PROJECT/.agents/skills/` | `cp -r image-decomposition-skill/skills/decompose-image ~/.agents/skills/` |

Then install the three Python libraries the script uses:

```
pip install -r skills/decompose-image/requirements.txt
```

## Use

Ask your agent in plain words, for example "break this image down into its colors and shapes". The agent follows [`SKILL.md`](skills/decompose-image/SKILL.md): it checks the image is suitable, runs the script, compares the redraw to the original, and renames the shapes after what they depict (`pink-circle` becomes `sun`).

You can also run the script yourself, without an agent:

```
python3 skills/decompose-image/scripts/decompose.py my-image.png --output-folder my-breakdown
```

It writes `breakdown.json`, `breakdown.md`, and `breakdown-preview.png`.

## Limits

- Built for flat illustrations with few colors. Photographs, gradients, textures, and outlines are not modeled.
- Fits rectangles, circles, and ellipses. Any other shape is reported as `irregular` with only its bounding box.
- Rectangles are assumed upright. Ellipses may be tilted.
- A shape split in two by a shape in front of it is reported as two shapes, and a shape hidden entirely is not found.

## Develop

```
pip install -r requirements-dev.txt
python3 -m pytest
pylint skills tests
yapf --diff --recursive skills tests
```

The tests draw pictures with known shapes and check that the script reports the same shapes back, including a circle half hidden behind a rectangle and a tilted ellipse. Rules for contributors, human or agent, are in [`AGENTS.md`](AGENTS.md).

## Code Quality & Standards

This repository adheres to the **Google Style Guide**.
Code formatting and static analysis are enforced via `Pylint` and `yapf` within GitHub Actions.

- `.pylintrc` is Google's own published Pylint configuration for the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) (Copyright 2018 Google LLC, Apache License 2.0). The Google style guides are licensed [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/).
- This repo is stricter than Google in one place: names must be whole words of at least three characters, with no single-letter exemptions. Each change is marked inside `.pylintrc`.

## License

[MIT](LICENSE). The example image was generated with an AI image tool.
