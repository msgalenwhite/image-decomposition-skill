"""Works out which shape is in front of which.

The method is to "peel" the picture from the front. The front-most shape
is the one whose visible area is already a complete simple shape, because
nothing covers it. Lift it off, and the shape it was covering can now be
fitted using only the edges that are truly its own. Repeat until nothing
is left. The order shapes were lifted off, reversed, is back to front.
"""

import numpy

import primitives

# When choosing which shape to lift off next, a polygon is treated as a
# worse fit by this many percentage points for every corner beyond three.
#
# Why: a shape with a piece hidden by a shape in front can always be
# traced as a polygon with extra corners, and that tracing fits perfectly.
# A triangle with one corner covered, for instance, looks exactly like a
# four-cornered shape. Covering part of a shape almost always adds corners
# to what is left showing, so of two shapes that both fit, the one with
# fewer corners is the likelier to be whole, and it comes off first. The
# shape behind can then be fitted as what it really is.
EXTRA_CORNER_PENALTY_PERCENT = 0.5
CORNERS_WITHOUT_PENALTY = 3


def lifting_score(primitive):
    """Returns how reluctant we are to lift this shape off next."""
    extra_corners = 0
    if primitive.kind == 'polygon':
        extra_corners = max(len(primitive.points) - CORNERS_WITHOUT_PENALTY, 0)
    return (primitive.fit_error_percent +
            EXTRA_CORNER_PENALTY_PERCENT * extra_corners)


def boxes_overlap(first, second):
    """Says whether two Window boxes share any pixels."""
    return (first.left < second.right and second.left < first.right and
            first.top < second.bottom and second.top < first.bottom)


def regions_affected_by(lifted_number, remaining, region_map, fits):
    """Returns the remaining regions whose fit may change.

    Lifting a shape off changes the fit of anything that touched it (more
    of its edge is now its own) and of anything whose fitted primitive
    reached under it (that overlap no longer counts against the fit). Both
    cases are caught by checking whether the lifted shape's box overlaps
    the other region's box or its primitive's reach, with a little room
    for the edge search.
    """
    canvas_shape = region_map.region_of_pixel.shape
    room = primitives.NEIGHBOR_SEARCH_RADIUS_PIXELS + 1
    lifted_box = primitives.region_window(
        region_map.regions[lifted_number]).grown(room, canvas_shape)
    affected = set()
    for region_number in remaining:
        own_box = primitives.region_window(region_map.regions[region_number])
        reach = primitives.primitive_window(fits[region_number], canvas_shape)
        if boxes_overlap(lifted_box, own_box) or boxes_overlap(
                lifted_box, reach):
            affected.add(region_number)
    return affected


def find_layer_order(region_map):
    """Returns region numbers back to front, and each region's primitive."""
    region_count = len(region_map.regions)
    scene = primitives.Scene(
        region_of_pixel=region_map.region_of_pixel,
        is_remaining=numpy.ones(region_count, dtype=bool),
        is_front=numpy.zeros(region_count, dtype=bool),
        region_areas=numpy.array(
            [region.area_pixels for region in region_map.regions]))
    remaining = set(range(region_count))
    lifted_off = []
    fits = {}
    needs_fitting = set(remaining)
    while remaining:
        for region_number in needs_fitting:
            fits[region_number] = primitives.fit_best_primitive(
                region_number, region_map.regions[region_number], scene)
        # Ties go to the lower region number so results never depend on
        # the order a set happens to be walked in.
        front_most = min(remaining,
                         key=lambda number:
                         (lifting_score(fits[number]), number))
        remaining.remove(front_most)
        lifted_off.append(front_most)
        scene.is_remaining[front_most] = False
        scene.is_front[front_most] = True
        needs_fitting = regions_affected_by(front_most, remaining, region_map,
                                            fits)
    back_to_front = lifted_off[::-1]
    return back_to_front, fits
