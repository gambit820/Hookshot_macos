"""Pack a shareable copy of the macOS builder. The window is the Swift app, Hookshot.app, not this file.

    python -I builder/macos/hookshot_builder.py --package dist/Hookshot-mac

A shared copy is the builder only. Game files are refused.
"""
import os
import shlex
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# (a 16 GB Mac loses the device at the game's own default; 9400 still holds the 2.4 GB pool. Larger Macs keep the default)
APPLE_MEMORY_MB = "9400"
APPLE_MEMORY_LIMIT = 18 * 1024 ** 3
VMA_MARK = b"AMD_VULKAN_MEMORY_ALLOCATOR_H"
BLOCK_DIRS = {
    ".git", "work", "gen", "image", "exefs", "romfs", "dist", "build", "build-linux", "ngx-sdk", "user",
    "__pycache__", ".cache",
}
BLOCK_SUFFIXES = (".nup", ".nso", ".nca", ".nsp", ".xci", ".nsz", ".xcz", ".keys", ".bin", ".env")
BLOCK_NAMES = {
    "hookshot", "hookshot.exe", "hookshot_vk.dylib", "hookshot_vk.so", "hookshot_vk.dll", "image.bin",
    "hookshot_log.txt",
}
SHARE_FILE_LIMIT = 80 * 1024 * 1024


def share_blocked(rel):
    """A path that must not leave this PC: the game, anything made from it, or the builder's own work folder."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p in BLOCK_DIRS for p in parts):
        return True
    base = parts[-1] if parts else ""
    if base in BLOCK_NAMES or base.startswith("hookshot_log"):
        return True
    return base.endswith(BLOCK_SUFFIXES)


def apple_play_env(environ, size, prefix):
    """What a launch on this Mac adds. A value the caller already set is left as it is.
    The Mac app repeats this in builder/macos/Sources/BuilderModel.swift."""
    env = {}
    icd = os.path.join(prefix, "etc", "vulkan", "icd.d", "MoltenVK_icd.json")
    if os.path.isfile(icd) and not environ.get("VK_DRIVER_FILES") and not environ.get("VK_ICD_FILENAMES"):
        env["VK_DRIVER_FILES"] = icd
    lib = os.path.join(prefix, "lib")
    if os.path.isdir(lib):
        current = environ.get("DYLD_LIBRARY_PATH", "")
        if lib not in current.split(":"):
            env["DYLD_LIBRARY_PATH"] = lib + ((":" + current) if current else "")
    if not environ.get("MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS"):
        env["MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS"] = "1"
    if size and size <= APPLE_MEMORY_LIMIT and not environ.get("HOS_MEMORY_MB"):
        env["HOS_MEMORY_MB"] = APPLE_MEMORY_MB
    return env


def game_launcher_script(exe_rel, extra):
    """The game folder's Hookshot.app: it starts the game built beside it, with MoltenVK found."""
    lines = ["#!/bin/bash", "set -eu", 'cd "$(dirname "$0")/../../.."']
    for key, value in extra.items():
        lines.append("export %s=%s" % (key, shlex.quote(str(value))))
    lines.append("exec %s" % shlex.quote(exe_rel))
    return "\n".join(lines) + "\n"


def _copy_file(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def copy_share(src, dest):
    """The source tree into dest/source, then the app beside it. Game files, work/, and links are left out.
    The VMA header is the one exception from work/: it is AMD's allocator, and the build needs it."""
    source = os.path.join(dest, "source")
    os.makedirs(source, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(src):
        rel_dir = os.path.relpath(dirpath, src)
        if rel_dir == ".":
            rel_dir = ""
        kept = []
        for name in dirnames:
            rel = os.path.join(rel_dir, name) if rel_dir else name
            if os.path.islink(os.path.join(dirpath, name)) or share_blocked(rel):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            rel = os.path.join(rel_dir, name) if rel_dir else name
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or share_blocked(rel):
                continue
            if os.path.getsize(path) > SHARE_FILE_LIMIT:
                raise SystemExit("refusing a file over 80 MB (%s)" % rel)
            _copy_file(path, os.path.join(source, rel))
    vma = os.path.join(src, "work", "vma", "include", "vk_mem_alloc.h")
    if os.path.isfile(vma):
        with open(vma, "rb") as f:
            head = f.read(4096)
        if VMA_MARK not in head or b"Permission is hereby granted" not in head:
            raise SystemExit("work/vma/include/vk_mem_alloc.h is not AMD's Vulkan Memory Allocator header")
        _copy_file(vma, os.path.join(source, "third_party", "vma", "include", "vk_mem_alloc.h"))
    app_src = os.path.join(src, "builder", "macos", "Hookshot.app")
    app_dst = os.path.join(dest, "Hookshot.app")
    if os.path.isdir(app_src):
        shutil.copytree(app_src, app_dst, dirs_exist_ok=True, symlinks=False)
        script = os.path.join(app_dst, "Contents", "MacOS", "hookshot-builder")
        if os.path.isfile(script):
            os.chmod(script, 0o755)
        subprocess.run(["/usr/bin/codesign", "-s", "-", "--force", app_dst], capture_output=True)
    readme = os.path.join(src, "builder", "macos", "README.txt")
    if os.path.isfile(readme):
        _copy_file(readme, os.path.join(dest, "README.txt"))
    _assert_share_clean(dest)
    return dest


def _assert_share_clean(dest):
    source = os.path.join(dest, "source")
    for dirpath, dirnames, filenames in os.walk(source):
        for name in dirnames + filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), source)
            if rel.endswith("vk_mem_alloc.h"):
                with open(os.path.join(dirpath, name), "rb") as header:
                    if VMA_MARK in header.read(4096):
                        continue
            if share_blocked(rel):
                raise SystemExit("refusing to share %s" % rel)


def package(dest):
    dest = os.path.abspath(dest)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    copy_share(ROOT, dest)
    archive = dest + ".zip"
    if os.path.exists(archive):
        os.remove(archive)
    subprocess.run(["/usr/bin/ditto", "-c", "-k", "--keepParent", dest, archive], check=True)
    print(archive, flush=True)
    return archive


def main(argv):
    """The window is builder/macos/Hookshot.app. This command only packs a copy of the builder to share."""
    if "--package" in argv:
        index = argv.index("--package")
        if index + 1 >= len(argv):
            print("needs a folder after --package", file=sys.stderr)
            return 2
        package(argv[index + 1])
        return 0
    print("Open builder/macos/Hookshot.app", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
