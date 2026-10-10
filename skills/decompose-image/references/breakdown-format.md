# The breakdown.json format

Version 2. Every position and size is a **percentage of the canvas width**,
measured from the top-left corner, with x to the right and y downward.
One unit is used for both directions so that circles stay round and
rotations stay meaningful on canvases that are not square. On a canvas
half as tall as it is wide, the bottom edge is at y = 50.

Rotations are in degrees. Positive is clockwise on screen.

## Top level

| Field | Meaning |
|---|---|
| `schema_version` | Version of this format. Currently `2`. |
| `source` | File name of the image that was measured. |
| `canvas` | Size of the original image. See below. |
| `palette` | The colors, most common first. |
| `layers_back_to_front` | Shape names in painting order: first is furthest back. |
| `shapes` | One entry per shape, in the same order. |
| `groups` | Shapes that form one object. Empty until filled in with `rename_shapes.py`. |
| `simplifications` | Plain sentences listing what the breakdown leaves out or assumes. |
| `redraw_match_percent` | When the image is redrawn from the shapes, the share of all the original's pixels that get the right color. A pixel on a soft edge counts as right when it blends the redraw's colors within two pixels of it. Anything left out of the breakdown lowers this number. |

## canvas

| Field | Meaning |
|---|---|
| `width_pixels`, `height_pixels` | Size of the original image. |
| `height_as_percent_of_width` | The y value of the bottom edge. `100` for a square. |
| `units` | A sentence restating the unit rule above. |

## palette entries

| Field | Meaning |
|---|---|
| `name` | Name used by each shape's `color` field. |
| `hex` | The color, as the median of the pixels that have it. |
| `visible_percent` | Share of the image showing this color. |

## shapes entries

Every shape has:

| Field | Meaning |
|---|---|
| `name` | Unique name, also used in `layers_back_to_front`. |
| `primitive` | One of the kinds below. |
| `color` | A palette `name`. |
| `visible_percent` | Share of the image where this shape shows. Hidden parts are not counted. |

The remaining fields depend on the kind.

### circle, ellipse

| Field | Meaning |
|---|---|
| `center_x`, `center_y` | The center. It may lie outside the canvas. |
| `radius_x` | Half the length of the axis closer to horizontal. |
| `radius_y` | Half the length of the other axis. |
| `rotation_degrees` | Tilt of the `radius_x` axis, between -45 and 45. Always `0` for a circle. |

### rectangle, rounded-rectangle

| Field | Meaning |
|---|---|
| `left`, `top` | The top-left corner of the box before it is rotated. |
| `width`, `height` | The size of the box. `width` is the side closer to horizontal. |
| `rotation_degrees` | How far the box is turned about its own center, between -45 and 45. `0` for an upright box. |
| `corner_radius` | Rounded rectangles only: the radius of each corner. |

`left`, `top`, `width`, and `height` describe the box as it would sit if
it were upright. `rotation_degrees` then says how far that box is turned
about its center.

### triangle, polygon

| Field | Meaning |
|---|---|
| `points` | The corners, each as `{"x": ..., "y": ...}`, clockwise on screen starting from the top-most. A corner may lie outside the canvas or under a shape in front. |

A triangle is a polygon with three points.

### irregular

A shape that fits none of the kinds above. It has `left`, `top`, `width`,
`height`, and `rotation_degrees` (always `0`), describing the smallest
upright box around the visible part of the shape, not the shape itself.

## groups entries

| Field | Meaning |
|---|---|
| `name` | Name of the object. |
| `members` | Names of the shapes it is made of. |

## Changes from version 1

- Added `rounded-rectangle`, `triangle`, and `polygon`.
- Rectangles gained `rotation_degrees`.
- `redraw_match_percent` no longer loses points for soft edges. It still scores every pixel.
