#!/usr/bin/env python3
"""Generate markdown keybinding tables from Binary Ninja keybinding JSON files
and update the migration guide documentation in-place.

Reads ida-keybindings.json and ghidra-keybindings.json, generates categorized
markdown tables, and replaces the existing keybinding tables in the
corresponding migration guide markdown files.
"""

import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Human-readable name overrides
# ---------------------------------------------------------------------------
# Explicit mappings from JSON action keys to short, readable names.
# Actions not listed here get a default cleanup (strip namespace prefix,
# trailing "...", trailing "\Default", etc.).

ACTION_DISPLAY_NAMES = {
    "Make Function at This Address\\Default": "Make Function",
    "Type\\Cycle Integer Size": "Cycle Integer Size",
    "Type\\Cycle Float Size": "Cycle Float Size",
    "Type\\Invert Integer Sign": "Invert Integer Sign",
    "Type\\Make C String": "Make C String",
    "Type\\Make Pointer": "Make Pointer",
    "Type\\Make Array": "Make Array",
    "Display as\\Unsigned Hexadecimal": "Display as Hex",
    "Display as\\Character Constant": "Display as Character",
    "Display as\\Enum Member": "Display as Enum",
    "Command Palette\\Search Actions...": "Command Palette",
    "Patch\\Convert to NOP": "Convert to NOP",
    "Patch\\Edit Current Line": "Edit Current Line (Patch)",
    "Project Browser\\Import Files...": "Import Files",
    "Project Browser\\Import Folder...": "Import Folder",
    "Show Cross References at Selection...": "Show Cross References",
    "Enter Comment...": "Enter Comment",
    "Change Type...": "Change Type",
    "Edit Function Properties...": "Edit Function Properties",
    "Go to Address...": "Go to Address",
    "Find...": "Find",
    "Find Next": "Find Next",
    "Rename...": "Rename",
    "Rename Type...": "Rename Type",
    "Add Tag...": "Add Tag",
    "Assemble...": "Assemble",
    "Import Header File...": "Import Header File",
    "Save Contents As...": "Save Contents As",
    "Open URL...": "Open URL",
    "Create Structure...": "Create Structure",
    "Undefine Type...": "Undefine Type",
    "New Binary Data": "New Binary Data",
    "New Project": "New Project",
    "New Window": "New Window",
}

# ---------------------------------------------------------------------------
# Category assignments
# ---------------------------------------------------------------------------
# Each action key is mapped to exactly one category.  Anything not listed
# here falls into "Other".

CATEGORY_ANALYSIS = "Analysis"
CATEGORY_NAVIGATION = "Navigation"
CATEGORY_TYPES = "Types"
CATEGORY_VIEWS = "Views & Panels"
CATEGORY_SEARCH = "Search"
CATEGORY_DEBUGGER = "Debugger"
CATEGORY_FILE = "File Operations"
CATEGORY_OTHER = "Other"

# Ordered so the output sections appear in a sensible sequence.
CATEGORY_ORDER = [
    CATEGORY_ANALYSIS,
    CATEGORY_NAVIGATION,
    CATEGORY_TYPES,
    CATEGORY_VIEWS,
    CATEGORY_SEARCH,
    CATEGORY_DEBUGGER,
    CATEGORY_FILE,
    CATEGORY_OTHER,
]

