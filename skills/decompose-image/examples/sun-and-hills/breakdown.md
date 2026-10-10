# Breakdown of original.webp

Canvas: 1600 x 1600 pixels. Every position and size is a percentage of the canvas width, measured from the top-left corner.

## Palette

| Name | Hex | Visible area |
|---|---|---|
| blue | `#74c6f3` | 54.3% |
| purple | `#c2a1e3` | 19.8% |
| green | `#94deba` | 16.7% |
| pink | `#f8bab0` | 8.6% |

## Shapes, back to front

| Shape | Primitive | Color | Position and size |
|---|---|---|---|
| background | rectangle | blue | left 0.0, top 0.0, width 100.0, height 100.0 |
| pink-circle | circle | pink | center 50.0, 49.6; radii 18.6, 18.6; rotated 0.0 degrees clockwise |
| green-ellipse | ellipse | green | center 33.6, 96.5; radii 34.2, 42.5; rotated 3.3 degrees clockwise |
| purple-ellipse | ellipse | purple | center 66.1, 111.5; radii 35.1, 51.0; rotated 10.2 degrees clockwise |

## Simplifications

- Each region is flattened to one color: the median of its pixels.
- Shapes partly hidden behind others are completed from the part of their outline that is visible.

## Accuracy

Redrawing the image from these shapes matches 99.41% of the pixels in the original. See `breakdown-preview.png` (original on the left, redraw on the right).
