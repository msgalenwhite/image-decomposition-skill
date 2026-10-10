"""Simple shapes ("primitives") and how to fit each one to a region.

A primitive is a rectangle, rounded rectangle, ellipse, or polygon. Each
fitting function looks at one region of the image and returns the primitive
of its kind that best explains the region, or None when that kind of shape
cannot be fitted.

Fitting happens while layers are being worked out (see layer_order.py), so
every fit is told which regions are still in the picture and which have
already been lifted off the front. Where a region's edge runs along a shape
in front of it, that edge belongs to the shape in front, and the fitters
ignore it or rebuild what it hides.

All coordinates here are working-image pixels. A pixel's center is half a
pixel in from its corner, so the pixel in column 0, row 0 is at (0.5, 0.5).
"""

import dataclasses
import math

import contourpy
import numpy
from scipy import ndimage

# How far to look around an edge for a shape lying in front of it.
NEIGHBOR_SEARCH_RADIUS_PIXELS = 3

# Outline points this close to the canvas edge are treated as hidden: there
# the shape is cut off by the frame, not by its own outline.
CANVAS_EDGE_MARGIN_PIXELS = 3

# An ellipse needs at least this many outline points to be fitted.
MINIMUM_OUTLINE_POINTS = 24

# When tracing a polygon, outline wiggles smaller than this share of the
# canvas width are smoothed away. Large enough to ignore pixel stair-steps
# on slanted edges, small enough to keep real corners.
POLYGON_SIMPLIFY_TOLERANCE_PERCENT = 0.4

# A polygon may have at most this many corners. Twelve is enough for a
# six-pointed star. The limit cannot go much higher: a large curve traces
# as thirteen or more short straight edges, and with a higher limit that
# many-cornered polygon follows a slightly uneven hill more closely than
# an ellipse does, so the hill would be reported as a polygon.
MAXIMUM_POLYGON_POINTS = 12

# A freshly traced outline may have up to this many corners before it is
# tidied. The tidying removes many of them: a sharp tip traces as two
# corners, and a curved bite left by a shape in front traces as a dozen
# that collapse into one rebuilt corner or one straight cut. So the limit
# on the finished polygon is checked afterwards, and this looser limit only
# stops work early on outlines that are plainly curves.
MAXIMUM_TRACED_CORNERS = 48

# A straight line needs at least this many points before fitting one is
# more trustworthy than simply joining the two ends.
MINIMUM_POINTS_TO_FIT_A_LINE = 4

# When solving for an ellipse, a determinant closer to zero than this means
# the outline points lie along a straight line or a parabola, which has no
# center to solve for.
NO_ELLIPSE_CENTER_DETERMINANT = 1e-12

# Each polygon edge is refitted as a straight line through its outline
# points, ignoring this share at both ends where corners round off.
EDGE_END_TRIM_FRACTION = 0.15

# A refitted corner may move at most this many simplify-tolerances away
# from the traced corner. Further than that means the two edge lines are
# nearly parallel and their crossing point is not trustworthy. The limit
# has to allow for sharp points, whose soft tips trace well short of where
# the two sides would really meet.
CORNER_SNAP_LIMIT_IN_TOLERANCES = 5

# An edge shorter than this many simplify-tolerances is not a real side.
# It is the blunt end that soft edges leave on a sharp point, so it is
# dropped and the sides either side of it are extended to meet. The
# sharper the point, the longer its blunt end: five tolerances (2% of the
# canvas width) is long enough for a point as sharp as 20 degrees, such as
# where a slanted side runs into the canvas frame. The price is that a
# real side shorter than 2% of the canvas width is treated as a blunt end.
SHORT_EDGE_LIMIT_IN_TOLERANCES = 5

# Two neighboring edges whose fitted lines differ in direction by less
# than this are one straight side, and the corner between them is not
# real. Such corners appear when a rounded-off tip pulls the end of a long
# side slightly off line.
MINIMUM_CORNER_TURN_DEGREES = 6.0

# An edge counts as hidden when more than this share of it runs along the
# canvas frame or a shape in front.
HIDDEN_EDGE_FRACTION = 0.5

# A four-cornered polygon is a rectangle when every corner is within this
# many degrees of a right angle.
RIGHT_ANGLE_TOLERANCE_DEGREES = 4.0

# A rectangle tilted by less than this is reported as upright.
UPRIGHT_TOLERANCE_DEGREES = 1.0

# Corner radii smaller than this are indistinguishable from the slight
# rounding that soft edges give every sharp corner.
MINIMUM_CORNER_RADIUS_PIXELS = 3.0
MINIMUM_CORNER_RADIUS_SHARE_OF_SHORT_SIDE = 0.06

# How many corner radii to try in each of the two search passes.
CORNER_RADIUS_COARSE_STEPS = 13
CORNER_RADIUS_FINE_STEPS = 9

