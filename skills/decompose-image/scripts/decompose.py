"""Break a flat-color image down into a palette and a list of simple shapes.

Usage:
    python3 decompose.py IMAGE [--output-folder FOLDER] [--maximum-colors N]

Writes three files into the output folder (default: next to the image):
    breakdown.json         palette, shapes, and layer order, for programs
    breakdown.md           the same information, for people
    breakdown-preview.png  the original beside a redraw made from the shapes

The work is split across four modules, in the order they run:
    image_regions.py     find the palette and split the image into regions
    layer_order.py       work out which shape is in front of which
    primitives.py        fit a rectangle, ellipse, or polygon to each region
    breakdown_report.py  name the shapes, write the breakdown, and redraw

All positions and sizes in the output are percentages of the canvas WIDTH,
measured from the top-left corner. Using one unit for both directions keeps
circles round and rotations meaningful on canvases that are not square.

Limits: built for flat illustrations. Gradients, textures, and outlines are
not modeled, and shapes with curved sides other than circles, ellipses, and
rounded rectangles are reported as "irregular".
"""

import argparse
import json
import pathlib
import sys

import numpy
from PIL import Image
from PIL import UnidentifiedImageError

import breakdown_report
import image_regions
import layer_order


class UnsuitableImageError(ValueError):
    """Raised when nothing in the image can be measured."""


def decompose(image_path, maximum_colors=None, minimum_shape_percent=None):
    """Measures the image and returns (breakdown, preview_image)."""
    if minimum_shape_percent is None:
        minimum_shape_percent = image_regions.DEFAULT_MINIMUM_SHAPE_PERCENT
    image_path = pathlib.Path(image_path)
    pixels, original_size = image_regions.load_working_pixels(image_path)
    unsuitable = UnsuitableImageError(
        f'Nothing to measure in {image_path.name}. Either it has no flat '
        'areas of color (this tool is for flat illustrations, not '
        'photographs or gradients), or --maximum-colors or '
        '--minimum-shape-percent is set so that nothing is left.')
    palette = image_regions.find_palette(pixels, maximum_colors)
    if len(palette) == 0:
        raise unsuitable
    labels = image_regions.label_pixels(pixels, palette)
    region_map = image_regions.find_regions(labels, len(palette),
                                            minimum_shape_percent)
    if not region_map.regions:
        raise unsuitable
    back_to_front, fits = layer_order.find_layer_order(region_map)
    breakdown, redrawn_pixels = breakdown_report.build_breakdown(
        image_path.name, original_size, pixels, palette, region_map,
        back_to_front, fits, minimum_shape_percent)
    side_by_side = numpy.concatenate([pixels, redrawn_pixels], axis=1)
    preview_image = Image.fromarray(side_by_side.astype(numpy.uint8))
    return breakdown, preview_image


def write_breakdown_files(breakdown, output_folder):
    """Writes breakdown.json and breakdown.md into a folder."""
    (output_folder /
     'breakdown.json').write_text(json.dumps(breakdown, indent=2) + '\n')
    (output_folder / 'breakdown.md').write_text(
        breakdown_report.breakdown_as_markdown(breakdown))


def main(arguments):
    """Runs the command-line tool."""
    parser = argparse.ArgumentParser(
        description='Break a flat-color image into a palette and shapes.')
    parser.add_argument('image', type=pathlib.Path)
    parser.add_argument('--output-folder',
                        type=pathlib.Path,
                        help='Where to write the files. Default: next to '
                        'the image.')
    parser.add_argument('--maximum-colors',
                        type=int,
                        help='Keep only this many of the most common colors.')
    parser.add_argument(
        '--minimum-shape-percent',
        type=float,
        default=image_regions.DEFAULT_MINIMUM_SHAPE_PERCENT,
        help='Drop regions smaller than this share of the image.')
    options = parser.parse_args(arguments)
    try:
        breakdown, preview_image = decompose(options.image,
                                             options.maximum_colors,
                                             options.minimum_shape_percent)
    except UnsuitableImageError as error:
        print(error, file=sys.stderr)
        return 1
    except (OSError, UnidentifiedImageError) as error:
        print(f'Could not open {options.image} as an image: {error}',
              file=sys.stderr)
        return 1
    # The folder is made only after measuring succeeds, so a refused image
    # does not leave an empty folder behind.
    output_folder = options.output_folder or options.image.parent
    try:
        output_folder.mkdir(parents=True, exist_ok=True)
        write_breakdown_files(breakdown, output_folder)
        preview_image.save(output_folder / 'breakdown-preview.png')
    except OSError as error:
        print(f'Could not write the breakdown to {output_folder}: {error}',
              file=sys.stderr)
        return 1
    print(
        json.dumps({
            'colors': len(breakdown['palette']),
            'shapes': len(breakdown['shapes']),
            'redraw_match_percent': breakdown['redraw_match_percent'],
            'output_folder': str(output_folder),
        }))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
