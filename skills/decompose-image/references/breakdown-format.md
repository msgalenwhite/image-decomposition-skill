# The breakdown.json format

Version 1. Every position and size is a **percentage of the canvas width**,
measured from the top-left corner, with x to the right and y downward.
One unit is used for both directions so that circles stay round and
rotations stay meaningful on canvases that are not square. On a canvas
half as tall as it is wide, the bottom edge is at y = 50.

## Top level

| Field | Meaning |
|---|---|
| `schema_version` | Version of this format. Currently `1`. |
| `source` | File name of the image that was measured. |
| `canvas` | Size of the original image. See below. |
| `palette` | The colors, most common first. |
| `layers_back_to_front` | Shape names in painting order: first is furthest back. |
| `shapes` | One entry per shape, in the same order. |
| `groups` | Shapes that form one object. Empty until an agent or person fills it in. |
| `simplifications` | Plain sentences listing what the breakdown leaves out or assumes. |
| `redraw_match_percent` | Share of pixels that match when the image is redrawn from the shapes. |

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
| `primitive` | `rectangle`, `circle`, `ellipse`, or `irregular`. |
| `color` | A palette `name`. |
| `visible_percent` | Share of the image where this shape shows. Hidden parts are not counted. |

A `circle` or `ellipse` also has:

| Field | Meaning |
|---|---|
| `center_x`, `center_y` | The center. It may lie outside the canvas. |
| `radius_x` | Half the length of the axis closer to horizontal. |
| `radius_y` | Half the length of the other axis. |
| `rotation_degrees` | Tilt of the `radius_x` axis. Positive is clockwise on screen, between -45 and 45. Always `0` for a circle. |

A `rectangle` or `irregular` shape also has:

| Field | Meaning |
|---|---|
| `left`, `top` | The top-left corner. |
| `width`, `height` | The size. |

For `irregular`, these describe the smallest upright box around the visible
part of the shape, not the shape itself.

## groups entries

| Field | Meaning |
|---|---|
| `name` | Name of the object. |
| `members` | Names of the shapes it is made of. |
