import os
import re
import subprocess
import argparse


EXCLUDED_DIRS = {"update-progress"}

REFERENCE_PATTERNS = [
    r"!\[.*?\]\((.*?)\)",  # markdown ![alt](url)
    r"""<img[^>]*\bsrc=["']([^"']+)["']""",  # html <img src="...">
]


def find_image_references(md_file):
    """Find all image references in a markdown file (markdown + HTML syntax)."""
    with open(md_file, "r", encoding="utf-8") as f:
        content = f.read()

    cleaned_paths = []
    for pattern in REFERENCE_PATTERNS:
        for match in re.findall(pattern, content):
            path = match.lstrip("/")
            if "img/" in path:
                cleaned_paths.append(path[path.index("img/") + 4 :])

    return cleaned_paths


def scan_markdown_files(docs_dir, project_root):
    """Recursively scan markdown files in docs_dir, plus root-level *.md files."""
    md_files = []
    for root, dirs, files in os.walk(docs_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for file in files:
            if file.endswith(".md"):
                md_files.append(os.path.join(root, file))
    for file in os.listdir(project_root):
        full_path = os.path.join(project_root, file)
        if file.endswith(".md") and os.path.isfile(full_path):
            md_files.append(full_path)
    return md_files


def find_img_dirs(docs_dir):
    """Yield every directory named 'img' under docs_dir, excluding EXCLUDED_DIRS."""
    for root, dirs, _ in os.walk(docs_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for d in dirs:
            if d == "img":
                yield os.path.join(root, d)


def find_all_images(img_dir):
    """Yield (img_dir, rel_path) for every image under img_dir."""
    for root, _, files in os.walk(img_dir):
        for file in files:
            if file.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg")):
                rel_path = os.path.relpath(os.path.join(root, file), img_dir)
                yield (img_dir, rel_path)


def grep_check_image(docs_dir, image_path):
    """
    Check if an image is referenced anywhere using grep.
    Returns True if any reference is found, False otherwise.
    """
    try:
        # Build a pattern that requires each path segment in order with any
        # separator between them — works for both versioned (0.37.0/foo.png)
        # and flat (subdir/foo.png) images.
        parts = os.path.normpath(image_path).split(os.sep)
        pattern = ".*".join(parts)
        try:
            exclude_args = [f"--exclude-dir={d}" for d in EXCLUDED_DIRS]
            result = subprocess.run(
                ["grep", "-r", "-l", *exclude_args, pattern, docs_dir],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                print(f"Found reference to {image_path} with pattern: {pattern}")
                return True
        except subprocess.CalledProcessError:
            pass

    except Exception as e:
        print(f"Error during grep check for {image_path}: {e}")

    return False


def main():
    parser = argparse.ArgumentParser(
        description="Find and optionally delete unused images in the MkDocs project"
    )
    parser.add_argument("--delete", action="store_true", help="Delete unused images")
    parser.add_argument(
        "--verbose", action="store_true", help="Show all found references and files"
    )
    parser.add_argument(
        "--skip-grep", action="store_true", help="Skip the additional grep validation"
    )
    args = parser.parse_args()

    docs_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(docs_dir)
    img_dirs = list(find_img_dirs(docs_dir))

    print(f"Scanning markdown files in: {docs_dir} (+ root-level *.md)")
    print(f"Found {len(img_dirs)} img directories:")
    for d in img_dirs:
        print(f"  - {os.path.relpath(d, project_root)}")

    # Get all markdown files
    md_files = scan_markdown_files(docs_dir, project_root)
    print(f"Found {len(md_files)} markdown files")

    # Collect all image references
    used_images = set()
    for md_file in md_files:
        refs = find_image_references(md_file)
        used_images.update(refs)

    # Collect every physical image across every img dir
    all_image_entries = [
        entry for img_dir in img_dirs for entry in find_all_images(img_dir)
    ]

    if args.verbose:
        print("\nAll image references found in markdown:")
        for img in sorted(used_images):
            print(f"- {img}")

        print("\nAll images on disk:")
        for img_dir, rel_path in sorted(all_image_entries):
            print(f"- {os.path.relpath(os.path.join(img_dir, rel_path), project_root)}")

    # Find potentially unused images
    unused_entries = [
        (img_dir, rel_path)
        for img_dir, rel_path in all_image_entries
        if rel_path not in used_images
    ]

    # Additional grep validation if not skipped
    if not args.skip_grep and unused_entries:
        print("\nPerforming additional grep validation...")
        actually_unused = [
            (img_dir, rel_path)
            for img_dir, rel_path in unused_entries
            if not grep_check_image(docs_dir, rel_path)
        ]

        if len(actually_unused) != len(unused_entries):
            print(
                f"\nGrep validation found {len(unused_entries) - len(actually_unused)} additional image references!"
            )
        unused_entries = actually_unused

    # Report findings
    print("\nResults:")
    print(f"Total images found: {len(all_image_entries)}")
    print(f"Images referenced in markdown: {len(used_images)}")
    print(f"Unused images: {len(unused_entries)}")

    if unused_entries:
        print("\nUnused images:")
        for img_dir, rel_path in sorted(unused_entries):
            print(f"- {os.path.relpath(os.path.join(img_dir, rel_path), project_root)}")

        if args.delete:
            print("\nDeleting unused images...")
            for img_dir, rel_path in unused_entries:
                full_path = os.path.join(img_dir, rel_path)
                try:
                    os.remove(full_path)
                    print(f"Deleted: {os.path.relpath(full_path, project_root)}")
                except Exception as e:
                    print(f"Error deleting {full_path}: {e}")
            print("\nDeletion complete")
    else:
        print("\nNo unused images found!")


if __name__ == "__main__":
    main()
