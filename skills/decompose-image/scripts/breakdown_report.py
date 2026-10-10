"""Turns fitted shapes into the breakdown that the skill hands back.

Three outputs are built here: the breakdown itself (a plain dictionary
that becomes breakdown.json), a Markdown version for people, and a redraw
of the image made only from the fitted shapes, used to check the work.

Everything in the breakdown is measured as a percentage of the canvas
width. See references/breakdown-format.md for every field.
"""

import colorsys
import dataclasses

import numpy

import primitives

SCHEMA_VERSION = 2

# A fit worse than this is reported as "irregular" instead.
MAXIMUM_FIT_ERROR_PERCENT = 5.0

# An ellipse whose two radii differ by less than this is called a circle.
CIRCLE_RADIUS_DIFFERENCE_PERCENT = 3.0

# A rectangle covering at least this much of the canvas is the background.
BACKGROUND_COVERAGE_PERCENT = 99.0

# When scoring the redraw, a pixel matches if it is within this distance
# of the original. Looser than the labeling tolerance, to allow for the
# original's compression noise on top of the palette's rounding.
REDRAW_MATCH_TOLERANCE = 24

# The redraw is painted this many times larger than the working image and
# then shrunk back. Shrinking blends the colors along each edge, the same
# way the original's soft edges are blended, so that a correctly placed
# edge is not counted as a mismatch merely for being crisp.
REDRAW_SMOOTHING_SCALE = 3

NUMBER_WORDS = [
    'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight',
    'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen',
    'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty', 'twenty-one',
    'twenty-two', 'twenty-three', 'twenty-four', 'twenty-five', 'twenty-six',
    'twenty-seven', 'twenty-eight', 'twenty-nine', 'thirty'
]

# Hue ranges on the color wheel, as (upper limit in degrees, name).
HUE_NAMES = [(20, 'red'), (45, 'orange'), (70, 'yellow'), (160, 'green'),
             (195, 'teal'), (255, 'blue'), (300, 'purple'), (340, 'pink'),
             (360, 'red')]

# Below this saturation a color has no clear hue and is named by lightness.
COLORLESS_SATURATION = 0.2
WHITE_BRIGHTNESS = 0.9
BLACK_BRIGHTNESS = 0.2

# A red or orange this washed-out and this bright reads as pink.
PALE_SATURATION = 0.45
PALE_BRIGHTNESS = 0.8

ROUND_KINDS = ('circle', 'ellipse')
BOX_KINDS = ('rectangle', 'rounded-rectangle', 'irregular')
POINT_KINDS = ('triangle', 'polygon')


def fill_canvas_if_background(primitive, canvas_shape):
    """Stretches the back-most rectangle to fill the canvas when it spans it.

    The back-most shape is usually a backdrop that other shapes cover along
    one edge, so its visible area stops short of that edge. If it already
    spans the full width or the full height, treat it as filling the canvas.
    """
    canvas_height, canvas_width = canvas_shape
    is_upright_rectangle = (primitive.kind == 'rectangle' and
                            primitive.rotation_degrees == 0)
    spans_width = 2 * primitive.half_width >= canvas_width - 1
    spans_height = 2 * primitive.half_height >= canvas_height - 1
    if not is_upright_rectangle or not (spans_width or spans_height):
        return primitive
    return dataclasses.replace(primitive,
                               center_x=canvas_width / 2,
                               center_y=canvas_height / 2,
                               half_width=canvas_width / 2,
                               half_height=canvas_height / 2)


def reported_kind(primitive):
    """Returns the name a primitive is reported under.

    Fitting works with four kinds. Reporting adds three friendlier names:
    a nearly round ellipse is a circle, a three-cornered polygon is a
    triangle, and anything that fits badly is irregular.
    """
    if primitive.fit_error_percent > MAXIMUM_FIT_ERROR_PERCENT:
        return 'irregular'
    if primitive.kind == 'ellipse':
        larger_radius = max(primitive.half_width, primitive.half_height)
        smaller_radius = min(primitive.half_width, primitive.half_height)
        difference_percent = (100 * (larger_radius - smaller_radius) /
                              larger_radius)
        if difference_percent <= CIRCLE_RADIUS_DIFFERENCE_PERCENT:
            return 'circle'
    if primitive.kind == 'polygon' and len(primitive.points) == 3:
        return 'triangle'
    return primitive.kind


def as_circle(primitive):
    """Returns the ellipse with both radii set to their average."""
    mean_radius = (primitive.half_width + primitive.half_height) / 2
    return dataclasses.replace(primitive,
                               half_width=mean_radius,
                               half_height=mean_radius,
                               rotation_degrees=0.0)


