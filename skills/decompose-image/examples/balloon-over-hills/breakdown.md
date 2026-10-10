# Breakdown of original.png

Canvas: 1000 x 1000 pixels. Every position and size is a percentage of the canvas width, measured from the top-left corner.

## Palette

| Name | Hex | Visible area |
|---|---|---|
| blue | `#74c6f3` | 61.1% |
| purple | `#c2a1e3` | 11.1% |
| green | `#94deba` | 10.7% |
| pink | `#f8bab0` | 10.2% |
| white | `#ffffff` | 2.9% |
| yellow | `#fae282` | 1.8% |
| gray | `#36393f` | 1.5% |
| orange | `#966950` | 0.8% |

## Shapes, back to front

| Shape | Primitive | Color | Position and size |
|---|---|---|---|
| background | rectangle | blue | left 0.0, top 0.0, width 100.0, height 100.0 |
| yellow-polygon | polygon | yellow | corners at (84.0, 6.0), (85.9, 10.7), (90.8, 10.8), (86.9, 13.9), (88.2, 18.7), (84.1, 16.0), (79.9, 18.7), (81.2, 13.9), (77.3, 10.8), (82.2, 10.7) |
| yellow-polygon-two | polygon | yellow | corners at (41.1, 54.6), (58.9, 54.8), (54.0, 66.1), (46.1, 66.1) |
| white-ellipse | ellipse | white | center 20.1, 18.0; radii 9.0, 4.0 |
| white-ellipse-two | ellipse | white | center 78.1, 32.0; radii 11.0, 5.0 |
| orange-rounded-rectangle | rounded-rectangle | orange | left 45.0, top 66.0, width 10.1, height 8.1; corner radius 2.2 |
| green-ellipse | ellipse | green | center 29.9, 101.6; radii 42.7, 26.6; rotated -0.3 degrees clockwise |
| gray-triangle | triangle | gray | corners at (12.1, 60.0), (20.1, 78.1), (4.0, 78.1) |
| pink-ellipse | ellipse | pink | center 50.1, 38.0; radii 17.0, 19.0; rotated 0.1 degrees clockwise |
| purple-ellipse | ellipse | purple | center 80.2, 110.0; radii 45.2, 32.0; rotated 0.4 degrees clockwise |

## Simplifications

- Each region is flattened to one color: the median of its pixels.
- Shapes partly hidden behind others are completed from the part of their outline that is visible.

## Accuracy

Redrawing the image from these shapes gives the right color on 99.86% of the original's flat-colored pixels. The blended pixels along edges are not scored. See `breakdown-preview.png` (original on the left, redraw on the right).