# Simpler kinds of shape are preferred. A simpler kind is chosen when its
# fit error is within this many percentage points of the best fit found.
SIMPLER_SHAPE_ALLOWANCE_PERCENT = 0.3

THREE_BY_THREE = numpy.ones((3, 3), dtype=bool)


@dataclasses.dataclass
class Primitive:
    """A fitted shape, measured in working-image pixels.

    Rectangles, rounded rectangles, and ellipses are described by a center,
    half sizes, and a clockwise tilt about the center. Polygons are
    described by `points` and leave the other measurements at zero.
    """
    kind: str  # 'rectangle', 'rounded-rectangle', 'ellipse', or 'polygon'
    center_x: float = 0.0
    center_y: float = 0.0
    half_width: float = 0.0
    half_height: float = 0.0
    rotation_degrees: float = 0.0
    corner_radius: float = 0.0
    points: list = None
    fit_error_percent: float = 0.0


@dataclasses.dataclass
class Window:
    """An upright box of pixels. Bottom and right are one past the end."""
    top: int
    bottom: int
    left: int
    right: int

    def slices(self):
        """Returns the (rows, columns) slices that cut this box out."""
        return slice(self.top, self.bottom), slice(self.left, self.right)

    def pixel_centers(self):
        """Returns the x and y of every pixel center inside the box."""
        rows, columns = numpy.mgrid[self.top:self.bottom, self.left:self.right]
        return columns + 0.5, rows + 0.5

    def grown(self, pixels, canvas_shape):
        """Returns this box made larger on every side, kept on the canvas."""
        canvas_height, canvas_width = canvas_shape
        return Window(top=max(self.top - pixels, 0),
                      bottom=min(self.bottom + pixels, canvas_height),
                      left=max(self.left - pixels, 0),
                      right=min(self.right + pixels, canvas_width))


@dataclasses.dataclass
class Scene:
    """What a fitter needs to know about the picture at one moment.

    `is_remaining[n]` is True while region n is still in the picture, and
    `is_front[n]` is True once region n has been lifted off the front.
    """
    region_of_pixel: numpy.ndarray
    is_remaining: numpy.ndarray
    is_front: numpy.ndarray
    # The number of pixels in each region.
    region_areas: numpy.ndarray

    def canvas_shape(self):
        """Returns the (height, width) of the working image."""
        return self.region_of_pixel.shape


def region_window(region):
    """Returns the smallest box holding a region."""
    return Window(region.top, region.bottom, region.left, region.right)


def whole_canvas(canvas_shape):
    """Returns the box covering the entire canvas."""
    return Window(0, canvas_shape[0], 0, canvas_shape[1])


def tilted_frame(primitive, window):
    """Returns each pixel's position in the primitive's own tilted frame.

    In that frame the primitive is upright and centered on zero, so the
    usual inside-tests for upright shapes apply.
    """
    pixel_x, pixel_y = window.pixel_centers()
    offset_x = pixel_x - primitive.center_x
    offset_y = pixel_y - primitive.center_y
    angle = math.radians(primitive.rotation_degrees)
    along_width = offset_x * math.cos(angle) + offset_y * math.sin(angle)
    along_height = -offset_x * math.sin(angle) + offset_y * math.cos(angle)
    return along_width, along_height


def rectangle_mask(primitive, window):
    """Returns the pixels in the window covered by a rectangle."""
    along_width, along_height = tilted_frame(primitive, window)
    return ((numpy.abs(along_width) <= primitive.half_width) &
            (numpy.abs(along_height) <= primitive.half_height))


def rounded_rectangle_mask(primitive, window):
    """Returns the pixels in the window covered by a rounded rectangle."""
    along_width, along_height = tilted_frame(primitive, window)
    distance_x = numpy.abs(along_width)
    distance_y = numpy.abs(along_height)
    inside_box = ((distance_x <= primitive.half_width) &
                  (distance_y <= primitive.half_height))
    # Each corner is rounded by a quarter circle. Its center sits one
    # corner radius in from both edges.
    corner_center_x = primitive.half_width - primitive.corner_radius
    corner_center_y = primitive.half_height - primitive.corner_radius
    in_corner_square = ((distance_x > corner_center_x) &
                        (distance_y > corner_center_y))
    outside_quarter_circle = ((distance_x - corner_center_x)**2 +
                              (distance_y - corner_center_y)**2
                              > primitive.corner_radius**2)
    return inside_box & ~(in_corner_square & outside_quarter_circle)


def ellipse_mask(primitive, window):
    """Returns the pixels in the window covered by an ellipse."""
    along_width, along_height = tilted_frame(primitive, window)
    return ((along_width / primitive.half_width)**2 +
            (along_height / primitive.half_height)**2) <= 1


