import os
import argparse
from tqdm import tqdm


def main():
    """
    Finds and deletes VIA JSON files from within their respective clip subdirectories
    after user confirmation.
    """
    parser = argparse.ArgumentParser(
        description="A safe script to delete generated VIA JSON files from their clip subdirectories before a rerun.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '--frame_dir',
        type=str,
        required=True,
        help="The root directory containing the frame subdirectories (e.g., '1_clip_000')."
    )
    args = parser.parse_args()

    if not os.path.isdir(args.frame_dir):
        print(f"❌ Error: Directory not found at '{args.frame_dir}'")
        return

    # --- Find all files matching the pattern by walking the directory tree ---
    files_to_delete = []
    print(f"Searching for '_via.json' files in '{args.frame_dir}'...")
    for root, dirs, files in os.walk(args.frame_dir):
        for filename in files:
            if filename.endswith('_via.json'):
                files_to_delete.append(os.path.join(root, filename))

    if not files_to_delete:
        print(f"✅ No '..._via.json' files found in any subdirectory. Nothing to do.")
        return

    # --- Safety Confirmation ---
    print("\n⚠️ The following files will be PERMANENTLY DELETED:")
    for file_path in files_to_delete:
        # Print a more readable relative path
        print(f"  - {os.path.relpath(file_path)}")

    try:
        confirm = input(f"\nAre you sure you want to delete these {len(files_to_delete)} files? (y/n): ")
    except KeyboardInterrupt:
        print("\n🚫 Operation cancelled by user.")
        return

    if confirm.lower() != 'y':
        print("🚫 Operation cancelled.")
        return

    # --- Deletion Process ---
    print("\nDeleting files...")
    deleted_count = 0
    for file_path in tqdm(files_to_delete, desc="Cleaning up"):
        try:
            os.remove(file_path)
            deleted_count += 1
        except OSError as e:
            print(f"\n❌ Error deleting {file_path}: {e}")

    print(f"\n🎉 Successfully deleted {deleted_count} file(s).")


if __name__ == "__main__":
    main()
