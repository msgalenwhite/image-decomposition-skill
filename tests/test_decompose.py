"""Tests for the decompose-image script.

Most tests draw a small picture with known shapes, run the script on it,
and check that the script reports the same shapes back.
"""

import json
import math
import pathlib
import sys
import time

import numpy
from PIL import Image
from PIL import ImageDraw
import pytest

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL_FOLDER = REPOSITORY_ROOT / 'skills' / 'decompose-image'
sys.path.insert(0, str(SKILL_FOLDER / 'scripts'))

import decompose  # pylint: disable=wrong-import-position
import rename_shapes  # pylint: disable=wrong-import-position

EXAMPLE_FOLDER = SKILL_FOLDER / 'examples' / 'sun-and-hills'
BALLOON_EXAMPLE_FOLDER = SKILL_FOLDER / 'examples' / 'balloon-over-hills'

# Test pictures are drawn this many times larger and then shrunk, which
# gives them the same soft, blended edges a real image has.
SMOOTHING_SCALE = 4

# How far a reported position or size may be from the truth, in percent of
# the canvas width.
POSITION_TOLERANCE = 0.6

SKY_BLUE = (116, 198, 243)
SOFT_PINK = (248, 186, 176)
MINT_GREEN = (148, 222, 186)
CHARCOAL = (54, 57, 63)
LAVENDER = (194, 161, 227)
BUTTER_YELLOW = (250, 226, 130)

# The scale test must finish within this many seconds. Generous enough for
# a slow shared test machine, tight enough to catch an accidental slowdown.
SCALE_TEST_TIME_LIMIT_SECONDS = 60


def draw_test_image(folder, canvas_size, background_color, draw_shapes):
    """Draws a picture with soft edges, saves it, and returns its path.

    draw_shapes receives a drawing surface and a function that converts a
    percentage of the canvas width into pixels on that surface.
    """
    canvas_width, canvas_height = canvas_size
    large_size = (canvas_width * SMOOTHING_SCALE,
                  canvas_height * SMOOTHING_SCALE)
    large_image = Image.new('RGB', large_size, background_color)
    large_width = large_size[0]

    def percent_to_pixels(percent):
        return percent * large_width / 100

    draw_shapes(ImageDraw.Draw(large_image), percent_to_pixels)
    image_path = folder / 'test-image.png'
    large_image.resize(canvas_size, Image.Resampling.LANCZOS).save(image_path)
    return image_path


def draw_ellipse(surface, percent_to_pixels, center, radii, color):
    """Draws an upright ellipse given in percent-of-width units."""
    surface.ellipse([
        percent_to_pixels(center[0] - radii[0]),
        percent_to_pixels(center[1] - radii[1]),
        percent_to_pixels(center[0] + radii[0]),
        percent_to_pixels(center[1] + radii[1]),
    ],
                    fill=color)


def draw_rectangle(surface, percent_to_pixels, left_top, size, color):
    """Draws an upright rectangle given in percent-of-width units."""
    surface.rectangle([
        percent_to_pixels(left_top[0]),
        percent_to_pixels(left_top[1]),
        percent_to_pixels(left_top[0] + size[0]),
        percent_to_pixels(left_top[1] + size[1]),
    ],
                      fill=color)


def draw_polygon(surface, percent_to_pixels, corners, color):
    """Draws a straight-sided shape given in percent-of-width units."""
    surface.polygon([(percent_to_pixels(corner_x), percent_to_pixels(corner_y))
                     for corner_x, corner_y in corners],
                    fill=color)


def draw_rounded_rectangle(surface, percent_to_pixels, left_top, size,
                           corner_radius, color):
    """Draws an upright rounded rectangle in percent-of-width units."""
    surface.rounded_rectangle([
        percent_to_pixels(left_top[0]),
        percent_to_pixels(left_top[1]),
        percent_to_pixels(left_top[0] + size[0]),
        percent_to_pixels(left_top[1] + size[1]),
    ],
                              radius=percent_to_pixels(corner_radius),
                              fill=color)