def polygon_mask(primitive, window):
    """Returns the pixels in the window covered by a polygon.

    Uses the even-odd rule: a pixel is inside when a ray drawn from it to
    the right crosses the polygon's edges an odd number of times.
    """
    pixel_x, pixel_y = window.pixel_centers()
    inside = numpy.zeros(pixel_x.shape, dtype=bool)
    points = primitive.points
    for point_number, (start_x, start_y) in enumerate(points):
        end_x, end_y = points[(point_number + 1) % len(points)]
        if start_y == end_y:
            continue
        edge_spans_row = (start_y > pixel_y) != (end_y > pixel_y)
        crossing_x = (end_x - start_x) * (pixel_y -
                                          start_y) / (end_y - start_y) + start_x
        inside ^= edge_spans_row & (pixel_x < crossing_x)
    return inside


MASK_FUNCTIONS = {
    'rectangle': rectangle_mask,
    'rounded-rectangle': rounded_rectangle_mask,
    'ellipse': ellipse_mask,
    'polygon': polygon_mask,
}


def primitive_mask(primitive, window):
    """Returns the pixels in the window covered by any primitive."""
    return MASK_FUNCTIONS[primitive.kind](primitive, window)


def primitive_window(primitive, canvas_shape):
    """Returns the box on the canvas that a primitive could touch."""
    if primitive.kind == 'polygon':
        all_x = [point[0] for point in primitive.points]
        all_y = [point[1] for point in primitive.points]
        left, right = min(all_x), max(all_x)
        top, bottom = min(all_y), max(all_y)
    else:
        angle = math.radians(primitive.rotation_degrees)
        cosine, sine = abs(math.cos(angle)), abs(math.sin(angle))
        if primitive.kind == 'ellipse':
            reach_x = math.hypot(primitive.half_width * cosine,
                                 primitive.half_height * sine)
            reach_y = math.hypot(primitive.half_width * sine,
                                 primitive.half_height * cosine)
        else:
            reach_x = (primitive.half_width * cosine +
                       primitive.half_height * sine)
            reach_y = (primitive.half_width * sine +
                       primitive.half_height * cosine)
        left, right = primitive.center_x - reach_x, primitive.center_x + reach_x
        top, bottom = primitive.center_y - reach_y, primitive.center_y + reach_y
    canvas_height, canvas_width = canvas_shape
    return Window(top=min(max(math.floor(top), 0), canvas_height),
                  bottom=min(max(math.ceil(bottom), 0), canvas_height),
                  left=min(max(math.floor(left), 0), canvas_width),
                  right=min(max(math.ceil(right), 0), canvas_width))


def fit_error_percent(primitive, region_number, region, scene):
    """Scores a fit: 0 is perfect, larger is worse.

    Two things count against a fit:
      - Missed pixels: parts of the region the primitive fails to cover,
        as a share of the region's area.
      - Spilled pixels: parts of the primitive that land on another shape
        still in the picture. Each spill is measured as a share of the
        smaller of the two shapes. That way a large backdrop swallowing a
        small shape whole scores as a complete miss, even though the small
        shape is a tiny share of the backdrop.

    Pixels of shapes already lifted off the front are not counted, since
    the primitive may pass under them.
    """
    reach = primitive_window(primitive, scene.canvas_shape())
    window = Window(top=min(region.top, reach.top),
                    bottom=max(region.bottom, reach.bottom),
                    left=min(region.left, reach.left),
                    right=max(region.right, reach.right))
    regions_here = scene.region_of_pixel[window.slices()]
    own_pixels = regions_here == region_number
    other_remaining_pixels = scene.is_remaining[regions_here] & ~own_pixels
    covered = primitive_mask(primitive, window)
    missed_share = (own_pixels & ~covered).sum() / region.area_pixels
    spilled_counts = numpy.bincount(regions_here[covered &
                                                 other_remaining_pixels],
                                    minlength=len(scene.region_areas))
    smaller_areas = numpy.minimum(scene.region_areas, region.area_pixels)
    spilled_share = (spilled_counts / smaller_areas).sum()
    return 100 * float(missed_share + spilled_share)


def fit_upright_rectangle(region):
    """Returns the smallest upright rectangle holding the region."""
    return Primitive(kind='rectangle',
                     center_x=(region.left + region.right) / 2,
                     center_y=(region.top + region.bottom) / 2,
                     half_width=(region.right - region.left) / 2,
                     half_height=(region.bottom - region.top) / 2)


