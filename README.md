# image-decomposition-skill

An agent skill that breaks a flat-color image down into a palette, a list of simple shapes, and their layer order.

It works with Claude Code, Codex, and any other agent that reads the open [Agent Skills](https://agentskills.io) format. The skill only measures: it says what is in a picture and where, and leaves how to rebuild it (CSS, SVG, embroidery, paint-by-number) to you.

![A hot air balloon picture beside a redraw made only from the measured shapes](skills/decompose-image/examples/balloon-over-hills/breakdown-preview.png)

*Left: the original. Right: a redraw made only from the ten shapes the skill measured.*

## What you get

For the picture above, the skill reports eight colors and these ten shapes, back to front:

| Shape | Kind | Position and size (percent of canvas width) |
|---|---|---|
| background | rectangle | fills the canvas |
| yellow-polygon | polygon | the star: ten corners |
| yellow-polygon-two | polygon | four corners at (41.1, 54.6), (58.9, 54.8), (54.0, 66.1), (46.1, 66.1) |
| white-ellipse | ellipse | center 20.1, 18.0; radii 9.0, 4.0 |
| white-ellipse-two | ellipse | center 78.1, 32.0; radii 11.0, 5.0 |
| orange-rounded-rectangle | rounded rectangle | left 45.0, top 66.0, width 10.1, height 8.1; corner radius 2.2 |
| green-ellipse | ellipse | center 29.9, 101.6; radii 42.7, 26.6 |
| gray-triangle | triangle | corners at (12.1, 60.0), (20.1, 78.1), (4.0, 78.1) |
| pink-ellipse | ellipse | center 50.1, 38.0; radii 17.0, 19.0 |
| purple-ellipse | ellipse | center 80.2, 110.0; radii 45.2, 32.0 |

Things to notice:

- **Hidden parts are completed.** Both hills run off the bottom of the canvas and one sits behind the other; each is completed from the arc that shows.
- **Layer order is worked out.** The balloon is in front of the yellow piece below it, and the basket is in front of that.
- **Names are placeholders.** The script names by color and kind. The agent, having seen the picture, renames `pink-ellipse` to `balloon` with the bundled renaming tool.

Kinds it can fit: rectangles (upright or tilted), rounded rectangles, circles, ellipses (upright or tilted), triangles, and polygons with up to 12 corners, including stars.

Full outputs are in [`skills/decompose-image/examples/`](skills/decompose-image/examples/), and every field is explained in [`breakdown-format.md`](skills/decompose-image/references/breakdown-format.md).

## Install

The skill is the single folder `skills/decompose-image/`. Copy it to where your agent looks for skills.

```
git clone https://github.com/msgalenwhite/image-decomposition-skill
```

| Agent | For one project | For every project |
|---|---|---|
| Claude Code | `cp -r image-decomposition-skill/skills/decompose-image YOUR-PROJECT/.claude/skills/` | `cp -r image-decomposition-skill/skills/decompose-image ~/.claude/skills/` |
| Codex | `cp -r image-decomposition-skill/skills/decompose-image YOUR-PROJECT/.agents/skills/` | `cp -r image-decomposition-skill/skills/decompose-image ~/.agents/skills/` |

Then install the four Python libraries the script uses:

```
pip install -r skills/decompose-image/requirements.txt
```

## Use

Ask your agent in plain words, for example "break this image down into its colors and shapes". The agent follows [`SKILL.md`](skills/decompose-image/SKILL.md): it checks the image is suitable, runs the script, compares the redraw to the original, and renames the shapes after what they depict (`pink-circle` becomes `sun`).

You can also run the script yourself, without an agent:

```
python3 skills/decompose-image/scripts/decompose.py my-image.png --output-folder my-breakdown
```

It writes `breakdown.json`, `breakdown.md`, and `breakdown-preview.png`. To give the shapes better names afterwards:

```
python3 skills/decompose-image/scripts/rename_shapes.py my-breakdown --shape pink-ellipse=balloon --color blue=sky
```

## Limits

- Built for flat illustrations with few colors. Photographs, gradients, textures, and outlines are not modeled.
- Curved shapes other than circles, ellipses, and rounded rectangles (hearts, clouds, crescents) are reported as `irregular` with only a bounding box.
- A hidden part is a best guess. In the picture above, the yellow piece is closed off straight across where the balloon covers it, and the hills' hidden lower halves are uncertain because only a shallow arc of each shows.
- Layer order comes from overlaps and can be fooled by unusual arrangements, so the skill tells the agent to check it by eye.
- A shape split in two by a shape in front of it is reported as two shapes, and a shape hidden entirely is not found.
- Polygons have at most 12 corners, so a six-pointed star is found and an eight-pointed one is reported as `irregular`. A shape with ten or more even sides bends so gently that it is reported as a circle or ellipse. A side shorter than 2% of the canvas width is treated as a blunted point and dropped, and points sharper than about 20 degrees come back slightly blunt.
- A rounded rectangle is recognized only when all four corners show. Partly hidden, or cut by the canvas edge, it is reported as a plain rectangle or as `irregular`.
- When two touching shapes could each be in front, the choice between them is arbitrary. The redraw looks the same either way, but the layer order may be wrong.
- The accuracy score measures area, so it cannot see very small omissions. A missing shape smaller than about half a percent of the picture still scores above 99.5, and so does a missing band up to about four pixels wide between two shapes whose colors lie either side of its own. The side-by-side preview is the check for those.

## Develop

```
pip install -r requirements-dev.txt
python3 -m pytest
pylint skills tests
yapf --diff --recursive skills tests
```

The tests draw pictures with known shapes and check that the script reports the same shapes back. They cover every kind of shape the script can fit, shapes partly hidden behind others, a shape cut off by the canvas edge, and a 25-shape picture with a time limit. Rules for contributors, human or agent, are in [`AGENTS.md`](AGENTS.md).

## Code Quality & Standards

This repository adheres to the **Google Style Guide**.
Code formatting and static analysis are enforced via `Pylint` and `yapf` within GitHub Actions.

- `.pylintrc` is Google's own published Pylint configuration for the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) (Copyright 2018 Google LLC, Apache License 2.0). The Google style guides are licensed [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/).
- This repo is stricter than Google in one place: names must be whole words of at least three characters, with no single-letter exemptions. Each change is marked inside `.pylintrc`.

## License

[MIT](LICENSE). The sun-and-hills example image was generated with an AI image tool. The balloon example was drawn by code for testing.