def rotated_about(center, corners, clockwise_degrees):
    """Returns corners turned clockwise on screen about a center."""
    angle = math.radians(clockwise_degrees)
    turned = []
    for corner_x, corner_y in corners:
        offset_x, offset_y = corner_x - center[0], corner_y - center[1]
        turned.append((center[0] + offset_x * math.cos(angle) -
                       offset_y * math.sin(angle), center[1] +
                       offset_x * math.sin(angle) + offset_y * math.cos(angle)))
    return turned


def star_corners(center, outer_radius, inner_radius, point_count):
    """Returns the corners of a star, starting from its top point."""
    corners = []
    for corner_number in range(2 * point_count):
        radius = outer_radius if corner_number % 2 == 0 else inner_radius
        angle = math.pi * corner_number / point_count - math.pi / 2
        corners.append((center[0] + radius * math.cos(angle),
                        center[1] + radius * math.sin(angle)))
    return corners


def assert_same_corners(reported_points, expected_corners):
    """Checks reported corners match expected ones, in any starting order."""
    assert len(reported_points) == len(expected_corners)
    for expected_x, expected_y in expected_corners:
        nearest_distance = min(
            math.hypot(point['x'] - expected_x, point['y'] - expected_y)
            for point in reported_points)
        assert nearest_distance <= POSITION_TOLERANCE, (
            f'no reported corner near ({expected_x}, {expected_y}): '
            f'{reported_points}')


def measure(image_path):
    """Runs the script on an image and returns only the breakdown."""
    breakdown, unused_preview_image = decompose.decompose(image_path)
    return breakdown


def shape_named(breakdown, name):
    """Returns the shape with the given name from a breakdown."""
    return next(shape for shape in breakdown['shapes'] if shape['name'] == name)


def test_single_circle_on_plain_background(tmp_path):
    """A lone circle comes back with the right center, radius, and color."""

    def draw_shapes(surface, percent_to_pixels):
        draw_ellipse(surface, percent_to_pixels, (40, 55), (20, 20), SOFT_PINK)

    image_path = draw_test_image(tmp_path, (600, 600), SKY_BLUE, draw_shapes)
    breakdown = measure(image_path)

    assert breakdown['layers_back_to_front'] == ['background', 'pink-circle']
    assert [color['hex'] for color in breakdown['palette']
           ] == ['#74c6f3', '#f8bab0']
    circle = shape_named(breakdown, 'pink-circle')
    assert circle['center_x'] == pytest.approx(40, abs=POSITION_TOLERANCE)
    assert circle['center_y'] == pytest.approx(55, abs=POSITION_TOLERANCE)
    assert circle['radius_x'] == pytest.approx(20, abs=POSITION_TOLERANCE)
    assert breakdown['redraw_match_percent'] > 99


def test_circle_half_hidden_behind_rectangle(tmp_path):
    """A hidden half is rebuilt, and the rectangle is placed in front."""

    def draw_shapes(surface, percent_to_pixels):
        draw_ellipse(surface, percent_to_pixels, (50, 50), (25, 25), SOFT_PINK)
        draw_rectangle(surface, percent_to_pixels, (10, 50), (80, 35),
                       MINT_GREEN)

    image_path = draw_test_image(tmp_path, (600, 600), SKY_BLUE, draw_shapes)
    breakdown = measure(image_path)

    assert breakdown['layers_back_to_front'] == [
        'background', 'pink-circle', 'green-rectangle'
    ]
    circle = shape_named(breakdown, 'pink-circle')
    assert circle['center_x'] == pytest.approx(50, abs=POSITION_TOLERANCE)
    assert circle['center_y'] == pytest.approx(50, abs=POSITION_TOLERANCE)
    assert circle['radius_x'] == pytest.approx(25, abs=POSITION_TOLERANCE)
    rectangle = shape_named(breakdown, 'green-rectangle')
    assert rectangle['left'] == pytest.approx(10, abs=POSITION_TOLERANCE)
    assert rectangle['top'] == pytest.approx(50, abs=POSITION_TOLERANCE)
    assert rectangle['width'] == pytest.approx(80, abs=POSITION_TOLERANCE)
    assert rectangle['height'] == pytest.approx(35, abs=POSITION_TOLERANCE)