def fit_rounded_rectangle(region_number, region, scene):
    """Finds the corner radius that best rounds the region's bounding box.

    Tries a spread of radii from square corners to fully round ends, then
    looks more closely around the best one. Returns None when the best
    radius is too small to tell apart from a plain rectangle.
    """
    box = fit_upright_rectangle(region)
    largest_radius = min(box.half_width, box.half_height)

    # Everything that does not depend on the radius is worked out once,
    # because the search below scores a couple of dozen radii.
    window = region_window(region)
    regions_here = scene.region_of_pixel[window.slices()]
    own_pixels = regions_here == region_number
    other_remaining_pixels = scene.is_remaining[regions_here] & ~own_pixels
    distance_x, distance_y = (
        numpy.abs(distance) for distance in tilted_frame(box, window))

    def error_for(radius):
        """Scores one radius the same way fit_error_percent would."""
        corner_center_x = box.half_width - radius
        corner_center_y = box.half_height - radius
        cut_away = ((distance_x > corner_center_x) &
                    (distance_y > corner_center_y) &
                    ((distance_x - corner_center_x)**2 +
                     (distance_y - corner_center_y)**2 > radius**2))
        missed_count = (own_pixels & cut_away).sum()
        spilled_count = (other_remaining_pixels & ~cut_away).sum()
        return missed_count + spilled_count

    coarse_radii = numpy.linspace(0, largest_radius, CORNER_RADIUS_COARSE_STEPS)
    best_coarse_radius = min(coarse_radii, key=error_for)
    coarse_step = largest_radius / (CORNER_RADIUS_COARSE_STEPS - 1)
    fine_radii = numpy.linspace(
        max(best_coarse_radius - coarse_step, 0),
        min(best_coarse_radius + coarse_step, largest_radius),
        CORNER_RADIUS_FINE_STEPS)
    best_radius = float(min(fine_radii, key=error_for))

    smallest_meaningful_radius = max(
        MINIMUM_CORNER_RADIUS_PIXELS,
        MINIMUM_CORNER_RADIUS_SHARE_OF_SHORT_SIDE * 2 * largest_radius)
    if best_radius < smallest_meaningful_radius:
        return None
    return dataclasses.replace(box,
                               kind='rounded-rectangle',
                               corner_radius=best_radius)


def own_edge_points(region_number, region, scene):
    """Returns pixel centers lying along the region's own visible edge.

    A point counts only where the region meets another shape that is still
    in the picture. Points beside a shape in front are skipped, because
    there the edge belongs to the shape in front. Points are taken from
    both sides of the edge so that their average sits exactly on it.
    """
    window = region_window(region).grown(NEIGHBOR_SEARCH_RADIUS_PIXELS + 1,
                                         scene.canvas_shape())
    regions_here = scene.region_of_pixel[window.slices()]
    own_pixels = regions_here == region_number
    other_remaining_pixels = scene.is_remaining[regions_here] & ~own_pixels
    own_side = own_pixels & ndimage.binary_dilation(other_remaining_pixels,
                                                    structure=THREE_BY_THREE)
    facing_side = other_remaining_pixels & ndimage.binary_dilation(
        own_pixels, structure=THREE_BY_THREE)
    usable = (own_side | facing_side) & ~near_front_pixels(scene, window)
    pixel_x, pixel_y = window.pixel_centers()
    usable &= ~near_canvas_edge(pixel_x, pixel_y, scene.canvas_shape())
    return pixel_x[usable], pixel_y[usable]


def near_front_pixels(scene, window):
    """Returns the pixels in the window that are close to a shape in front."""
    front_pixels = scene.is_front[scene.region_of_pixel[window.slices()]]
    search_diameter = 2 * NEIGHBOR_SEARCH_RADIUS_PIXELS + 1
    search_square = numpy.ones((search_diameter, search_diameter), dtype=bool)
    return ndimage.binary_dilation(front_pixels, structure=search_square)


def near_canvas_edge(point_x, point_y, canvas_shape):
    """Says, for each point, whether it is within the canvas edge margin."""
    canvas_height, canvas_width = canvas_shape
    margin = CANVAS_EDGE_MARGIN_PIXELS
    return ((point_x < margin) | (point_x > canvas_width - margin) |
            (point_y < margin) | (point_y > canvas_height - margin))


def fit_ellipse(region_number, region, scene):
    """Fits a tilted ellipse through the region's own edge, or returns None.

    Every ellipse satisfies an equation of the form
        a*x*x + b*x*y + c*y*y + d*x + e*y = 1
    once x and y are measured from a point inside it. Least squares finds
    the five numbers that best satisfy that equation at every edge point;
    the center, radii, and tilt are then read off those numbers.
    """
    points_x, points_y = own_edge_points(region_number, region, scene)
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
    if abs(numpy.linalg.det(quadratic_part)) < NO_ELLIPSE_CENTER_DETERMINANT:
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
    # report how far it is tilted. Positive means clockwise on screen.
    first_direction = axis_directions[:, 0]
    width_axis = 0 if abs(first_direction[0]) >= abs(first_direction[1]) else 1
    width_direction = axis_directions[:, width_axis]
    if width_direction[0] < 0:
        width_direction = -width_direction
    rotation_degrees = math.degrees(
        math.atan2(width_direction[1], width_direction[0]))
    return Primitive(kind='ellipse',
                     center_x=float(origin_x + center[0] * scale),
                     center_y=float(origin_y + center[1] * scale),
                     half_width=float(radii[width_axis]),
                     half_height=float(radii[1 - width_axis]),
                     rotation_degrees=rotation_degrees)


