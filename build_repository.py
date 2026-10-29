#!/usr/bin/env python3
"""Build Aurora's Kodi repository feed and installable add-on archives."""
from __future__ import annotations

import argparse
import hashlib
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
ADDONS = ROOT / "addons"
PLUGIN_ID = "plugin.video.netflix.aurora"
PLUGIN_VERSION = "0.4.0"
REPO_ID = "repository.aurora"
REPO_VERSION = "1.0.0"


def archive_addon(addon_dir: Path, version: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{addon_dir.name}-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(addon_dir.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                zf.write(path, Path(addon_dir.name) / path.relative_to(addon_dir))
    return archive


def repo_index(base_url: str, repo_id: str, repo_version: str, repo_dir: Path) -> None:
    packages = [
        (PLUGIN_ID, PLUGIN_VERSION, ROOT / PLUGIN_ID, f"{PLUGIN_ID}/{PLUGIN_ID}-{PLUGIN_VERSION}.zip"),
        (repo_id, repo_version, repo_dir, f"{repo_id}/{repo_id}-{repo_version}.zip"),
    ]
    root = ET.Element("addons")
    for addon_id, version, source_dir, relative_zip in packages:
        addon_xml = ET.parse(source_dir / "addon.xml").getroot()
        addon_xml.set("version", version)
        ET.SubElement(addon_xml, "zip", url=f"{base_url}/addons/{relative_zip}")
        root.append(addon_xml)
    ET.indent(root, space="  ")
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    (ROOT / "addons.xml").write_bytes(xml_bytes + b"\n")
    (ROOT / "addons.xml.md5").write_text(hashlib.md5(xml_bytes + b"\n").hexdigest() + "\n", encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="Public URL serving this repository root")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if not base.startswith("https://"):
        raise SystemExit("--base-url must use HTTPS")
    repo_id = REPO_ID
    repo_version = REPO_VERSION
    repo_dir = ROOT / REPO_ID
    plugin_dir = ROOT / PLUGIN_ID
    repo_zip = archive_addon(repo_dir, repo_version, ADDONS / repo_id)
    archive_addon(plugin_dir, PLUGIN_VERSION, ADDONS / PLUGIN_ID)
    repo_index(base, repo_id, repo_version, repo_dir)
    print(f"Repository bootstrap archive: {repo_zip.relative_to(ROOT)}")
    print(f"Feed URL: {base}/addons.xml")


if __name__ == "__main__":
    main()
