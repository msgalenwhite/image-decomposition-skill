---
name: decompose-image
description: Break a flat-color image (vector-style illustration, icon, logo, simple AI-generated art) into a palette, a list of simple shapes, and their layer order, written as breakdown.json and breakdown.md. Use when asked to break down, decompose, measure, or analyze an image's colors and shapes, or before recreating an image in another medium. Do not use for photographs, gradients, or heavily textured images.
---

# Decompose an image into colors and shapes

This skill measures an image. It says what is in the picture and where.
It gives no advice on how to rebuild the picture in CSS, SVG, or anything
else; that belongs to whatever uses the breakdown.

## 1. Look at the image first

Open the image and check it suits this skill:

- Flat areas of solid color, with few colors (roughly ten or fewer).
- Simple shapes with clean edges.

If the image is a photograph, or relies on gradients, texture, or outlines,
say so and stop. The numbers would be misleading.

Write down, in a sentence, what the picture shows. You need it in step 4.

## 2. Run the script

```
pip install -r requirements.txt
python3 scripts/decompose.py PATH/TO/IMAGE --output-folder PATH/TO/OUTPUT
```

Paths are relative to this skill's folder. Without `--output-folder` the
files are written next to the image.

| Option | Use it when |
|---|---|
| `--maximum-colors N` | The palette has extra, near-duplicate colors. |
| `--minimum-shape-percent P` | Small real shapes are being dropped (lower it from 0.1), or noise is being reported as shapes (raise it). |

It writes `breakdown.json`, `breakdown.md`, and `breakdown-preview.png`,
and prints the number of colors and shapes and a `redraw_match_percent`.

## 3. Check the result with your own eyes

Open `breakdown-preview.png`: the original is on the left, a redraw made
only from the measured shapes is on the right.

- They should look the same.
- `redraw_match_percent` should be about 99.5 or higher for a suitable
  image. It scores every pixel and forgives only soft edges, so a lower
  number means something in the picture was left out or misplaced. Find
  out what before going on. After using `--maximum-colors` or
  `--minimum-shape-percent`, a low score usually means the option removed
  something real.
- Check the layer order. Shapes that do not touch can come out in any
  order, which is harmless. Shapes that overlap must be the right way round.
- If a shape is missing, misplaced, or in the wrong layer, do not hand-edit
  numbers to hide it. Try the options above, and if it still fails, report
  the problem and add it to `simplifications`.

## 4. Give the shapes meaningful names

The script can only name things by color and kind, for example
`pink-circle`. You have seen the picture, so rename each shape after what
it depicts, and group shapes that form one object:

```
python3 scripts/rename_shapes.py PATH/TO/OUTPUT \
    --shape background=sky --shape pink-circle=sun \
    --shape green-ellipse=hill-green --shape purple-ellipse=hill-lavender \
    --color blue=sky --color pink=sun \
    --group hills=hill-green,hill-lavender
```

The tool renames everywhere a name appears, in both `breakdown.json` and
`breakdown.md`, and refuses a rename that would break something.

Rules for names:

- Whole lowercase words joined by hyphens: `tree-trunk`, not `tt` or
  `shape-7`.
- Name by what the shape depicts, not by its color or kind.
- Change names only. Never change a measured number.

## 5. Report

Tell the user the number of colors and shapes, the `redraw_match_percent`,
and everything listed under `simplifications`, so they know what the
breakdown leaves out.

## Reference

- The meaning of every field: `references/breakdown-format.md`
- Worked examples: `examples/sun-and-hills/` (four shapes) and
  `examples/balloon-over-hills/` (ten shapes of five kinds)

## What it can fit

| Kind | Notes |
|---|---|
| `rectangle` | Upright or tilted. |
| `rounded-rectangle` | Upright only. |
| `circle`, `ellipse` | Ellipses may be tilted. |
| `triangle`, `polygon` | Any straight-sided shape with up to 12 corners, including stars and other shapes with corners pointing inward. |

Shapes partly hidden behind others are completed where the visible part
says how: a hidden corner is rebuilt when the two sides leading to it are
visible, and an ellipse is completed from any visible arc.

## Limits

- Curved shapes other than circles, ellipses, and rounded rectangles
  (hearts, clouds, crescents, free curves) are reported as `irregular`
  with only a bounding box.
- A hidden part is a best guess. When a shape's sides spread apart as
  they pass behind another shape, it is closed off straight across. When
  only a shallow arc of an ellipse shows, its hidden size is uncertain
  even though the visible part is matched.
- Layer order is worked out from overlaps. Unusual arrangements can fool
  it, so always check it in step 3.
- A shape split in two by a shape in front of it is reported as two
  shapes, and a shape hidden entirely is not found.
- Polygons have at most 12 corners: a six-pointed star is found, an
  eight-pointed one is `irregular`. A side shorter than 2% of the canvas
  width is treated as a blunted point and dropped, and points sharper
  than about 20 degrees come back slightly blunt.
- A rounded rectangle is recognized only when all four corners show.
  Partly hidden, or cut by the canvas edge, it comes back as a plain
  rectangle or as `irregular`.
- When two touching shapes could each be in front, the choice between
  them is arbitrary. The redraw looks the same either way.