def trace_outline(region_number, region, scene):
    """Returns the region's outer outline as an ordered loop of points.

    The points run all the way around the region, one or two per pixel,
    along the boundary between its pixels and everything else.
    """
    window = region_window(region)
    own_pixels = scene.region_of_pixel[window.slices()] == region_number
    # A ring of empty pixels lets the outline close where the region
    # touches the canvas frame.
    padded = numpy.pad(own_pixels, 1).astype(float)
    halfway_between_inside_and_outside = 0.5
    loops = contourpy.contour_generator(
        z=padded).lines(halfway_between_inside_and_outside)
    if not loops:
        return None
    longest_loop = max(loops, key=len)
    # The loop repeats its first point at the end; drop the repeat. Undo
    # the padding and move from pixel indexes to pixel centers.
    outline = longest_loop[:-1] + numpy.array(
        [window.left - 1 + 0.5, window.top - 1 + 0.5])
    return outline


def distance_from_line(points, line_start, line_end):
    """Returns each point's distance from the line through two points."""
    direction = line_end - line_start
    length = numpy.linalg.norm(direction)
    if length == 0:
        return numpy.linalg.norm(points - line_start, axis=1)
    offsets = points - line_start
    return numpy.abs(direction[0] * offsets[:, 1] -
                     direction[1] * offsets[:, 0]) / length


def simplify_path(points, tolerance):
    """Returns the indexes of the points worth keeping on an open path.

    This is the Douglas-Peucker method: join the two ends with a straight
    line and find the point furthest from it. If that point is further
    than the tolerance it is a real corner, so keep it and repeat on the
    two halves either side of it. Otherwise the whole stretch is straight
    enough and everything between the ends is dropped.
    """
    kept_indexes = {0, len(points) - 1}
    stretches_to_check = [(0, len(points) - 1)]
    while stretches_to_check:
        first_index, last_index = stretches_to_check.pop()
        if last_index - first_index < 2:
            continue
        distances = distance_from_line(points[first_index + 1:last_index],
                                       points[first_index], points[last_index])
        furthest_offset = int(distances.argmax())
        if distances[furthest_offset] > tolerance:
            corner_index = first_index + 1 + furthest_offset
            kept_indexes.add(corner_index)
            stretches_to_check.append((first_index, corner_index))
            stretches_to_check.append((corner_index, last_index))
    return sorted(kept_indexes)


def find_corner_indexes(outline, tolerance):
    """Returns the indexes of the outline points that are real corners.

    A closed loop has no ends to start from, so two far-apart points are
    picked as anchors and each half of the loop is simplified between them.
    Both anchors are certain to be corners or very near one.
    """
    centroid = outline.mean(axis=0)
    first_anchor = int(numpy.linalg.norm(outline - centroid, axis=1).argmax())
    turned = numpy.roll(outline, -first_anchor, axis=0)
    second_anchor = int(numpy.linalg.norm(turned - turned[0], axis=1).argmax())
    closed = numpy.vstack([turned, turned[:1]])
    first_half = simplify_path(closed[:second_anchor + 1], tolerance)
    second_half = simplify_path(closed[second_anchor:], tolerance)
    corner_indexes = first_half + [
        second_anchor + index for index in second_half[1:-1]
    ]
    return sorted(
        (first_anchor + index) % len(outline) for index in corner_indexes)


@dataclasses.dataclass
class Edge:
    """One straight side of a traced outline."""
    start_point: numpy.ndarray
    end_point: numpy.ndarray
    # The straight line that best follows the side: any point on it, and
    # a direction of length one pointing from start toward end.
    line_point: numpy.ndarray
    line_direction: numpy.ndarray
    # True when the side runs along the frame or a shape in front, so it
    # is where the region was cut off and not a side of the real shape.
    is_hidden: bool


def fit_line_through(points, start_point, end_point):
    """Returns the line that best follows a run of points.

    The best line passes through the points' average position, in the
    direction along which they are most spread out.
    """
    toward_end = end_point - start_point
    if len(points) < MINIMUM_POINTS_TO_FIT_A_LINE:
        return start_point, toward_end / numpy.linalg.norm(toward_end)
    average = points.mean(axis=0)
    spread_directions = numpy.linalg.svd(points - average,
                                         full_matrices=False)[2]
    direction = spread_directions[0]
    if direction @ toward_end < 0:
        direction = -direction
    return average, direction