def test_two_shapes_of_one_color_get_separate_names(tmp_path):
    """Same-colored shapes that do not touch are reported one by one."""

    def draw_shapes(surface, percent_to_pixels):
        draw_ellipse(surface, percent_to_pixels, (25, 30), (12, 12), SOFT_PINK)
        draw_ellipse(surface, percent_to_pixels, (70, 65), (15, 15), SOFT_PINK)

    image_path = draw_test_image(tmp_path, (600, 600), CHARCOAL, draw_shapes)
    breakdown = measure(image_path)

    assert len(breakdown['palette']) == 2
    assert sorted(breakdown['layers_back_to_front']) == [
        'background', 'pink-circle', 'pink-circle-two'
    ]


def test_tiny_speck_is_dropped_and_reported(tmp_path):
    """A stray dot is left out of the shapes and noted as a simplification."""

    def draw_shapes(surface, percent_to_pixels):
        draw_ellipse(surface, percent_to_pixels, (50, 50), (20, 20), SOFT_PINK)
        draw_ellipse(surface, percent_to_pixels, (90, 10), (1.2, 1.2),
                     SOFT_PINK)

    image_path = draw_test_image(tmp_path, (600, 600), SKY_BLUE, draw_shapes)
    breakdown = measure(image_path)

    assert breakdown['layers_back_to_front'] == ['background', 'pink-circle']
    assert any('dropped' in note for note in breakdown['simplifications'])


def test_wide_canvas_measures_everything_against_its_width(tmp_path):
    """On a canvas twice as wide as tall, a circle is still a circle."""

    def draw_shapes(surface, percent_to_pixels):
        draw_ellipse(surface, percent_to_pixels, (30, 25), (15, 15), MINT_GREEN)

    image_path = draw_test_image(tmp_path, (800, 400), CHARCOAL, draw_shapes)
    breakdown = measure(image_path)

    assert breakdown['canvas']['height_as_percent_of_width'] == 50
    circle = shape_named(breakdown, 'green-circle')
    assert circle['primitive'] == 'circle'
    assert circle['center_y'] == pytest.approx(25, abs=POSITION_TOLERANCE)
    assert circle['radius_y'] == pytest.approx(15, abs=POSITION_TOLERANCE)


def test_tilted_ellipse_reports_its_rotation(tmp_path):
    """An ellipse leaning clockwise reports a positive rotation."""
    tilt_degrees = 20

    def draw_shapes(surface, percent_to_pixels):
        del surface, percent_to_pixels  # The ellipse is pasted in below.

    image_path = draw_test_image(tmp_path, (600, 600), SKY_BLUE, draw_shapes)
    ellipse_layer = Image.new('RGBA', (2400, 2400), (0, 0, 0, 0))
    ImageDraw.Draw(ellipse_layer).ellipse([480, 840, 1920, 1560],
                                          fill=SOFT_PINK + (255,))
    # Pillow turns counter-clockwise for positive angles, so negate.
    ellipse_layer = ellipse_layer.rotate(-tilt_degrees,
                                         resample=Image.Resampling.BICUBIC)
    backdrop = Image.new('RGBA', (2400, 2400), SKY_BLUE + (255,))
    Image.alpha_composite(backdrop, ellipse_layer).convert('RGB').resize(
        (600, 600), Image.Resampling.LANCZOS).save(image_path)
    breakdown = measure(image_path)

    ellipse = shape_named(breakdown, 'pink-ellipse')
    assert ellipse['radius_x'] == pytest.approx(30, abs=POSITION_TOLERANCE)
    assert ellipse['radius_y'] == pytest.approx(15, abs=POSITION_TOLERANCE)
    assert ellipse['rotation_degrees'] == pytest.approx(tilt_degrees, abs=1)


def test_sun_and_hills_example_matches_the_committed_breakdown():
    """The worked example in the repo is exactly what the script produces."""
    breakdown = measure(EXAMPLE_FOLDER / 'original.webp')
    committed = json.loads((EXAMPLE_FOLDER / 'breakdown.json').read_text())

    assert breakdown == committed
    assert breakdown['layers_back_to_front'] == [
        'background', 'pink-circle', 'green-ellipse', 'purple-ellipse'
    ]
    assert breakdown['redraw_match_percent'] > 99


