"""Rename shapes and colors in a breakdown, and group shapes into objects.

The measuring script can only name a shape after its color and kind, such
as "pink-circle". Whoever has looked at the picture knows it is the sun.
This tool applies those better names everywhere they appear, so nothing
is left half-renamed.

Usage:
    python3 rename_shapes.py FOLDER \\
        --shape pink-circle=sun --shape green-ellipse=hill-green \\
        --color blue=sky \\
        --group hills=hill-green,hill-lavender

FOLDER is the folder holding breakdown.json. Both breakdown.json and
breakdown.md are rewritten. Only names change; no measurement is touched.
"""

import argparse
import json
import pathlib
import re
import sys

import breakdown_report

# Whole lowercase words joined by hyphens, for example "tree-trunk".
NAME_PATTERN = re.compile(r'^[a-z]+(-[a-z]+)*$')


class RenameError(ValueError):
    """Raised when a requested rename cannot be applied safely."""


def parse_pairs(pair_texts, option_name):
    """Turns ['old=new', ...] into {'old': 'new', ...}."""
    pairs = {}
    for pair_text in pair_texts:
        old_name, separator, new_name = pair_text.partition('=')
        if not separator or not old_name or not new_name:
            raise RenameError(
                f'{option_name} expects OLD=NEW, but got "{pair_text}".')
        pairs[old_name] = new_name
    return pairs


def check_new_name(new_name):
    """Raises RenameError unless the name is hyphenated lowercase words."""
    if not NAME_PATTERN.match(new_name):
        raise RenameError(
            f'"{new_name}" is not a valid name. Use whole lowercase words '
            'joined by hyphens, for example "tree-trunk".')


def renamed(existing_names, renames, what):
    """Returns the names after renaming, checking nothing goes wrong."""
    for old_name, new_name in renames.items():
        if old_name not in existing_names:
            known = ', '.join(existing_names)
            raise RenameError(
                f'There is no {what} named "{old_name}". Known: {known}.')
        check_new_name(new_name)
    new_names = [renames.get(name, name) for name in existing_names]
    repeated = sorted({name for name in new_names if new_names.count(name) > 1})
    if repeated:
        raise RenameError(f'These {what} names would be used twice: ' +
                          ', '.join(repeated) + '.')
    return new_names


def apply_renames(breakdown, shape_renames, color_renames, groups):
    """Returns a copy of the breakdown with new names and groups applied.

    `groups` maps a group name to the list of (new) shape names in it and,
    when not empty, replaces any groups already in the breakdown.
    """
    breakdown = json.loads(json.dumps(breakdown))  # A fully separate copy.
    old_shape_names = [shape['name'] for shape in breakdown['shapes']]
    new_shape_names = renamed(old_shape_names, shape_renames, 'shape')
    old_color_names = [color['name'] for color in breakdown['palette']]
    new_color_names = renamed(old_color_names, color_renames, 'color')
    shape_name_for = dict(zip(old_shape_names, new_shape_names))
    color_name_for = dict(zip(old_color_names, new_color_names))

    for color in breakdown['palette']:
        color['name'] = color_name_for[color['name']]
    for shape in breakdown['shapes']:
        shape['name'] = shape_name_for[shape['name']]
        shape['color'] = color_name_for[shape['color']]
    breakdown['layers_back_to_front'] = [
        shape_name_for[name] for name in breakdown['layers_back_to_front']
    ]
    for group in breakdown['groups']:
        group['members'] = [
            shape_name_for[member] for member in group['members']
        ]

    if groups:
        for group_name, members in groups.items():
            check_new_name(group_name)
            for member in members:
                if member not in new_shape_names:
                    raise RenameError(
                        f'Group "{group_name}" lists "{member}", which is '
                        'not a shape. Use the names shapes have after '
                        'renaming.')
        breakdown['groups'] = [{
            'name': group_name,
            'members': members
        } for group_name, members in groups.items()]
    return breakdown


def main(arguments):
    """Runs the command-line tool."""
    parser = argparse.ArgumentParser(
        description='Rename shapes and colors in a breakdown.')
    parser.add_argument('folder',
                        type=pathlib.Path,
                        help='Folder holding breakdown.json.')
    parser.add_argument('--shape',
                        action='append',
                        default=[],
                        metavar='OLD=NEW',
                        help='Rename one shape. May be repeated.')
    parser.add_argument('--color',
                        action='append',
                        default=[],
                        metavar='OLD=NEW',
                        help='Rename one palette color. May be repeated.')
    parser.add_argument('--group',
                        action='append',
                        default=[],
                        metavar='NAME=SHAPE,SHAPE',
                        help='Group shapes into one object. May be repeated.')
    options = parser.parse_args(arguments)
    breakdown_path = options.folder / 'breakdown.json'
    try:
        groups = {
            group_name: members_text.split(',') for group_name, members_text in
            parse_pairs(options.group, '--group').items()
        }
        breakdown = apply_renames(json.loads(breakdown_path.read_text()),
                                  parse_pairs(options.shape, '--shape'),
                                  parse_pairs(options.color, '--color'), groups)
    except RenameError as error:
        print(error, file=sys.stderr)
        return 1
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        print(f'Could not read {breakdown_path} as a breakdown: {error!r}',
              file=sys.stderr)
        return 1
    # Both texts are prepared before either file is touched, and the
    # Markdown is written first: if it cannot be written, the JSON is
    # still the old one and the two files still agree.
    json_text = json.dumps(breakdown, indent=2) + '\n'
    markdown_text = breakdown_report.breakdown_as_markdown(breakdown)
    try:
        (options.folder / 'breakdown.md').write_text(markdown_text)
        breakdown_path.write_text(json_text)
    except OSError as error:
        print(f'Could not write to {options.folder}: {error}', file=sys.stderr)
        return 1
    print(
        json.dumps({'layers_back_to_front': breakdown['layers_back_to_front']}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