def build_edges(outline, corner_indexes, point_is_hidden):
    """Turns corners on an outline into Edge objects, in order."""
    edges = []
    for corner_number, start_index in enumerate(corner_indexes):
        end_index = corner_indexes[(corner_number + 1) % len(corner_indexes)]
        if end_index > start_index:
            indexes = numpy.arange(start_index, end_index + 1)
        else:
            indexes = numpy.concatenate([
                numpy.arange(start_index, len(outline)),
                numpy.arange(0, end_index + 1)
            ])
        is_hidden = point_is_hidden[indexes].mean() > HIDDEN_EDGE_FRACTION
        trim = int(len(indexes) * EDGE_END_TRIM_FRACTION)
        middle_indexes = indexes[trim:len(indexes) - trim]
        start_point, end_point = outline[start_index], outline[end_index]
        if is_hidden:
            # A hidden side is only a cut, so do not refine it.
            line_point, line_direction = fit_line_through(
                outline[:0], start_point, end_point)
        else:
            line_point, line_direction = fit_line_through(
                outline[middle_indexes], start_point, end_point)
        edges.append(
            Edge(start_point, end_point, line_point, line_direction, is_hidden))
    return edges


def build_edges_without_false_corners(outline, corner_indexes, point_is_hidden):
    """Builds the edges, merging neighbors that are really one side.

    Whenever two visible edges in a row run in almost the same direction,
    the corner between them is dropped and the edges are built again, so
    the merged side gets one line fitted along its whole length.
    """
    corner_indexes = list(corner_indexes)
    fewest_corners_of_a_polygon = 3
    while True:
        edges = build_edges(outline, corner_indexes, point_is_hidden)
        if len(edges) <= fewest_corners_of_a_polygon:
            return edges
        slightest_turn = MINIMUM_CORNER_TURN_DEGREES
        false_corner_position = None
        for position, edge in enumerate(edges):
            next_edge = edges[(position + 1) % len(edges)]
            if edge.is_hidden or next_edge.is_hidden:
                continue
            cosine = numpy.clip(edge.line_direction @ next_edge.line_direction,
                                -1, 1)
            turn = math.degrees(math.acos(cosine))
            if turn < slightest_turn:
                slightest_turn = turn
                # The corner after edge number `position` is the start of
                # the next edge.
                false_corner_position = (position + 1) % len(edges)
        if false_corner_position is None:
            return edges
        del corner_indexes[false_corner_position]


def without_blunt_tips(edges, shortest_real_edge):
    """Returns the edges with stubs too short to be real sides removed.

    A stub appears where soft edges blunt a sharp point, and also where a
    side runs into the canvas frame: its last few pixels count as hidden
    and trace as a tiny edge of their own. Either way the sides on both
    sides of the stub are then extended until they meet, which puts the
    corner where it really is.
    """
    real_edges = [
        edge for edge in edges
        if numpy.linalg.norm(edge.end_point -
                             edge.start_point) >= shortest_real_edge
    ]
    fewest_sides_of_a_polygon = 3
    if len(real_edges) < fewest_sides_of_a_polygon:
        return edges
    return real_edges


def line_crossing(first_edge, second_edge):
    """Returns where two edges' lines cross, or None if they are parallel."""
    directions = numpy.column_stack(
        [first_edge.line_direction, -second_edge.line_direction])
    nearly_parallel = 1e-6
    if abs(numpy.linalg.det(directions)) < nearly_parallel:
        return None
    distance_along_first = numpy.linalg.solve(
        directions, second_edge.line_point - first_edge.line_point)[0]
    return (first_edge.line_point +
            distance_along_first * first_edge.line_direction)


def is_hidden_place(point, region_number, scene):
    """Says whether a point is somewhere a shape's corner could hide.

    That is: off the canvas, or under a shape that sits in front.
    """
    canvas_height, canvas_width = scene.canvas_shape()
    column, row = math.floor(point[0]), math.floor(point[1])
    if not (0 <= column < canvas_width and 0 <= row < canvas_height):
        return True
    region_there = scene.region_of_pixel[row, column]
    return bool(scene.is_front[region_there]) and region_there != region_number


def rebuilt_corner(edge_before, edge_after, region_number, scene):
    """Returns the hidden corner two visible edges point toward, or None.

    When something covers a corner, the two visible sides leading into the
    gap can be extended until they meet. The meeting point is accepted
    only if both sides reach it by continuing forward, and it lies where a
    corner could really be hiding.
    """
    crossing = line_crossing(edge_before, edge_after)
    if crossing is None:
        return None
    slack = CANVAS_EDGE_MARGIN_PIXELS
    continues_forward = (
        (crossing - edge_before.end_point) @ edge_before.line_direction
        >= -slack)
    arrives_from_behind = (
        (edge_after.start_point - crossing) @ edge_after.line_direction
        >= -slack)
    farthest_plausible = 2 * max(scene.canvas_shape())
    within_reach = (numpy.linalg.norm(crossing - edge_before.end_point)
                    <= farthest_plausible)
    if not (continues_forward and arrives_from_behind and within_reach):
        return None
    if not is_hidden_place(crossing, region_number, scene):
        return None
    return crossing