def enlarged(primitive, scale):
    """Returns the primitive as it would be on a canvas `scale` times larger."""
    points = primitive.points
    if points is not None:
        points = [
            (point_x * scale, point_y * scale) for point_x, point_y in points
        ]
    return dataclasses.replace(primitive,
                               center_x=primitive.center_x * scale,
                               center_y=primitive.center_y * scale,
                               half_width=primitive.half_width * scale,
                               half_height=primitive.half_height * scale,
                               corner_radius=primitive.corner_radius * scale,
                               points=points)


def redraw(region_map, back_to_front, fitted, palette):
    """Paints the fitted shapes in layer order and returns the pixels.

    Painting is done on an enlarged canvas which is then shrunk back by
    averaging, to give the redraw soft edges like the original's.
    """
    scale = REDRAW_SMOOTHING_SCALE
    region_of_pixel = region_map.region_of_pixel
    canvas_height, canvas_width = region_of_pixel.shape
    large_shape = (canvas_height * scale, canvas_width * scale)
    large_canvas = numpy.full(large_shape + (3,), 255.0)
    for region_number in back_to_front:
        primitive, kind = fitted[region_number]
        color = palette[region_map.regions[region_number].color_index]
        if kind == 'irregular':
            # No primitive to paint, so paint the region's own pixels, each
            # one enlarged into a scale-by-scale block.
            own_pixels = region_of_pixel == region_number
            covered = numpy.repeat(numpy.repeat(own_pixels, scale, axis=0),
                                   scale,
                                   axis=1)
            large_canvas[covered] = color
            continue
        large_primitive = enlarged(primitive, scale)
        window = primitives.primitive_window(large_primitive, large_shape)
        covered = primitives.primitive_mask(large_primitive, window)
        large_canvas[window.slices()][covered] = color
    blocks = large_canvas.reshape(canvas_height, scale, canvas_width, scale, 3)
    return blocks.mean(axis=(1, 3))


def describe_color(color):
    """Returns a plain name such as 'blue' or 'pink' for an RGB color."""
    red, green, blue = (channel / 255 for channel in color)
    hue, saturation, brightness = colorsys.rgb_to_hsv(red, green, blue)
    if saturation < COLORLESS_SATURATION:
        if brightness > WHITE_BRIGHTNESS:
            return 'white'
        if brightness < BLACK_BRIGHTNESS:
            return 'black'
        return 'gray'
    hue_degrees = hue * 360
    hue_name = next(name for limit, name in HUE_NAMES if hue_degrees <= limit)
    is_pale = saturation < PALE_SATURATION and brightness > PALE_BRIGHTNESS
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


def describe_shape(name, color_name, primitive, kind, region, canvas_shape):
    """Builds one entry of the "shapes" list, in percent-of-width units."""
    canvas_height, canvas_width = canvas_shape

    def to_percent(pixels):
        return round(float(pixels) * 100 / canvas_width, 1)

    shape = {
        'name':
            name,
        'primitive':
            kind,
        'color':
            color_name,
        'visible_percent':
            round(100 * region.area_pixels / (canvas_width * canvas_height), 1),
    }
    if kind in ROUND_KINDS:
        shape.update({
            'center_x': to_percent(primitive.center_x),
            'center_y': to_percent(primitive.center_y),
            'radius_x': to_percent(primitive.half_width),
            'radius_y': to_percent(primitive.half_height),
            'rotation_degrees': round(primitive.rotation_degrees, 1),
        })
    elif kind in POINT_KINDS:
        shape['points'] = [{
            'x': to_percent(point_x),
            'y': to_percent(point_y)
        } for point_x, point_y in primitive.points]
    else:
        if kind == 'irregular':
            primitive = primitives.fit_upright_rectangle(region)
        shape.update({
            'left': to_percent(primitive.center_x - primitive.half_width),
            'top': to_percent(primitive.center_y - primitive.half_height),
            'width': to_percent(2 * primitive.half_width),
            'height': to_percent(2 * primitive.half_height),
            'rotation_degrees': round(primitive.rotation_degrees, 1),
        })
        if kind == 'rounded-rectangle':
            shape['corner_radius'] = to_percent(primitive.corner_radius)
    return shape


def name_shapes(region_map, back_to_front, fitted, color_names):
    """Returns a unique name for every shape, back to front."""
    canvas_height, canvas_width = region_map.region_of_pixel.shape
    base_names = []
    for region_number in back_to_front:
        primitive, kind = fitted[region_number]
        covered_percent = (100 * 4 * primitive.half_width *
                           primitive.half_height /
                           (canvas_width * canvas_height))
        if (kind == 'rectangle' and
                covered_percent >= BACKGROUND_COVERAGE_PERCENT):
            base_names.append('background')
        else:
            color_name = color_names[
                region_map.regions[region_number].color_index]
            base_names.append(f'{color_name}-{kind}')
    return make_unique_names(base_names)