def test_balloon_example_matches_the_committed_breakdown():
    """The second worked example is exactly what the script produces.

    It holds every kind of shape at once: ellipses, a rounded rectangle, a
    triangle, a star, and a four-cornered shape partly behind an ellipse.
    """
    breakdown = measure(BALLOON_EXAMPLE_FOLDER / 'original.png')
    committed = json.loads(
        (BALLOON_EXAMPLE_FOLDER / 'breakdown.json').read_text())

    assert breakdown == committed
    kinds = sorted(shape['primitive'] for shape in breakdown['shapes'])
    assert kinds == [
        'ellipse', 'ellipse', 'ellipse', 'ellipse', 'ellipse', 'polygon',
        'polygon', 'rectangle', 'rounded-rectangle', 'triangle'
    ]


def test_command_line_writes_all_three_files(tmp_path):
    """Running the script as a command produces the documented files."""
    exit_code = decompose.main([
        str(EXAMPLE_FOLDER / 'original.webp'), '--output-folder',
        str(tmp_path)
    ])

    assert exit_code == 0
    for file_name in ('breakdown.json', 'breakdown.md',
                      'breakdown-preview.png'):
        assert (tmp_path / file_name).exists()


def test_triangle_reports_its_three_corners(tmp_path):
    """A triangle comes back with the three corners it was drawn with."""
    corners = [(50, 15), (85, 80), (20, 70)]

    def draw_shapes(surface, percent_to_pixels):
        draw_polygon(surface, percent_to_pixels, corners, MINT_GREEN)

    image_path = draw_test_image(tmp_path, (600, 600), CHARCOAL, draw_shapes)
    breakdown = measure(image_path)

    triangle = shape_named(breakdown, 'green-triangle')
    assert_same_corners(triangle['points'], corners)
    assert breakdown['redraw_match_percent'] > 99


def test_tilted_rectangle_reports_its_size_and_rotation(tmp_path):
    """A tilted rectangle is a rectangle with a rotation, not a polygon."""
    upright_corners = [(30, 40), (70, 40), (70, 60), (30, 60)]
    tilt_degrees = 25

    def draw_shapes(surface, percent_to_pixels):
        draw_polygon(surface, percent_to_pixels,
                     rotated_about((50, 50), upright_corners, tilt_degrees),
                     SOFT_PINK)

    image_path = draw_test_image(tmp_path, (600, 600), SKY_BLUE, draw_shapes)
    breakdown = measure(image_path)

    rectangle = shape_named(breakdown, 'pink-rectangle')
    assert rectangle['width'] == pytest.approx(40, abs=POSITION_TOLERANCE)
    assert rectangle['height'] == pytest.approx(20, abs=POSITION_TOLERANCE)
    assert rectangle['left'] == pytest.approx(30, abs=POSITION_TOLERANCE)
    assert rectangle['top'] == pytest.approx(40, abs=POSITION_TOLERANCE)
    assert rectangle['rotation_degrees'] == pytest.approx(tilt_degrees, abs=1)


def test_upright_rectangle_stays_a_plain_rectangle(tmp_path):
    """Sharp corners are not mistaken for rounded ones."""

    def draw_shapes(surface, percent_to_pixels):
        draw_rectangle(surface, percent_to_pixels, (20, 30), (55, 25), LAVENDER)

    image_path = draw_test_image(tmp_path, (600, 600), CHARCOAL, draw_shapes)
    breakdown = measure(image_path)

    rectangle = shape_named(breakdown, 'purple-rectangle')
    assert rectangle['rotation_degrees'] == 0
    assert 'corner_radius' not in rectangle


def test_rounded_rectangle_reports_its_corner_radius(tmp_path):
    """A rounded rectangle comes back with its box and its corner radius."""

    def draw_shapes(surface, percent_to_pixels):
        draw_rounded_rectangle(surface, percent_to_pixels, (20, 30), (60, 36),
                               8, BUTTER_YELLOW)

    image_path = draw_test_image(tmp_path, (600, 600), CHARCOAL, draw_shapes)
    breakdown = measure(image_path)

    rounded = shape_named(breakdown, 'yellow-rounded-rectangle')
    assert rounded['left'] == pytest.approx(20, abs=POSITION_TOLERANCE)
    assert rounded['top'] == pytest.approx(30, abs=POSITION_TOLERANCE)
    assert rounded['width'] == pytest.approx(60, abs=POSITION_TOLERANCE)
    assert rounded['height'] == pytest.approx(36, abs=POSITION_TOLERANCE)
    assert rounded['corner_radius'] == pytest.approx(8, abs=1)