ACTION_CATEGORIES = {
    # Analysis
    "Rename...": CATEGORY_ANALYSIS,
    "Rename Type...": CATEGORY_ANALYSIS,
    "Change Type...": CATEGORY_ANALYSIS,
    "Make Function at This Address\\Default": CATEGORY_ANALYSIS,
    "Undefine": CATEGORY_ANALYSIS,
    "Undefine Type...": CATEGORY_ANALYSIS,
    "Enter Comment...": CATEGORY_ANALYSIS,
    "Edit Function Properties...": CATEGORY_ANALYSIS,
    "Show Cross References at Selection...": CATEGORY_ANALYSIS,
    "Pin Cross References": CATEGORY_ANALYSIS,
    "Focus Cross References": CATEGORY_ANALYSIS,
    "Add Bookmark": CATEGORY_ANALYSIS,
    "Add Tag...": CATEGORY_ANALYSIS,
    "Assemble...": CATEGORY_ANALYSIS,
    "Patch\\Convert to NOP": CATEGORY_ANALYSIS,
    "Patch\\Edit Current Line": CATEGORY_ANALYSIS,
    "Copy Address": CATEGORY_ANALYSIS,
    "Create Structure...": CATEGORY_ANALYSIS,
    "Undo": CATEGORY_ANALYSIS,
    "Redo": CATEGORY_ANALYSIS,

    # Navigation
    "Go to Address...": CATEGORY_NAVIGATION,
    "Go to Entry Point": CATEGORY_NAVIGATION,
    "Navigate Back": CATEGORY_NAVIGATION,
    "Navigate Forward": CATEGORY_NAVIGATION,
    "Navigate to Selection": CATEGORY_NAVIGATION,

    # Types
    "Type\\Cycle Integer Size": CATEGORY_TYPES,
    "Type\\Cycle Float Size": CATEGORY_TYPES,
    "Type\\Invert Integer Sign": CATEGORY_TYPES,
    "Type\\Make C String": CATEGORY_TYPES,
    "Type\\Make Pointer": CATEGORY_TYPES,
    "Type\\Make Array": CATEGORY_TYPES,
    "Display as\\Unsigned Hexadecimal": CATEGORY_TYPES,
    "Display as\\Character Constant": CATEGORY_TYPES,
    "Display as\\Enum Member": CATEGORY_TYPES,

    # Views & Panels
    "Focus Symbols": CATEGORY_VIEWS,
    "Focus Types": CATEGORY_VIEWS,
    "Focus Strings": CATEGORY_VIEWS,
    "Focus Log": CATEGORY_VIEWS,
    "Focus Tags": CATEGORY_VIEWS,
    "Focus Memory Map": CATEGORY_VIEWS,
    "Focus Stack Trace": CATEGORY_VIEWS,
    "Toggle Decompiled View": CATEGORY_VIEWS,
    "Toggle Disassembly View": CATEGORY_VIEWS,
    "View in Graph": CATEGORY_VIEWS,
    "View in Linear Disassembly": CATEGORY_VIEWS,
    "View in Hex Editor": CATEGORY_VIEWS,
    "Zoom to Fit": CATEGORY_VIEWS,
    "Keybindings": CATEGORY_VIEWS,

    # Search
    "Find...": CATEGORY_SEARCH,
    "Find Next": CATEGORY_SEARCH,
    "Command Palette\\Search Actions...": CATEGORY_SEARCH,

    # Debugger
    "Step Into": CATEGORY_DEBUGGER,
    "Step Over": CATEGORY_DEBUGGER,
    "Step Return": CATEGORY_DEBUGGER,
    "Resume": CATEGORY_DEBUGGER,
    "Toggle Breakpoint": CATEGORY_DEBUGGER,
    "Run To Here": CATEGORY_DEBUGGER,
    "Kill": CATEGORY_DEBUGGER,

    # File Operations
    "Close Pane": CATEGORY_FILE,
    "Close Tab": CATEGORY_FILE,
    "Save Contents As...": CATEGORY_FILE,
    "Import Header File...": CATEGORY_FILE,
    "Project Browser\\Import Files...": CATEGORY_FILE,
    "Project Browser\\Import Folder...": CATEGORY_FILE,
    "Open URL...": CATEGORY_FILE,
    "New Binary Data": CATEGORY_FILE,
    "New Project": CATEGORY_FILE,
    "New Window": CATEGORY_FILE,
}

