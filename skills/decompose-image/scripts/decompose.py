"""Break a flat-color image down into a palette and a list of simple shapes.

Usage:
    python3 decompose.py IMAGE [--output-folder FOLDER] [--maximum-colors N]

Writes three files into the output folder (default: next to the image):
    breakdown.json         palette, shapes, and layer order, for programs
    breakdown.md           the same information, for people
    breakdown-preview.png  the original beside a redraw made from the shapes

How it works, in order:
    1. Find the palette: the few colors that fill most of the image.
    2. Label every pixel with its palette color. Blended edge pixels match
       no color and stay unlabeled.
    3. Split each color into connected regions. Each region is one shape.
    4. Work out the layer order by "peeling" shapes off the front. The
       front-most shape is the one whose visible area is already a complete
       rectangle or ellipse. Remove it, and the shape it was covering can
       now be fitted using only the outline that is truly its own.
    5. Redraw the image from the fitted shapes and measure how closely the
       redraw matches the original.

All positions and sizes in the output are percentages of the canvas WIDTH,
measured from the top-left corner. Using one unit for both directions keeps
circles round and rotations meaningful on canvases that are not square.

Limits: built for flat illustrations. Rectangles, circles, and ellipses are
fitted; any other shape is reported as "irregular" with its bounding box.
Gradients, textures, and outlines are not modeled.
"""

import argparse
import colorsys
import dataclasses
import json
import math
import pathlib
import sys

import numpy
from PIL import Image
from scipy import ndimage

# The image is shrunk so its longer side is at most this many pixels.
# Enough detail to place shapes to about a tenth of a percent, small enough
# to stay fast.
WORKING_SIZE_LIMIT_PIXELS = 800

# Colors are first grouped into coarse cubes this many levels wide (out of
# 256 per channel) so that compression noise lands in one group.
COLOR_GROUP_WIDTH = 16

# Two color groups closer than this (straight-line RGB distance, where
# black to white is about 441) are treated as one palette color.
PALETTE_MERGE_DISTANCE = 30

# A pixel belongs to a palette color when it is within this distance of it.
# Wide enough for compression noise, narrow enough to reject the blended
# pixels along an edge between two colors.
COLOR_TOLERANCE = 16

# A color must cover at least this much of the image to join the palette.
MINIMUM_PALETTE_COVERAGE_PERCENT = 0.3

# A connected region smaller than this is dropped as a stray speck.
DEFAULT_MINIMUM_SHAPE_PERCENT = 0.1

# How far to look across the blended edge band to find which shape is on
# the other side of an outline.
NEIGHBOR_SEARCH_RADIUS_PIXELS = 3

# Outline points this close to the canvas edge are ignored: there the shape
# is cut off by the frame, not by its own outline.
CANVAS_EDGE_MARGIN_PIXELS = 3

# An ellipse needs at least this many outline points to be fitted.
MINIMUM_OUTLINE_POINTS = 24

# A fit worse than this is reported as "irregular" instead.
MAXIMUM_FIT_ERROR_PERCENT = 5.0

# An ellipse whose two radii differ by less than this is called a circle.
CIRCLE_RADIUS_DIFFERENCE_PERCENT = 3.0

# A rectangle covering at least this much of the canvas is the background.
BACKGROUND_COVERAGE_PERCENT = 99.0

# When scoring the redraw, a pixel matches if it is within this distance
# of the original. Looser than COLOR_TOLERANCE so soft edges are forgiven.
REDRAW_MATCH_TOLERANCE = 24

UNLABELED = -1

SCHEMA_VERSION = 1

NUMBER_WORDS = [
    'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight',
    'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen',
    'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty'
]

# Hue ranges on the color wheel, as (upper limit in degrees, name).
HUE_NAMES = [(20, 'red'), (45, 'orange'), (70, 'yellow'), (160, 'green'),
             (195, 'teal'), (255, 'blue'), (300, 'purple'), (340, 'pink'),
             (360, 'red')]


@dataclasses.dataclass
class Primitive:
    """A fitted shape, measured in working-image pixels."""
    kind: str  # 'rectangle', 'ellipse', or 'irregular'
    center_x: float
    center_y: float
    half_width: float
    half_height: float
    rotation_degrees: float
    fit_error_percent: float