def test_star_reports_all_ten_corners(tmp_path):
    """A shape with corners pointing inward is traced as a polygon."""
    corners = star_corners((50, 52), 32, 13, point_count=5)

    def draw_shapes(surface, percent_to_pixels):
        draw_polygon(surface, percent_to_pixels, corners, BUTTER_YELLOW)

    image_path = draw_test_image(tmp_path, (600, 600), CHARCOAL, draw_shapes)
    breakdown = measure(image_path)

    star = shape_named(breakdown, 'yellow-polygon')
    assert_same_corners(star['points'], corners)


def test_triangle_corner_hidden_behind_circle_is_rebuilt(tmp_path):
    """A covered corner is found by extending the two sides that lead to it."""
    corners = [(50, 20), (85, 80), (15, 80)]

    def draw_shapes(surface, percent_to_pixels):
        draw_polygon(surface, percent_to_pixels, corners, MINT_GREEN)
        draw_ellipse(surface, percent_to_pixels, (50, 22), (12, 12), SOFT_PINK)

    image_path = draw_test_image(tmp_path, (600, 600), SKY_BLUE, draw_shapes)
    breakdown = measure(image_path)

    assert breakdown['layers_back_to_front'] == [
        'background', 'green-triangle', 'pink-circle'
    ]
    triangle = shape_named(breakdown, 'green-triangle')
    assert_same_corners(triangle['points'], corners)


def test_triangle_running_off_the_canvas_is_cut_at_the_frame(tmp_path):
    """A shape cut by the frame is reported as far as the frame, no further."""

    def draw_shapes(surface, percent_to_pixels):
        draw_polygon(surface, percent_to_pixels, [(50, 40), (90, 140),
                                                  (10, 140)], LAVENDER)

    image_path = draw_test_image(tmp_path, (600, 600), CHARCOAL, draw_shapes)
    breakdown = measure(image_path)

    triangle = shape_named(breakdown, 'purple-triangle')
    assert_same_corners(triangle['points'], [(50, 40), (74, 100), (26, 100)])


def test_small_circle_is_still_a_circle(tmp_path):
    """A small circle traces as only a few edges but must stay a circle."""

    def draw_shapes(surface, percent_to_pixels):
        draw_ellipse(surface, percent_to_pixels, (30, 30), (4, 4), SOFT_PINK)

    image_path = draw_test_image(tmp_path, (600, 600), SKY_BLUE, draw_shapes)
    breakdown = measure(image_path)

    circle = shape_named(breakdown, 'pink-circle')
    assert circle['radius_x'] == pytest.approx(4, abs=POSITION_TOLERANCE)