# Sentinel comments used to delimit the auto-generated keybinding tables
# inside the migration guide markdown files.
MARKER_BEGIN = "<!-- BEGIN GENERATED KEYBINDING TABLES -->"
MARKER_END = "<!-- END GENERATED KEYBINDING TABLES -->"


def clean_action_name(raw_name):
    """Derive a human-readable action name from a raw JSON key."""
    if raw_name in ACTION_DISPLAY_NAMES:
        return ACTION_DISPLAY_NAMES[raw_name]

    name = raw_name
    # Strip trailing \Default
    if name.endswith("\\Default"):
        name = name[: name.rfind("\\Default")]
    # Strip namespace prefix (everything before last backslash)
    if "\\" in name:
        name = name.split("\\")[-1]
    # Strip trailing ellipsis
    name = name.rstrip(".")
    # Strip trailing whitespace
    name = name.strip()
    return name


def format_shortcut(shortcut):
    """Format a shortcut string for display in markdown.

    Converts "Ctrl+" prefixed shortcuts to "Ctrl/Cmd+" to indicate
    cross-platform behaviour.
    """
    if not shortcut:
        return shortcut
    parts = shortcut.split("+")
    formatted_parts = []
    for part in parts:
        if part == "Ctrl":
            formatted_parts.append("Ctrl/Cmd")
        else:
            formatted_parts.append(part)
    return "+".join(formatted_parts)


def get_category(action_key):
    """Return the category string for an action key."""
    return ACTION_CATEGORIES.get(action_key, CATEGORY_OTHER)


def generate_tables(bindings):
    """Generate categorized markdown tables from a keybindings dict.

    Parameters
    ----------
    bindings : dict
        Mapping of action key -> shortcut string (from JSON).

    Returns
    -------
    str
        Markdown text containing only the category headings and tables
        (no document title or introduction).
    """
    # Bucket actions into categories, skipping empty shortcuts.
    categorized = {cat: [] for cat in CATEGORY_ORDER}
    for action_key, shortcut in sorted(bindings.items()):
        if not shortcut:
            continue
        cat = get_category(action_key)
        display_name = clean_action_name(action_key)
        display_shortcut = format_shortcut(shortcut)
        categorized[cat].append((display_name, display_shortcut))

    lines = []
    first = True
    for cat in CATEGORY_ORDER:
        entries = categorized[cat]
        if not entries:
            continue

        if not first:
            lines.append("")
        first = False

        lines.append(f"{cat} Keybindings:")
        lines.append("")
        lines.append("| Action | Shortcut |")
        lines.append("| --- | --- |")
        for display_name, display_shortcut in entries:
            lines.append(f"| {display_name} | `{display_shortcut}` |")

    return "\n".join(lines)