def straight_cut(start_point, end_point):
    """Returns a hidden edge running straight between two points."""
    line_point, line_direction = fit_line_through(numpy.empty((0, 2)),
                                                  start_point, end_point)
    return Edge(start_point, end_point, line_point, line_direction, True)


def resolve_hidden_edges(edges, region_number, scene, straighten_cuts):
    """Decides what to do with each run of hidden edges.

    Returns a list of (edge, corner) pairs going around the shape. The
    corner is the rebuilt corner that follows the edge, or None when the
    corner should be worked out from the edge and the one after it.

    For each run of hidden edges between two visible ones:
      - If the visible edges point to a corner hiding behind the cut, the
        run is dropped and that corner takes its place.
      - Otherwise, if `straighten_cuts` is set and the run has several
        edges, the run becomes one straight cut. A shape in front usually
        leaves a curved or jagged bite, and what lies under the shape in
        front is unknown, so a straight cut is the simplest honest guess.
      - Otherwise the run is kept as traced.
    """
    visible_numbers = [
        number for number, edge in enumerate(edges) if not edge.is_hidden
    ]
    fewest_visible_edges_to_work_from = 2
    if len(visible_numbers) < fewest_visible_edges_to_work_from:
        return [(edge, None) for edge in edges]

    resolved = []
    for position, before_number in enumerate(visible_numbers):
        after_number = visible_numbers[(position + 1) % len(visible_numbers)]
        edge_before, edge_after = edges[before_number], edges[after_number]
        hidden_run = [
            edges[(before_number + step) % len(edges)]
            for step in range(1, (after_number - before_number - 1) %
                              len(edges) + 1)
        ]
        if not hidden_run:
            resolved.append((edge_before, None))
            continue
        corner = rebuilt_corner(edge_before, edge_after, region_number, scene)
        if corner is not None:
            resolved.append((edge_before, corner))
            continue
        resolved.append((edge_before, None))
        if straighten_cuts and len(hidden_run) > 1:
            resolved.append((straight_cut(edge_before.end_point,
                                          edge_after.start_point), None))
        else:
            resolved.extend((hidden_edge, None) for hidden_edge in hidden_run)
    return resolved


def corners_from_edges(resolved_edges, snap_limit):
    """Returns the polygon's corners from resolved edges.

    Where a corner was rebuilt it is used as is. Everywhere else the
    corner is where an edge's fitted line crosses the next edge's, unless
    that crossing strays too far from the traced corner to be trusted.
    """
    corners = []
    for position, (edge, corner_after) in enumerate(resolved_edges):
        if corner_after is not None:
            corners.append(corner_after)
            continue
        next_edge = resolved_edges[(position + 1) % len(resolved_edges)][0]
        crossing = line_crossing(edge, next_edge)
        traced_corner = edge.end_point
        if (crossing is None or
                numpy.linalg.norm(crossing - traced_corner) > snap_limit):
            corners.append(traced_corner)
        else:
            corners.append(crossing)
    return corners


def in_reading_order(corners):
    """Returns corners clockwise on screen, starting from the top-most."""
    corners = [(float(corner[0]), float(corner[1])) for corner in corners]
    # The "shoelace" sum is positive when points run clockwise on a screen,
    # where y grows downward.
    shoelace_sum = sum(start[0] * end[1] - end[0] * start[1]
                       for start, end in zip(corners, corners[1:] +
                                             corners[:1]))
    if shoelace_sum < 0:
        corners.reverse()
    top_most = min(range(len(corners)),
                   key=lambda number: (corners[number][1], corners[number][0]))
    return corners[top_most:] + corners[:top_most]


def as_rectangle_if_square_cornered(corners):
    """Returns a tilted rectangle if four corners form one, else None."""
    if len(corners) != 4:
        return None
    points = numpy.array(corners)
    sides = numpy.roll(points, -1, axis=0) - points
    for side_number in range(4):
        this_side = sides[side_number]
        next_side = sides[(side_number + 1) % 4]
        cosine = (this_side @ next_side) / (numpy.linalg.norm(this_side) *
                                            numpy.linalg.norm(next_side))
        corner_degrees = math.degrees(math.acos(numpy.clip(cosine, -1, 1)))
        if abs(corner_degrees - 90) > RIGHT_ANGLE_TOLERANCE_DEGREES:
            return None
    side_lengths = numpy.linalg.norm(sides, axis=1)
    first_pair_length = (side_lengths[0] + side_lengths[2]) / 2
    second_pair_length = (side_lengths[1] + side_lengths[3]) / 2

    def tilt_of(side):
        """Returns a side's tilt from horizontal, between -90 and 90."""
        degrees = math.degrees(math.atan2(side[1], side[0]))
        return (degrees + 90) % 180 - 90

    first_tilt, second_tilt = tilt_of(sides[0]), tilt_of(sides[1])
    # The pair of sides lying closer to horizontal gives the width.
    if abs(first_tilt) <= abs(second_tilt):
        width, height = first_pair_length, second_pair_length
        rotation = first_tilt
    else:
        width, height = second_pair_length, first_pair_length
        rotation = second_tilt
    if abs(rotation) < UPRIGHT_TOLERANCE_DEGREES:
        rotation = 0.0
    center = points.mean(axis=0)
    return Primitive(kind='rectangle',
                     center_x=float(center[0]),
                     center_y=float(center[1]),
                     half_width=float(width / 2),
                     half_height=float(height / 2),
                     rotation_degrees=float(rotation))