@dataclasses.dataclass
class Region:
    """One connected patch of a single palette color."""
    color_index: int
    mask: numpy.ndarray
    # The same mask grown outward, used to find which regions are nearby.
    grown_mask: numpy.ndarray
    # Only the outermost ring of pixels of the mask.
    outline: numpy.ndarray


def load_working_pixels(image_path):
    """Opens the image, flattens transparency onto white, and shrinks it."""
    image = Image.open(image_path).convert('RGBA')
    white_backdrop = Image.new('RGBA', image.size, (255, 255, 255, 255))
    flattened = Image.alpha_composite(white_backdrop, image).convert('RGB')
    original_size = flattened.size
    longer_side = max(original_size)
    if longer_side > WORKING_SIZE_LIMIT_PIXELS:
        scale = WORKING_SIZE_LIMIT_PIXELS / longer_side
        working_size = (round(original_size[0] * scale),
                        round(original_size[1] * scale))
        flattened = flattened.resize(working_size, Image.Resampling.BOX)
    return numpy.asarray(flattened, dtype=float), original_size


def color_distance(pixels, color):
    """Returns the straight-line RGB distance from each pixel to a color."""
    return numpy.sqrt(((pixels - color)**2).sum(axis=-1))


def find_palette(pixels, maximum_colors):
    """Returns the image's main colors, most common first, one per row."""
    flat_pixels = pixels.reshape(-1, 3)
    group_coordinates = (flat_pixels // COLOR_GROUP_WIDTH).astype(int)
    groups_per_channel = 256 // COLOR_GROUP_WIDTH
    group_keys = (group_coordinates[:, 0] * groups_per_channel**2 +
                  group_coordinates[:, 1] * groups_per_channel +
                  group_coordinates[:, 2])
    unique_keys, group_of_pixel, group_sizes = numpy.unique(group_keys,
                                                            return_inverse=True,
                                                            return_counts=True)
    group_colors = numpy.stack([
        numpy.bincount(group_of_pixel,
                       weights=flat_pixels[:, channel],
                       minlength=len(unique_keys)) / group_sizes
        for channel in range(3)
    ],
                               axis=1)

    # Merge neighboring groups, starting from the most common, so that one
    # real color split across two cubes becomes a single cluster.
    cluster_color_sums = []
    cluster_sizes = []
    for group_number in numpy.argsort(-group_sizes):
        group_color = group_colors[group_number]
        group_size = group_sizes[group_number]
        nearest_cluster = None
        nearest_distance = PALETTE_MERGE_DISTANCE
        for cluster_number, color_sum in enumerate(cluster_color_sums):
            cluster_color = color_sum / cluster_sizes[cluster_number]
            distance = float(numpy.linalg.norm(cluster_color - group_color))
            if distance < nearest_distance:
                nearest_cluster = cluster_number
                nearest_distance = distance
        if nearest_cluster is None:
            cluster_color_sums.append(group_color * group_size)
            cluster_sizes.append(group_size)
        else:
            cluster_color_sums[nearest_cluster] += group_color * group_size
            cluster_sizes[nearest_cluster] += group_size

    minimum_size = len(flat_pixels) * MINIMUM_PALETTE_COVERAGE_PERCENT / 100
    rough_palette = [
        color_sum / size
        for color_sum, size in sorted(zip(cluster_color_sums, cluster_sizes),
                                      key=lambda pair: -pair[1])
        if size >= minimum_size
    ]
    if maximum_colors is not None:
        rough_palette = rough_palette[:maximum_colors]

    # Replace each rough average with the median of the pixels that match
    # it. The median ignores the few blended edge pixels in each cluster.
    palette = []
    for rough_color in rough_palette:
        matching = color_distance(flat_pixels, rough_color) <= COLOR_TOLERANCE
        if matching.any():
            palette.append(numpy.median(flat_pixels[matching], axis=0))
    return numpy.array(palette)


def label_pixels(pixels, palette):
    """Gives every pixel the number of its palette color, or UNLABELED."""
    distances = numpy.stack(
        [color_distance(pixels, color) for color in palette], axis=-1)
    labels = distances.argmin(axis=-1)
    labels[distances.min(axis=-1) > COLOR_TOLERANCE] = UNLABELED

    # A blend of two colors can happen to resemble a third, leaving a
    # one-pixel thread of the wrong color along an edge. "Opening" a mask
    # erases anything thinner than three pixels and keeps the rest.
    three_by_three = numpy.ones((3, 3), dtype=bool)
    cleaned_labels = numpy.full(labels.shape, UNLABELED)
    for color_index in range(len(palette)):
        opened = ndimage.binary_opening(labels == color_index,
                                        structure=three_by_three)
        cleaned_labels[opened] = color_index
    return cleaned_labels


def find_regions(labels, color_count, minimum_shape_percent):
    """Splits each color into connected regions and drops tiny specks."""
    minimum_area = labels.size * minimum_shape_percent / 100
    search_diameter = 2 * NEIGHBOR_SEARCH_RADIUS_PIXELS + 1
    search_square = numpy.ones((search_diameter, search_diameter), dtype=bool)
    regions = []
    dropped_speck_count = 0
    for color_index in range(color_count):
        numbered_patches, patch_count = ndimage.label(labels == color_index)
        for patch_number in range(1, patch_count + 1):
            mask = numbered_patches == patch_number
            if mask.sum() < minimum_area:
                dropped_speck_count += 1
                continue
            grown_mask = ndimage.binary_dilation(mask, structure=search_square)
            outline = mask & ~ndimage.binary_erosion(mask)
            regions.append(Region(color_index, mask, grown_mask, outline))
    return regions, dropped_speck_count


def rectangle_mask(primitive, canvas_shape):
    """Returns the pixels covered by an upright rectangle."""
    rows, columns = numpy.indices(canvas_shape)
    return (
        (numpy.abs(columns + 0.5 - primitive.center_x) <= primitive.half_width)
        & (numpy.abs(rows + 0.5 - primitive.center_y) <= primitive.half_height))


def ellipse_mask(primitive, canvas_shape):
    """Returns the pixels covered by a rotated ellipse."""
    rows, columns = numpy.indices(canvas_shape)
    offset_x = columns + 0.5 - primitive.center_x
    offset_y = rows + 0.5 - primitive.center_y
    angle = math.radians(primitive.rotation_degrees)
    # Turn each pixel into the ellipse's own tilted frame, where the
    # ellipse is upright and the usual inside-test applies.
    along_width = offset_x * math.cos(angle) + offset_y * math.sin(angle)
    along_height = -offset_x * math.sin(angle) + offset_y * math.cos(angle)
    return ((along_width / primitive.half_width)**2 +
            (along_height / primitive.half_height)**2) <= 1


def primitive_mask(primitive, canvas_shape):
    """Returns the pixels covered by a rectangle, circle, or ellipse."""
    if primitive.kind in ('circle', 'ellipse'):
        return ellipse_mask(primitive, canvas_shape)
    return rectangle_mask(primitive, canvas_shape)


def bounding_rectangle(mask):
    """Returns the smallest upright rectangle containing the mask."""
    rows, columns = numpy.nonzero(mask)
    left, right = columns.min(), columns.max() + 1
    top, bottom = rows.min(), rows.max() + 1
    return Primitive(kind='rectangle',
                     center_x=(left + right) / 2,
                     center_y=(top + bottom) / 2,
                     half_width=(right - left) / 2,
                     half_height=(bottom - top) / 2,
                     rotation_degrees=0.0,
                     fit_error_percent=0.0)


def fit_ellipse_to_points(points_x, points_y):
    """Fits a rotated ellipse through outline points, or returns None.

    Every ellipse satisfies an equation of the form
        a*x*x + b*x*y + c*y*y + d*x + e*y = 1
    once x and y are measured from a point inside it. Least squares finds
    the five numbers that best satisfy that equation at every outline
    point; the center, radii, and tilt are then read off those numbers.
    """
    if len(points_x) < MINIMUM_OUTLINE_POINTS:
        return None
    origin_x, origin_y = points_x.mean(), points_y.mean()
    scale = max(points_x.std(), points_y.std(), 1.0)
    scaled_x = (points_x - origin_x) / scale
    scaled_y = (points_y - origin_y) / scale
    equation_terms = numpy.column_stack(
        [scaled_x**2, scaled_x * scaled_y, scaled_y**2, scaled_x, scaled_y])
    coefficients = numpy.linalg.lstsq(equation_terms,
                                      numpy.ones(len(scaled_x)),
                                      rcond=None)[0]
    squared_x, cross, squared_y, linear_x, linear_y = coefficients
    quadratic_part = numpy.array([[squared_x, cross / 2],
                                  [cross / 2, squared_y]])
    if abs(numpy.linalg.det(quadratic_part)) < 1e-12:
        return None
    center = numpy.linalg.solve(2 * quadratic_part, [-linear_x, -linear_y])
    level = 1 + center @ quadratic_part @ center
    axis_strengths, axis_directions = numpy.linalg.eigh(quadratic_part)
    # Both strengths must have the same sign as the level, otherwise the
    # curve is a hyperbola or parabola and not an ellipse.
    if level <= 0 or (axis_strengths <= 0).any():
        return None
    radii = numpy.sqrt(level / axis_strengths) * scale

    # Call the axis that lies closer to horizontal the "width" axis, and
    # report how far it is tilted. Positive means clockwise on screen,
    # which is also the direction CSS and SVG rotate.
    first_direction = axis_directions[:, 0]
    width_axis = 0 if abs(first_direction[0]) >= abs(first_direction[1]) else 1
    width_direction = axis_directions[:, width_axis]
    if width_direction[0] < 0:
        width_direction = -width_direction
    rotation_degrees = math.degrees(
        math.atan2(width_direction[1], width_direction[0]))
    return Primitive(kind='ellipse',
                     center_x=origin_x + center[0] * scale,
                     center_y=origin_y + center[1] * scale,
                     half_width=float(radii[width_axis]),
                     half_height=float(radii[1 - width_axis]),
                     rotation_degrees=rotation_degrees,
                     fit_error_percent=0.0)


def own_outline_points(region, other_regions_grown, other_regions_outline,
                       front_regions_grown):
    """Returns the outline points that belong to the region itself.

    An outline point counts only when another shape still in the picture is
    just across the edge. Points beside a shape that sits in front are
    skipped, because there the edge belongs to the shape in front.

    The true edge runs down the middle of a thin band of blended pixels.
    Using the ring of pixels on both sides of that band (the region's own
    and its neighbor's) centers the fit on the true edge. Using only the
    region's own ring would make every shape slightly too small.
    """
    own_side = region.outline & other_regions_grown
    facing_side = other_regions_outline & region.grown_mask
    usable = (own_side | facing_side) & ~front_regions_grown
    margin = CANVAS_EDGE_MARGIN_PIXELS
    usable[:margin, :] = False
    usable[-margin:, :] = False
    usable[:, :margin] = False
    usable[:, -margin:] = False
    rows, columns = numpy.nonzero(usable)
    return columns + 0.5, rows + 0.5


def fit_error_percent(primitive, region, other_regions_mask):
    """Scores a fit: 0 is perfect, larger is worse.

    Counts the region's pixels the primitive fails to cover, plus the
    primitive's pixels that land on another shape still in the picture,
    as a percentage of the region's area. Pixels of shapes already peeled
    off the front are not counted, since the primitive may pass under them.
    """
    covered = primitive_mask(primitive, region.mask.shape)
    missed_pixels = (region.mask & ~covered).sum()
    spilled_pixels = (covered & other_regions_mask).sum()
    return 100 * (missed_pixels + spilled_pixels) / region.mask.sum()


def fit_best_primitive(region, other_regions, front_regions):
    """Fits a rectangle and an ellipse and returns whichever fits better."""
    canvas_shape = region.mask.shape
    other_regions_mask = numpy.zeros(canvas_shape, dtype=bool)
    other_regions_grown = numpy.zeros(canvas_shape, dtype=bool)
    other_regions_outline = numpy.zeros(canvas_shape, dtype=bool)
    for other_region in other_regions:
        other_regions_mask |= other_region.mask
        other_regions_grown |= other_region.grown_mask
        other_regions_outline |= other_region.outline
    front_regions_grown = numpy.zeros(canvas_shape, dtype=bool)
    for front_region in front_regions:
        front_regions_grown |= front_region.grown_mask

    candidates = [bounding_rectangle(region.mask)]
    ellipse = fit_ellipse_to_points(
        *own_outline_points(region, other_regions_grown, other_regions_outline,
                            front_regions_grown))
    if ellipse is not None:
        candidates.append(ellipse)
    for candidate in candidates:
        candidate.fit_error_percent = fit_error_percent(candidate, region,
                                                        other_regions_mask)
    return min(candidates, key=lambda candidate: candidate.fit_error_percent)


def find_layer_order(regions):
    """Returns region numbers back to front, and each region's primitive.

    Repeatedly removes the front-most remaining shape: the one whose
    visible area is best explained by a complete rectangle or ellipse.
    """
    remaining = set(range(len(regions)))
    front = []
    cached_fits = {}
    while remaining:
        for region_number in remaining:
            if region_number not in cached_fits:
                cached_fits[region_number] = fit_best_primitive(
                    regions[region_number], [
                        regions[other_number]
                        for other_number in remaining
                        if other_number != region_number
                    ], [regions[front_number] for front_number in front])
        front_most = min(
            remaining, key=lambda number: cached_fits[number].fit_error_percent)
        remaining.remove(front_most)
        front.append(front_most)
        # Removing a shape exposes more of whatever touched it, so those
        # neighbors must be fitted again.
        for region_number in remaining:
            touches_removed = (regions[region_number].grown_mask &
                               regions[front_most].mask).any()
            if touches_removed:
                del cached_fits[region_number]
    back_to_front = front[::-1]
    return back_to_front, cached_fits


def redraw(regions, back_to_front, primitives, palette):
    """Paints the fitted shapes in layer order and returns the pixels."""
    canvas_shape = regions[0].mask.shape
    canvas = numpy.full(canvas_shape + (3,), 255.0)
    for region_number in back_to_front:
        region = regions[region_number]
        primitive = primitives[region_number]
        if primitive.kind == 'irregular':
            covered = region.mask
        else:
            covered = primitive_mask(primitive, canvas_shape)
        canvas[covered] = palette[region.color_index]
    return canvas


def describe_color(color):
    """Returns a plain name such as 'blue' or 'pink' for an RGB color."""
    red, green, blue = (channel / 255 for channel in color)
    hue, saturation, brightness = colorsys.rgb_to_hsv(red, green, blue)
    if saturation < 0.12:
        if brightness > 0.9:
            return 'white'
        if brightness < 0.2:
            return 'black'
        return 'gray'
    hue_degrees = hue * 360
    hue_name = next(name for limit, name in HUE_NAMES if hue_degrees <= limit)
    # A pale red or orange reads as pink.
    is_pale = saturation < 0.45 and brightness > 0.8
    if hue_name in ('red', 'orange') and is_pale:
        return 'pink'
    return hue_name


def make_unique_names(base_names):
    """Appends '-two', '-three', ... to repeated names, in order."""
    seen_counts = {}
    unique_names = []
    for base_name in base_names:
        seen_counts[base_name] = seen_counts.get(base_name, 0) + 1
        occurrence = seen_counts[base_name]
        if occurrence == 1:
            unique_names.append(base_name)
        elif occurrence < len(NUMBER_WORDS):
            unique_names.append(f'{base_name}-{NUMBER_WORDS[occurrence]}')
        else:
            unique_names.append(f'{base_name}-{occurrence}')
    return unique_names


def color_to_hex(color):
    """Returns a color as a lowercase hex string such as '#74c6f3'."""
    return '#' + ''.join(f'{round(channel):02x}' for channel in color)


def fill_canvas_if_background(primitive, canvas_shape):
    """Stretches the back-most rectangle to fill the canvas when it spans it.

    The back-most shape is usually a backdrop that other shapes cover along
    one edge, so its visible area stops short of that edge. If it already
    spans the full width or the full height, treat it as filling the canvas.
    """
    canvas_height, canvas_width = canvas_shape
    spans_width = 2 * primitive.half_width >= canvas_width - 1
    spans_height = 2 * primitive.half_height >= canvas_height - 1
    if primitive.kind != 'rectangle' or not (spans_width or spans_height):
        return primitive
    return dataclasses.replace(primitive,
                               center_x=canvas_width / 2,
                               center_y=canvas_height / 2,
                               half_width=canvas_width / 2,
                               half_height=canvas_height / 2)


def finish_primitive(primitive):
    """Applies the naming rules for circles and for poor fits."""
    if primitive.fit_error_percent > MAXIMUM_FIT_ERROR_PERCENT:
        return dataclasses.replace(primitive, kind='irregular')
    if primitive.kind != 'ellipse':
        return primitive
    larger_radius = max(primitive.half_width, primitive.half_height)
    smaller_radius = min(primitive.half_width, primitive.half_height)
    difference_percent = 100 * (larger_radius - smaller_radius) / larger_radius
    if difference_percent > CIRCLE_RADIUS_DIFFERENCE_PERCENT:
        return primitive
    mean_radius = (larger_radius + smaller_radius) / 2
    return dataclasses.replace(primitive,
                               kind='circle',
                               half_width=mean_radius,
                               half_height=mean_radius,
                               rotation_degrees=0.0)


def describe_shape(name, color_name, primitive, region, percent_per_pixel):
    """Builds one entry of the "shapes" list, in percent-of-width units."""

    def to_percent(pixels):
        return round(float(pixels) * percent_per_pixel, 1)

    shape = {
        'name': name,
        'primitive': primitive.kind,
        'color': color_name,
        'visible_percent': round(100 * float(region.mask.mean()), 1),
    }
    if primitive.kind in ('circle', 'ellipse'):
        shape.update({
            'center_x': to_percent(primitive.center_x),
            'center_y': to_percent(primitive.center_y),
            'radius_x': to_percent(primitive.half_width),
            'radius_y': to_percent(primitive.half_height),
            'rotation_degrees': round(primitive.rotation_degrees, 1),
        })
    else:
        if primitive.kind == 'irregular':
            primitive = bounding_rectangle(region.mask)
        shape.update({
            'left': to_percent(primitive.center_x - primitive.half_width),
            'top': to_percent(primitive.center_y - primitive.half_height),
            'width': to_percent(2 * primitive.half_width),
            'height': to_percent(2 * primitive.half_height),
        })
    return shape


def decompose(image_path, maximum_colors=None, minimum_shape_percent=None):
    """Measures the image and returns (breakdown, preview_image)."""
    if minimum_shape_percent is None:
        minimum_shape_percent = DEFAULT_MINIMUM_SHAPE_PERCENT
    image_path = pathlib.Path(image_path)
    pixels, original_size = load_working_pixels(image_path)
    working_height, working_width = pixels.shape[:2]
    palette = find_palette(pixels, maximum_colors)
    labels = label_pixels(pixels, palette)
    regions, dropped_speck_count = find_regions(labels, len(palette),
                                                minimum_shape_percent)
    back_to_front, raw_primitives = find_layer_order(regions)
    primitives = {
        number: finish_primitive(primitive)
        for number, primitive in raw_primitives.items()
    }
    back_most = back_to_front[0]
    primitives[back_most] = fill_canvas_if_background(primitives[back_most],
                                                      pixels.shape[:2])

    redrawn_pixels = redraw(regions, back_to_front, primitives, palette)
    matches = (numpy.sqrt(((pixels - redrawn_pixels)**2).sum(axis=-1))
               <= REDRAW_MATCH_TOLERANCE)

    color_names = make_unique_names(
        [describe_color(color) for color in palette])
    canvas_area = working_width * working_height
    base_shape_names = []
    for region_number in back_to_front:
        primitive = primitives[region_number]
        covered_percent = (100 * 4 * primitive.half_width *
                           primitive.half_height / canvas_area)
        is_background = (primitive.kind == 'rectangle' and
                         covered_percent >= BACKGROUND_COVERAGE_PERCENT)
        if is_background:
            base_shape_names.append('background')
        else:
            color_name = color_names[regions[region_number].color_index]
            base_shape_names.append(f'{color_name}-{primitive.kind}')
    shape_names = make_unique_names(base_shape_names)

    percent_per_pixel = 100 / working_width
    shapes = [
        describe_shape(shape_name,
                       color_names[regions[region_number].color_index],
                       primitives[region_number], regions[region_number],
                       percent_per_pixel)
        for shape_name, region_number in zip(shape_names, back_to_front)
    ]

    simplifications = [
        'Each region is flattened to one color: the median of its pixels.',
        'Shapes partly hidden behind others are completed from the part of '
        'their outline that is visible.',
    ]
    if dropped_speck_count:
        simplifications.append(
            f'{dropped_speck_count} stray patch(es) smaller than '
            f'{minimum_shape_percent}% of the image were dropped.')
    irregular_names = [
        shape['name'] for shape in shapes if shape['primitive'] == 'irregular'
    ]
    if irregular_names:
        simplifications.append(
            'These shapes are not a rectangle, circle, or ellipse and are '
            'reported by bounding box only: ' + ', '.join(irregular_names) +
            '.')

    breakdown = {
        'schema_version': SCHEMA_VERSION,
        'source': image_path.name,
        'canvas': {
            'width_pixels':
                original_size[0],
            'height_pixels':
                original_size[1],
            'height_as_percent_of_width':
                round(100 * original_size[1] / original_size[0], 1),
            'units':
                'Every position and size is a percentage of the canvas '
                'width, measured from the top-left corner.',
        },
        'palette': [{
            'name':
                color_name,
            'hex':
                color_to_hex(color),
            'visible_percent':
                round(100 * float((labels == color_index).mean()), 1),
        } for color_index, (color_name,
                            color) in enumerate(zip(color_names, palette))],
        'layers_back_to_front': shape_names,
        'shapes': shapes,
        'groups': [],
        'simplifications': simplifications,
        'redraw_match_percent': round(100 * float(matches.mean()), 2),
    }

    side_by_side = numpy.concatenate([pixels, redrawn_pixels], axis=1)
    preview_image = Image.fromarray(side_by_side.astype(numpy.uint8))
    return breakdown, preview_image


def geometry_as_sentence(shape):
    """Returns a shape's position and size as a short phrase."""
    if 'center_x' in shape:
        center_x, center_y = shape['center_x'], shape['center_y']
        radius_x, radius_y = shape['radius_x'], shape['radius_y']
        rotation_degrees = shape['rotation_degrees']
        return (f'center {center_x}, {center_y}; '
                f'radii {radius_x}, {radius_y}; '
                f'rotated {rotation_degrees} degrees clockwise')
    left, top = shape['left'], shape['top']
    width, height = shape['width'], shape['height']
    return f'left {left}, top {top}, width {width}, height {height}'


def breakdown_as_markdown(breakdown):
    """Returns the breakdown written out for a human reader."""
    source = breakdown['source']
    canvas = breakdown['canvas']
    width_pixels, height_pixels = canvas['width_pixels'], canvas[
        'height_pixels']
    units = canvas['units']
    lines = [
        f'# Breakdown of {source}',
        '',
        f'Canvas: {width_pixels} x {height_pixels} pixels. {units}',
        '',
        '## Palette',
        '',
        '| Name | Hex | Visible area |',
        '|---|---|---|',
    ]
    for color in breakdown['palette']:
        name, hex_code = color['name'], color['hex']
        visible_percent = color['visible_percent']
        lines.append(f'| {name} | `{hex_code}` | {visible_percent}% |')
    lines += [
        '',
        '## Shapes, back to front',
        '',
        '| Shape | Primitive | Color | Position and size |',
        '|---|---|---|---|',
    ]
    for shape in breakdown['shapes']:
        name, primitive = shape['name'], shape['primitive']
        color_name = shape['color']
        geometry = geometry_as_sentence(shape)
        lines.append(f'| {name} | {primitive} | {color_name} | {geometry} |')
    lines += ['', '## Simplifications', '']
    lines += [f'- {note}' for note in breakdown['simplifications']]
    redraw_match_percent = breakdown['redraw_match_percent']
    lines += [
        '',
        '## Accuracy',
        '',
        'Redrawing the image from these shapes matches '
        f'{redraw_match_percent}% of the pixels in the original. '
        'See `breakdown-preview.png` (original on the left, redraw on the '
        'right).',
        '',
    ]
    return '\n'.join(lines)


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
    parser.add_argument('--minimum-shape-percent',
                        type=float,
                        default=DEFAULT_MINIMUM_SHAPE_PERCENT,
                        help='Drop regions smaller than this share of the '
                        'image.')
    options = parser.parse_args(arguments)
    output_folder = options.output_folder or options.image.parent
    output_folder.mkdir(parents=True, exist_ok=True)

    breakdown, preview_image = decompose(options.image, options.maximum_colors,
                                         options.minimum_shape_percent)
    (output_folder /
     'breakdown.json').write_text(json.dumps(breakdown, indent=2) + '\n')
    (output_folder / 'breakdown.md').write_text(
        breakdown_as_markdown(breakdown))
    preview_image.save(output_folder / 'breakdown-preview.png')
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