def replace_tables_in_file(md_path, tables_md, dry_run=False):
    """Replace the keybinding tables in an existing markdown file.

    The function looks for the sentinel markers MARKER_BEGIN / MARKER_END.
    If found, the content between them is replaced.

    If the markers are not present, the function falls back to a
    heuristic: it finds the keybinding section header ("## Keybindings")
    and replaces everything between the last prose paragraph in that
    section and the next "## " heading with the generated tables,
    wrapping them in sentinel markers for future runs.

    Returns True if the file was modified, False otherwise.
    """
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # --- Strategy 1: sentinel markers already present ---
    if MARKER_BEGIN in content and MARKER_END in content:
        before = content[: content.index(MARKER_BEGIN) + len(MARKER_BEGIN)]
        after = content[content.index(MARKER_END) :]
        new_content = before + "\n" + tables_md + "\n" + after
        if new_content != content:
            if not dry_run:
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
            return True
        return False

    # --- Strategy 2: heuristic replacement ---
    # Find the ## Keybindings section.
    kb_match = re.search(r"^## Keybindings\s*$", content, re.MULTILINE)
    if not kb_match:
        print(f"Warning: no '## Keybindings' section found in {md_path}",
              file=sys.stderr)
        return False

    # Find the next ## heading after the keybindings section.
    next_section = re.search(r"^## ", content[kb_match.end():], re.MULTILINE)
    if next_section:
        section_end = kb_match.end() + next_section.start()
    else:
        section_end = len(content)

    # Within the keybinding section, find where the prose ends and the
    # tables / bullet lists begin.  We look for the first line that is
    # either a table row, a bullet list item describing keybindings, or
    # a sub-heading like "Analysis Keybindings:".
    section_text = content[kb_match.end():section_end]
    # Find the first line that starts a table, a bullet list entry with
    # keybinding info, or a category label ending with "Keybindings:".
    table_start_pattern = re.compile(
        r"^(?:\||\- |[A-Z][\w &]+ Keybindings:)", re.MULTILINE
    )
    table_match = table_start_pattern.search(section_text)

    if not table_match:
        # No existing tables found; insert right before the next section.
        insert_pos = section_end
        # Walk backwards to skip trailing blank lines.
        while insert_pos > kb_match.end() and content[insert_pos - 1] == "\n":
            insert_pos -= 1
        prefix = content[:insert_pos]
        suffix = content[section_end:]
        new_content = (
            prefix + "\n\n"
            + MARKER_BEGIN + "\n"
            + tables_md + "\n"
            + MARKER_END + "\n\n"
            + suffix
        )
    else:
        # Replace from the start of the first table/list to the end of
        # the section (exclusive of the next ## heading).
        replace_start = kb_match.end() + table_match.start()
        # Walk backwards from section_end to trim trailing blank lines.
        replace_end = section_end
        while replace_end > replace_start and content[replace_end - 1] == "\n":
            replace_end -= 1

        prefix = content[:replace_start]
        suffix = content[replace_end:]
        new_content = (
            prefix
            + MARKER_BEGIN + "\n"
            + tables_md + "\n"
            + MARKER_END
            + suffix
        )

    if new_content != content:
        if not dry_run:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Generate markdown keybinding tables from Binary Ninja "
        "keybinding JSON files and update migration guides in-place."
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Path to the repository root. Defaults to the script's "
        "grandparent directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be changed without writing files.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print generated tables to stdout instead of updating files.",
    )
    args = parser.parse_args()

    if args.repo_root:
        repo_root = os.path.abspath(args.repo_root)
    else:
        # Default: script lives at <repo>/api/scripts/generate_keybinding_docs.py
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    json_dir = os.path.join(repo_root, "api", "docs", "files")

    # (json filename, tool name, path to migration guide markdown)
    sources = [
        (
            "ida-keybindings.json",
            "IDA",
            os.path.join(repo_root, "api", "docs", "guide", "migration",
                         "migrationguideida.md"),
        ),
        (
            "ghidra-keybindings.json",
            "Ghidra",
            os.path.join(repo_root, "api", "docs", "guide", "migration",
                         "ghidra", "index.md"),
        ),
    ]

    for json_name, tool_name, md_path in sources:
        json_path = os.path.join(json_dir, json_name)
        if not os.path.isfile(json_path):
            print(f"Warning: {json_path} not found, skipping.",
                  file=sys.stderr)
            continue

        with open(json_path, "r", encoding="utf-8") as f:
            bindings = json.load(f)

        tables_md = generate_tables(bindings)

        if args.stdout:
            print(f"=== {tool_name} keybinding tables ===")
            print(tables_md)
            print()
            continue

        if not os.path.isfile(md_path):
            print(f"Warning: {md_path} not found, skipping.",
                  file=sys.stderr)
            continue

        changed = replace_tables_in_file(md_path, tables_md,
                                         dry_run=args.dry_run)
        if changed:
            verb = "Would update" if args.dry_run else "Updated"
            print(f"{verb} {md_path}", file=sys.stderr)
        else:
            print(f"No changes needed for {md_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
