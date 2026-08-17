#!/usr/bin/env python3

import argparse
import base64
import getpass
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


API_URL = "https://war.app/API/UpdateMod"
API_TOKEN_HELP = "https://war.app/API/GetAPIToken"
MOD_ID_HELP = "https://war.app/Mods/Develop"
POLL_INTERVAL = 1.0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Upload and continuously update a war.app mod."
    )

    parser.add_argument(
        "folder",
        nargs="?",
        default=None,
        help="Folder containing the mod files "
             "(defaults to the current working directory).",
    )

    parser.add_argument(
        "--email",
        help="war.app account email address.",
    )

    parser.add_argument(
        "--api-token",
        help="war.app API token.",
    )

    parser.add_argument(
        "--mod-id",
        help="war.app mod ID.",
    )

    return parser.parse_args()


def get_configuration(args):
    folder = Path(
        args.folder or os.getcwd()
    ).expanduser().resolve()

    if not folder.is_dir():
        print(
            f"Error: folder does not exist or is not a directory: "
            f"{folder}"
        )
        sys.exit(1)

    print(f"Using folder: {folder}")

    email = args.email

    if not email:
        email = input(
            "war.app account email address: "
        ).strip()

    if not email:
        print("Error: an account email address is required.")
        sys.exit(1)

    api_token = args.api_token

    if not api_token:
        print(
            f"You can get your API token at: "
            f"{API_TOKEN_HELP}"
        )

        api_token = getpass.getpass(
            "war.app account API token: "
        ).strip()

    if not api_token:
        print("Error: an API token is required.")
        sys.exit(1)

    mod_id = args.mod_id

    if not mod_id:
        print(
            "You can get your mod ID in the mod development "
            f"console at: {MOD_ID_HELP}"
        )

        mod_id = input(
            "war.app mod ID: "
        ).strip()

    if not mod_id:
        print("Error: a mod ID is required.")
        sys.exit(1)

    return folder, email, api_token, mod_id


def get_file_snapshot(folder):
    """
    Create a snapshot of the files currently contained in the mod folder.

    The snapshot maps each relative path to its modification time and size.

    This allows us to detect:
      - modified files
      - newly created files
      - deleted files
    """
    snapshot = {}

    for path in folder.rglob("*"):
        try:
            if not path.is_file():
                continue

            # Don't follow symlinks.
            if path.is_symlink():
                continue

            relative_path = path.relative_to(folder).as_posix()

            stat = path.stat()

            snapshot[relative_path] = (
                stat.st_mtime_ns,
                stat.st_size,
            )

        except (OSError, PermissionError):
            # The file may have disappeared between rglob() and stat().
            continue

    return snapshot


def read_files(folder):
    """
    Read every file in the mod directory recursively.

    Files are base64 encoded so both text and binary files can be uploaded.
    """
    files = []

    for path in sorted(
        folder.rglob("*"),
        key=lambda p: p.as_posix(),
    ):
        if not path.is_file():
            continue

        if path.is_symlink():
            continue

        relative_path = path.relative_to(folder).as_posix()

        try:
            data = path.read_bytes()
        except OSError as exc:
            raise RuntimeError(
                f"Could not read '{relative_path}': {exc}"
            ) from exc

        content = base64.b64encode(data).decode("ascii")

        files.append({
            "path": relative_path,
            "content": content,
        })

    return files




def upload_mod(folder, api_token, mod_id):
    """
    Upload the entire current contents of the mod folder.
    """
    print("Reading mod files...")

    files = read_files(folder)

    # Build the complete JSON request body in memory.
    json_data = json.dumps(
        {
            "files": files,
        },
        separators=(",", ":"),
    ).encode("utf-8")

    print(
        f"Preparing {len(files)} file(s), "
        f"JSON size: {len(json_data):,} bytes..."
    )

    query = urllib.parse.urlencode({
        "ModID": mod_id,
        "APIToken": api_token,
    })

    url = (
        f"{API_URL}"
        f"?{query}"
    )

    request = urllib.request.Request(
        url,
        data=json_data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "war-app-mod-updater/1.0",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=60,
        ) as response:

            response_body = response.read().decode(
                "utf-8",
                errors="replace",
            )

            print(
                f"Upload successful: "
                f"{len(files)} file(s), "
                f"HTTP {response.status}"
            )

            if response_body:
                print(
                    f"API response: {response_body}"
                )

    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            f"war.app API returned HTTP {exc.code}: {body}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not connect to war.app: {exc.reason}"
        ) from exc


def watch_folder(folder, api_token, mod_id):
    """
    Monitor the folder for changes.

    Whenever the contents change, upload the entire mod again.
    """
    previous_snapshot = get_file_snapshot(folder)

    while True:
        time.sleep(POLL_INTERVAL)

        current_snapshot = get_file_snapshot(folder)

        if current_snapshot != previous_snapshot:
            print(
                "\nChange detected. Uploading mod..."
            )

            try:
                upload_mod(
                    folder,
                    api_token,
                    mod_id,
                )

                # Only consider the change handled after a
                # successful upload.
                previous_snapshot = current_snapshot

            except Exception as exc:
                print(
                    f"Upload failed: {exc}"
                )

                print(
                    "The change will be retried."
                )


def main():
    args = parse_args()

    folder, email, api_token, mod_id = (
        get_configuration(args)
    )

    # The documented UpdateMod endpoint does not have an
    # email parameter. We collect the email as requested,
    # but the API request uses ModID and APIToken.
    _ = email

    print("\nUploading mod...")

    try:
        upload_mod(
            folder,
            api_token,
            mod_id,
        )

    except Exception as exc:
        print(
            f"Initial upload failed: {exc}"
        )
        sys.exit(1)

    print(
        f"\nMonitoring {folder} for changes..."
    )

    print(
        "Press Ctrl+C to stop."
    )

    try:
        watch_folder(
            folder,
            api_token,
            mod_id,
        )

    except KeyboardInterrupt:
        print("\nStopped.")

    except Exception as exc:
        print(
            f"\nFatal error: {exc}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