def test_twenty_five_shapes_are_all_found_in_reasonable_time(tmp_path):
    """A busy picture: every shape is found, named by kind, and found quickly.

    Twenty-four shapes sit on a grid in a repeating pattern of circle,
    rectangle, triangle, and rounded rectangle. The background makes 25.
    """
    kinds_in_order = ['circle', 'rectangle', 'triangle', 'rounded-rectangle']
    colors_in_order = [SOFT_PINK, MINT_GREEN, LAVENDER, BUTTER_YELLOW]
    column_count, row_count = 6, 4
    cell_size = 100 / column_count
    half_shape = cell_size * 0.36

    def draw_shapes(surface, percent_to_pixels):
        for cell_number in range(column_count * row_count):
            center_x = (cell_number % column_count + 0.5) * cell_size
            center_y = (cell_number // column_count + 0.5) * cell_size
            kind = kinds_in_order[cell_number % 4]
            color = colors_in_order[cell_number % 4]
            left_top = (center_x - half_shape, center_y - half_shape)
            size = (2 * half_shape, 2 * half_shape)
            if kind == 'circle':
                draw_ellipse(surface, percent_to_pixels, (center_x, center_y),
                             (half_shape, half_shape), color)
            elif kind == 'rectangle':
                draw_rectangle(surface, percent_to_pixels, left_top, size,
                               color)
            elif kind == 'triangle':
                draw_polygon(surface, percent_to_pixels,
                             [(center_x, center_y - half_shape),
                              (center_x + half_shape, center_y + half_shape),
                              (center_x - half_shape, center_y + half_shape)],
                             color)
            else:
                draw_rounded_rectangle(surface, percent_to_pixels, left_top,
                                       size, half_shape * 0.5, color)

    canvas_height = round(900 * row_count / column_count)
    image_path = draw_test_image(tmp_path, (900, canvas_height), CHARCOAL,
                                 draw_shapes)
    started = time.monotonic()
    breakdown = measure(image_path)
    seconds_taken = time.monotonic() - started

    assert len(breakdown['shapes']) == 25
    for kind in kinds_in_order:
        found = [
            shape for shape in breakdown['shapes']
            if shape['primitive'] == kind and shape['name'] != 'background'
        ]
        assert len(found) == 6, f'expected 6 of {kind}, found {len(found)}'
    assert breakdown['redraw_match_percent'] > 99
    assert seconds_taken < SCALE_TEST_TIME_LIMIT_SECONDS


def test_triangle_in_front_of_triangle_is_ordered_and_completed(tmp_path):
    """The whole triangle is in front; the cut one behind gets its corner back.

    The part of the back triangle left showing is a four-cornered shape,
    so this checks that fewer corners wins when deciding which is whole.
    """
    back_corners = [(35, 15), (65, 75), (5, 75)]
    front_corners = [(65, 30), (95, 85), (35, 85)]

    def draw_shapes(surface, percent_to_pixels):
        draw_polygon(surface, percent_to_pixels, back_corners, MINT_GREEN)
        draw_polygon(surface, percent_to_pixels, front_corners, LAVENDER)

    image_path = draw_test_image(tmp_path, (600, 600), SKY_BLUE, draw_shapes)
    breakdown = measure(image_path)

    assert breakdown['layers_back_to_front'] == [
        'background', 'green-triangle', 'purple-triangle'
    ]
    assert_same_corners(
        shape_named(breakdown, 'green-triangle')['points'], back_corners)
    assert_same_corners(
        shape_named(breakdown, 'purple-triangle')['points'], front_corners)


def test_bite_from_a_shape_in_front_becomes_a_straight_cut(tmp_path):
    """A curved bite is not traced corner by corner into the shape behind.

    The sides of this shape spread apart as they run under the circle, so
    its hidden corners cannot be rebuilt. It is closed off straight across.
    """

    def draw_shapes(surface, percent_to_pixels):
        draw_polygon(surface, percent_to_pixels, [(30, 45), (70, 45), (60, 80),
                                                  (40, 80)], BUTTER_YELLOW)
        draw_ellipse(surface, percent_to_pixels, (50, 35), (26, 26), SOFT_PINK)

    image_path = draw_test_image(tmp_path, (600, 600), SKY_BLUE, draw_shapes)
    breakdown = measure(image_path)

    assert breakdown['layers_back_to_front'] == [
        'background', 'yellow-polygon', 'pink-circle'
    ]
    assert len(shape_named(breakdown, 'yellow-polygon')['points']) == 4


def test_shape_drawn_inside_another_is_in_front_of_it(tmp_path):
    """A circle sitting wholly inside an ellipse leaves the ellipse whole."""

    def draw_shapes(surface, percent_to_pixels):
        draw_ellipse(surface, percent_to_pixels, (50, 50), (35, 22),
                     BUTTER_YELLOW)
        draw_ellipse(surface, percent_to_pixels, (50, 50), (12, 12), LAVENDER)

    image_path = draw_test_image(tmp_path, (600, 600), SKY_BLUE, draw_shapes)
    breakdown = measure(image_path)

    assert breakdown['layers_back_to_front'] == [
        'background', 'yellow-ellipse', 'purple-circle'
    ]
    ellipse = shape_named(breakdown, 'yellow-ellipse')
    assert ellipse['radius_x'] == pytest.approx(35, abs=POSITION_TOLERANCE)
    assert ellipse['radius_y'] == pytest.approx(22, abs=POSITION_TOLERANCE)


def test_image_with_no_flat_color_is_refused(tmp_path):
    """Pure noise has no flat areas, and the tool says so, not guesses."""
    repeatable_randomness = numpy.random.default_rng(seed=1)
    noise = repeatable_randomness.integers(0, 256, size=(200, 200, 3))
    image_path = tmp_path / 'noise.png'
    Image.fromarray(noise.astype(numpy.uint8)).save(image_path)

    with pytest.raises(decompose.UnsuitableImageError):
        decompose.decompose(image_path)


def test_renaming_updates_every_place_a_name_appears():
    """Shape, color, layer, and group names all change together."""
    breakdown = measure(EXAMPLE_FOLDER / 'original.webp')

    renamed = rename_shapes.apply_renames(
        breakdown,
        shape_renames={
            'pink-circle': 'sun',
            'green-ellipse': 'hill-green'
        },
        color_renames={'blue': 'sky'},
        groups={'hills': ['hill-green', 'purple-ellipse']})

    assert renamed['layers_back_to_front'] == [
        'background', 'sun', 'hill-green', 'purple-ellipse'
    ]
    assert shape_named(renamed, 'background')['color'] == 'sky'
    assert renamed['palette'][0]['name'] == 'sky'
    assert renamed['groups'] == [{
        'name': 'hills',
        'members': ['hill-green', 'purple-ellipse']
    }]
    for original_shape, renamed_shape in zip(breakdown['shapes'],
                                             renamed['shapes']):
        assert original_shape['center_x' if 'center_x' in
                              original_shape else 'left'] == renamed_shape[
                                  'center_x' if 'center_x' in
                                  renamed_shape else 'left']


def test_renaming_refuses_unknown_and_clipped_names():
    """A typo or an abbreviation is reported, not silently applied."""
    breakdown = measure(EXAMPLE_FOLDER / 'original.webp')

    with pytest.raises(rename_shapes.RenameError):
        rename_shapes.apply_renames(breakdown, {'pink-square': 'sun'}, {}, {})
    with pytest.raises(rename_shapes.RenameError):
        rename_shapes.apply_renames(breakdown, {'pink-circle': 'shape-7'}, {},
                                    {})
    with pytest.raises(rename_shapes.RenameError):
        rename_shapes.apply_renames(breakdown, {'pink-circle': 'green-ellipse'},
                                    {}, {})


@pytest.mark.parametrize('inner_radius', [11.5, 13, 16.4, 22])
def test_five_point_stars_of_every_proportion_are_traced(
        tmp_path, inner_radius):
    """Thin-armed and fat-armed stars alike come back with ten corners.

    A sharp tip first traces as two corners. This checks the corner limit
    is applied after those are tidied into one, for spiky and stubby stars.
    """
    corners = star_corners((50, 52), 36, inner_radius, point_count=5)

    def draw_shapes(surface, percent_to_pixels):
        draw_polygon(surface, percent_to_pixels, corners, BUTTER_YELLOW)

    image_path = draw_test_image(tmp_path, (600, 600), CHARCOAL, draw_shapes)
    breakdown = measure(image_path)

    assert breakdown['layers_back_to_front'] == ['background', 'yellow-polygon']
    assert_same_corners(
        shape_named(breakdown, 'yellow-polygon')['points'], corners)


def test_six_point_star_uses_all_twelve_allowed_corners(tmp_path):
    """A six-pointed star has exactly the most corners a polygon may have."""
    corners = star_corners((50, 50), 40, 20, point_count=6)

    def draw_shapes(surface, percent_to_pixels):
        draw_polygon(surface, percent_to_pixels, corners, BUTTER_YELLOW)

    image_path = draw_test_image(tmp_path, (600, 600), CHARCOAL, draw_shapes)
    breakdown = measure(image_path)

    assert_same_corners(
        shape_named(breakdown, 'yellow-polygon')['points'], corners)


def test_rectangle_with_a_large_round_bite_is_still_a_rectangle(tmp_path):
    """A big circle over one corner does not stop the rectangle being found.

    The bite's curved edge traces as many corners, which are all hidden and
    collapse into the one rebuilt corner underneath the circle.
    """
    tilt_degrees = 20
    upright_corners = [(17, 30), (83, 30), (83, 70), (17, 70)]
    corners = rotated_about((50, 50), upright_corners, tilt_degrees)

    def draw_shapes(surface, percent_to_pixels):
        draw_polygon(surface, percent_to_pixels, corners, SOFT_PINK)
        draw_ellipse(surface, percent_to_pixels, (33, 33), (17, 17), MINT_GREEN)

    image_path = draw_test_image(tmp_path, (600, 600), SKY_BLUE, draw_shapes)
    breakdown = measure(image_path)

    assert breakdown['layers_back_to_front'] == [
        'background', 'pink-rectangle', 'green-circle'
    ]
    rectangle = shape_named(breakdown, 'pink-rectangle')
    assert rectangle['width'] == pytest.approx(66, abs=POSITION_TOLERANCE)
    assert rectangle['height'] == pytest.approx(40, abs=POSITION_TOLERANCE)
    assert rectangle['rotation_degrees'] == pytest.approx(tilt_degrees, abs=1)


def test_mountain_filling_the_bottom_of_the_canvas_is_a_triangle(tmp_path):
    """A triangle whose base corners sit on the canvas corners has three."""
    corners = [(50, 25), (100, 100), (0, 100)]

    def draw_shapes(surface, percent_to_pixels):
        draw_polygon(surface, percent_to_pixels, corners, CHARCOAL)

    image_path = draw_test_image(tmp_path, (600, 600), SKY_BLUE, draw_shapes)
    breakdown = measure(image_path)

    mountain = shape_named(breakdown, 'gray-triangle')
    assert_same_corners(mountain['points'], corners)


def test_triangle_cut_by_the_side_of_the_canvas_has_four_corners(tmp_path):
    """Where the frame cuts a corner off, exactly one new corner replaces it.

    The triangle's bottom-left corner is off the canvas. The frame cuts it
    where the left side crosses the canvas edge, two thirds of the way down.
    """
    corners_as_drawn = [(100 / 6, 100 / 3), (400 / 6, 100), (-50 / 6, 100)]
    where_the_left_side_meets_the_frame = (0, 100 - 400 / 6 / 3)
    visible_corners = [
        corners_as_drawn[0], corners_as_drawn[1], (0, 100),
        where_the_left_side_meets_the_frame
    ]

    def draw_shapes(surface, percent_to_pixels):
        draw_polygon(surface, percent_to_pixels, corners_as_drawn, CHARCOAL)

    image_path = draw_test_image(tmp_path, (600, 600), SKY_BLUE, draw_shapes)
    breakdown = measure(image_path)

    assert_same_corners(
        shape_named(breakdown, 'gray-polygon')['points'], visible_corners)


def test_score_drops_when_a_color_is_left_out():
    """Leaving shapes out of the breakdown must show up in the score.

    Keeping only two of the example's four colors loses the sun and one
    hill, about a quarter of the picture.
    """
    breakdown, unused_preview_image = decompose.decompose(EXAMPLE_FOLDER /
                                                          'original.webp',
                                                          maximum_colors=2)

    assert len(breakdown['shapes']) == 2
    assert breakdown['redraw_match_percent'] < 80


def test_score_drops_when_thin_lines_are_missed(tmp_path):
    """Lines too thin to be measured still count against the score.

    Eight lines, each a quarter of a percent thick and most of the picture
    wide, cover 1.6 percent of it. None can be reported as a shape, so the
    score must fall by about that much.
    """
    line_thickness = 0.25
    line_tops = [10, 20, 30, 40, 60, 70, 80, 90]

    def draw_shapes(surface, percent_to_pixels):
        for line_top in line_tops:
            draw_rectangle(surface, percent_to_pixels, (10, line_top),
                           (80, line_thickness), CHARCOAL)

    image_path = draw_test_image(tmp_path, (800, 800), SKY_BLUE, draw_shapes)
    breakdown = measure(image_path)

    assert breakdown['layers_back_to_front'] == ['background']
    assert breakdown['redraw_match_percent'] < 99


def test_command_line_reports_a_missing_image_without_a_traceback(
        tmp_path, capsys):
    """A wrong path gives a one-line message and leaves no folder behind."""
    output_folder = tmp_path / 'never-made'
    exit_code = decompose.main([
        str(tmp_path / 'no-such-image.png'), '--output-folder',
        str(output_folder)
    ])

    assert exit_code == 1
    assert 'Could not open' in capsys.readouterr().err
    assert not output_folder.exists()
