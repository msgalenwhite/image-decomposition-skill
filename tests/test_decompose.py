"""Tests for the decompose-image script.

Most tests draw a small picture with known shapes, run the script on it,
and check that the script reports the same shapes back.
"""

import json
import pathlib
import sys

from PIL import Image
from PIL import ImageDraw
import pytest

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL_FOLDER = REPOSITORY_ROOT / 'skills' / 'decompose-image'
sys.path.insert(0, str(SKILL_FOLDER / 'scripts'))

import decompose  # pylint: disable=wrong-import-position

EXAMPLE_FOLDER = SKILL_FOLDER / 'examples' / 'sun-and-hills'

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