def fit_polygon(region_number, region, scene):
    """Fits a straight-sided shape to the region, or returns None.

    Traces the region's outline, keeps only its real corners, refits each
    side as a straight line, and rebuilds corners hidden behind shapes in
    front. Four square corners are reported as a tilted rectangle.
    """
    outline = trace_outline(region_number, region, scene)
    if outline is None or len(outline) < MINIMUM_OUTLINE_POINTS:
        return None
    canvas_width = scene.canvas_shape()[1]
    tolerance = canvas_width * POLYGON_SIMPLIFY_TOLERANCE_PERCENT / 100
    corner_indexes = find_corner_indexes(outline, tolerance)
    if not 3 <= len(corner_indexes) <= MAXIMUM_TRACED_CORNERS:
        return None

    # Look up, for every outline point, whether a shape in front is close.
    # The lookup grid only needs to cover the region and a little around it.
    window = region_window(region).grown(NEIGHBOR_SEARCH_RADIUS_PIXELS + 1,
                                         scene.canvas_shape())
    near_front = near_front_pixels(scene, window)
    columns = numpy.clip(
        numpy.floor(outline[:, 0]).astype(int) - window.left, 0,
        near_front.shape[1] - 1)
    rows = numpy.clip(
        numpy.floor(outline[:, 1]).astype(int) - window.top, 0,
        near_front.shape[0] - 1)
    point_is_hidden = near_front[rows, columns] | near_canvas_edge(
        outline[:, 0], outline[:, 1], scene.canvas_shape())

    edges = without_blunt_tips(
        build_edges_without_false_corners(outline, corner_indexes,
                                          point_is_hidden),
        shortest_real_edge=SHORT_EDGE_LIMIT_IN_TOLERANCES * tolerance)
    snap_limit = CORNER_SNAP_LIMIT_IN_TOLERANCES * tolerance

    def polygon_with(straighten_cuts):
        """Builds the polygon with or without straightened cuts."""
        corners = corners_from_edges(
            resolve_hidden_edges(edges, region_number, scene, straighten_cuts),
            snap_limit)
        fewest_corners_of_a_polygon = 3
        if not (fewest_corners_of_a_polygon <= len(corners) <=
                MAXIMUM_POLYGON_POINTS):
            return None
        corners = in_reading_order(corners)
        candidate = as_rectangle_if_square_cornered(corners)
        if candidate is None:
            candidate = Primitive(kind='polygon', points=corners)
        candidate.fit_error_percent = fit_error_percent(candidate,
                                                        region_number, region,
                                                        scene)
        return candidate

    # Prefer the version with straightened cuts, which has fewer corners,
    # unless straightening made the fit noticeably worse.
    as_traced = polygon_with(straighten_cuts=False)
    straightened = polygon_with(straighten_cuts=True)
    if as_traced is None or straightened is None:
        return straightened or as_traced
    if (straightened.fit_error_percent
            <= as_traced.fit_error_percent + SIMPLER_SHAPE_ALLOWANCE_PERCENT):
        return straightened
    return as_traced


def fit_best_primitive(region_number, region, scene):
    """Fits each kind of primitive and returns the simplest good one.

    Kinds are tried from simplest to most flexible. The most flexible
    kind nearly always fits a little better, so a simpler kind wins
    whenever it comes within a small allowance of the best fit found.
    For the same reason the search stops early as soon as one kind fits
    within that allowance of perfect: nothing later could displace it.
    """
    fitters_simplest_first = [
        lambda: fit_upright_rectangle(region),
        lambda: fit_ellipse(region_number, region, scene),
        lambda: fit_rounded_rectangle(region_number, region, scene),
        lambda: fit_polygon(region_number, region, scene),
    ]
    candidates = []
    for fitter in fitters_simplest_first:
        candidate = fitter()
        if candidate is None:
            continue
        candidate.fit_error_percent = fit_error_percent(candidate,
                                                        region_number, region,
                                                        scene)
        candidates.append(candidate)
        if candidate.fit_error_percent <= SIMPLER_SHAPE_ALLOWANCE_PERCENT:
            break
    best_error = min(candidate.fit_error_percent for candidate in candidates)
    return next(candidate for candidate in candidates
                if candidate.fit_error_percent <= best_error +
                SIMPLER_SHAPE_ALLOWANCE_PERCENT)