def redraw_match_percent(pixels, redrawn_pixels, is_flat_color):
    """Returns the share of flat-colored pixels the redraw gets right.

    Only pixels that clearly show one palette color are scored. The thin
    bands of blended pixels along edges are left out, because a blend has
    no single right answer: how soft an edge looks depends on how the
    image was made, not on where the shape is. A shape in the wrong place,
    the wrong size, or the wrong layer still loses points, because it
    paints the wrong color over flat pixels.
    """
    color_distances = numpy.sqrt(((pixels - redrawn_pixels)**2).sum(axis=-1))
    matches = color_distances <= REDRAW_MATCH_TOLERANCE
    return round(100 * float(matches[is_flat_color].mean()), 2)


def build_breakdown(source_name, original_size, pixels, palette, is_flat_color,
                    region_map, back_to_front, fits, minimum_shape_percent):
    """Returns the breakdown dictionary and the redrawn pixels."""
    canvas_shape = region_map.region_of_pixel.shape
    fits = dict(fits)
    back_most = back_to_front[0]
    fits[back_most] = fill_canvas_if_background(fits[back_most], canvas_shape)
    fitted = {}
    for region_number, primitive in fits.items():
        kind = reported_kind(primitive)
        if kind == 'circle':
            primitive = as_circle(primitive)
        fitted[region_number] = (primitive, kind)

    redrawn_pixels = redraw(region_map, back_to_front, fitted, palette)

    color_names = make_unique_names(
        [describe_color(color) for color in palette])
    shape_names = name_shapes(region_map, back_to_front, fitted, color_names)
    shapes = []
    for shape_name, region_number in zip(shape_names, back_to_front):
        primitive, kind = fitted[region_number]
        region = region_map.regions[region_number]
        shapes.append(
            describe_shape(shape_name, color_names[region.color_index],
                           primitive, kind, region, canvas_shape))

    simplifications = [
        'Each region is flattened to one color: the median of its pixels.',
        'Shapes partly hidden behind others are completed from the part of '
        'their outline that is visible.',
    ]
    if region_map.dropped_speck_count:
        simplifications.append(
            f'{region_map.dropped_speck_count} stray patch(es) smaller than '
            f'{minimum_shape_percent}% of the image were dropped.')
    irregular_names = [
        shape['name'] for shape in shapes if shape['primitive'] == 'irregular'
    ]
    if irregular_names:
        simplifications.append(
            'These shapes fit none of the supported primitives and are '
            'reported by bounding box only: ' + ', '.join(irregular_names) +
            '.')

    color_areas = numpy.zeros(len(palette))
    for region in region_map.regions:
        color_areas[region.color_index] += region.area_pixels
    canvas_area = canvas_shape[0] * canvas_shape[1]
    breakdown = {
        'schema_version':
            SCHEMA_VERSION,
        'source':
            source_name,
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
                round(100 * float(color_areas[color_index]) / canvas_area, 1),
        } for color_index, (color_name,
                            color) in enumerate(zip(color_names, palette))],
        'layers_back_to_front':
            shape_names,
        'shapes':
            shapes,
        'groups': [],
        'simplifications':
            simplifications,
        'redraw_match_percent':
            redraw_match_percent(pixels, redrawn_pixels, is_flat_color),
    }
    return breakdown, redrawn_pixels


def geometry_as_sentence(shape):
    """Returns a shape's position and size as a short phrase."""
    if 'points' in shape:
        corner_texts = []
        for point in shape['points']:
            point_x, point_y = point['x'], point['y']
            corner_texts.append(f'({point_x}, {point_y})')
        return 'corners at ' + ', '.join(corner_texts)
    rotation_degrees = shape['rotation_degrees']
    tilt = ''
    if rotation_degrees:
        tilt = f'; rotated {rotation_degrees} degrees clockwise'
    if 'center_x' in shape:
        center_x, center_y = shape['center_x'], shape['center_y']
        radius_x, radius_y = shape['radius_x'], shape['radius_y']
        return (f'center {center_x}, {center_y}; '
                f'radii {radius_x}, {radius_y}{tilt}')
    left, top = shape['left'], shape['top']
    width, height = shape['width'], shape['height']
    rounding = ''
    if 'corner_radius' in shape:
        corner_radius = shape['corner_radius']
        rounding = f'; corner radius {corner_radius}'
    return (f'left {left}, top {top}, width {width}, height {height}'
            f'{rounding}{tilt}')


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
    if breakdown['groups']:
        lines += ['', '## Groups', '']
        for group in breakdown['groups']:
            group_name = group['name']
            members = ', '.join(group['members'])
            lines.append(f'- {group_name}: {members}')
    lines += ['', '## Simplifications', '']
    lines += [f'- {note}' for note in breakdown['simplifications']]
    match_percent = breakdown['redraw_match_percent']
    lines += [
        '',
        '## Accuracy',
        '',
        'Redrawing the image from these shapes gives the right color on '
        f'{match_percent}% of the original\'s flat-colored pixels. The '
        'blended pixels along edges are not scored. '
        'See `breakdown-preview.png` (original on the left, redraw on the '
        'right).',
        '',
    ]
    return '\n'.join(lines)
