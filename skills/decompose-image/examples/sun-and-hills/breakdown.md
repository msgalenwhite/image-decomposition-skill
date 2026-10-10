# Breakdown of original.webp

Canvas: 1600 x 1600 pixels. Every position and size is a percentage of the canvas width, measured from the top-left corner.

## Palette

| Name | Hex | Visible area |
|---|---|---|
| blue | `#74c6f3` | 54.5% |
| purple | `#c2a1e3` | 20.0% |
| green | `#94deba` | 16.8% |
| pink | `#f8bab0` | 8.7% |

## Shapes, back to front

| Shape | Primitive | Color | Position and size |
|---|---|---|---|
| background | rectangle | blue | left 0.0, top 0.0, width 100.0, height 100.0 |
| pink-circle | circle | pink | center 50.0, 49.6; radii 18.6, 18.6 |
| green-ellipse | ellipse | green | center 33.7, 96.6; radii 34.3, 42.6; rotated 2.8 degrees clockwise |
| purple-ellipse | ellipse | purple | center 66.1, 111.9; radii 35.3, 51.4; rotated 9.9 degrees clockwise |

## Simplifications

- Each region is flattened to one color: the median of its pixels.
- Shapes partly hidden behind others are completed from the part of their outline that is visible.

## Accuracy

Redrawing the image from these shapes gives the right color on 99.84% of the pixels in the original. A soft edge counts as right when it blends the colors that meet there. See `breakdown-preview.png` (original on the left, redraw on the right).
