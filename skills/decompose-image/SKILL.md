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
- Simple shapes: rectangles, circles, ellipses.

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

- They should look the same apart from slightly crisper edges.
- `redraw_match_percent` should be about 99 or higher for a suitable image.
- If a shape is missing, misplaced, or in the wrong layer, do not hand-edit
  numbers to hide it. Try the options above, and if it still fails, report
  the problem and add it to `simplifications`.

## 4. Give the shapes meaningful names

The script can only name things by color and shape, for example
`pink-circle`. You have seen the picture, so rename each shape after what
it depicts:

| Script's name | After renaming |
|---|---|
| `background` | `sky` |
| `pink-circle` | `sun` |
| `green-ellipse` | `hill-green` |
| `purple-ellipse` | `hill-lavender` |

Rules for names:

- Whole lowercase words joined by hyphens: `tree-trunk`, not `tt` or
  `shape-7`.
- Rename in all three places a name appears: the shape's `name`, the
  `layers_back_to_front` list, and `breakdown.md`.
- Palette names may be renamed the same way (`blue` to `sky`). Update each
  shape's `color` to match.
- Change names only. Never change a measured number.

## 5. Add groups

Fill in `groups` for shapes that form one object:

```json
"groups": [{ "name": "hills", "members": ["hill-green", "hill-lavender"] }]
```

## 6. Report

Tell the user the number of colors and shapes, the `redraw_match_percent`,
and everything listed under `simplifications`, so they know what the
breakdown leaves out.

## Reference

- The meaning of every field: `references/breakdown-format.md`
- A complete worked example: `examples/sun-and-hills/`

## Limits

- Fits rectangles, circles, and ellipses. Anything else (triangles, stars,
  rounded rectangles, free curves) is reported as `irregular` with only its
  bounding box.
- Rectangles are assumed upright. Ellipses may be tilted.
- A shape split in two by a shape in front of it is reported as two shapes.
- Shapes hidden entirely are not found.
