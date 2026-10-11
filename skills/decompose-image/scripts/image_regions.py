"""Turns an image into regions: connected patches of one palette color.

Steps, in order:
    1. Find the palette: the few colors that fill most of the image.
    2. Label every pixel with its palette color. Blended pixels along an
       edge match no color and stay unlabeled.
    3. Split each color into connected patches and drop tiny specks.
    4. Hand every leftover pixel to its nearest patch, which splits each
       blended edge band down the middle between the two shapes it joins.

The result is a "region map": a grid the size of the image in which every
pixel holds the number of the region it belongs to.
"""

import dataclasses

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

# A connected patch smaller than this is dropped as a stray speck.
DEFAULT_MINIMUM_SHAPE_PERCENT = 0.1

UNLABELED = -1


@dataclasses.dataclass
class Region:
    """One connected patch of a single palette color."""
    color_index: int
    area_pixels: int
    # The smallest upright box holding the region, as pixel indexes.
    # Bottom and right are one past the last row and column.
    top: int
    bottom: int
    left: int
    right: int


@dataclasses.dataclass
class RegionMap:
    """Every region in the image and the grid saying which pixel is whose."""
    regions: list
    # Same height and width as the working image. Each entry is an index
    # into `regions`.
    region_of_pixel: numpy.ndarray
    dropped_speck_count: int


def load_working_pixels(image_path):
    """Opens the image, flattens transparency onto white, and shrinks it.

    Returns the pixels and the original (width, height).
    """
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
    """Splits each color into connected regions and builds the region map."""
    minimum_area = labels.size * minimum_shape_percent / 100
    region_colors = []
    region_of_pixel = numpy.full(labels.shape, UNLABELED)
    dropped_speck_count = 0
    for color_index in range(color_count):
        numbered_patches, patch_count = ndimage.label(labels == color_index)
        patch_areas = numpy.bincount(numbered_patches.ravel())
        for patch_number in range(1, patch_count + 1):
            if patch_areas[patch_number] < minimum_area:
                dropped_speck_count += 1
                continue
            region_of_pixel[numbered_patches == patch_number] = len(
                region_colors)
            region_colors.append(color_index)

    if not region_colors:
        return RegionMap([], region_of_pixel, dropped_speck_count)

    # Pixels still unlabeled are blended edge bands and dropped specks.
    # Give each one to the nearest region. Along an edge this splits the
    # blended band down the middle, which is where the true edge lies.
    unlabeled = region_of_pixel == UNLABELED
    nearest_labeled_row, nearest_labeled_column = (
        ndimage.distance_transform_edt(unlabeled,
                                       return_distances=False,
                                       return_indices=True))
    region_of_pixel = region_of_pixel[nearest_labeled_row,
                                      nearest_labeled_column]

    regions = []
    bounding_slices = ndimage.find_objects(region_of_pixel + 1)
    areas = numpy.bincount(region_of_pixel.ravel(),
                           minlength=len(region_colors))
    for region_number, color_index in enumerate(region_colors):
        row_slice, column_slice = bounding_slices[region_number]
        regions.append(
            Region(color_index=color_index,
                   area_pixels=int(areas[region_number]),
                   top=row_slice.start,
                   bottom=row_slice.stop,
                   left=column_slice.start,
                   right=column_slice.stop))
    return RegionMap(regions, region_of_pixel, dropped_speck_count)
