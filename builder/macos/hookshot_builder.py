"""Hookshot Builder for macOS. The window asks for your own .nup, then runs nx2/make_game.py and starts the game with
MoltenVK on the path. A shared copy is this builder only: --package writes a folder you can hand to someone else, and
refuses game files.

    python -I builder/macos/hookshot_builder.py
    python -I builder/macos/hookshot_builder.py --nup game.nup
    python -I builder/macos/hookshot_builder.py --package dist/Hookshot-mac
"""
import os
import queue
import shlex
import shutil
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CONFIG = os.path.join(os.path.expanduser("~/Library/Application Support"), "Hookshot", "builder.ini")
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


def load_config():
    cfg = {}
    try:
        for line in open(CONFIG, encoding="utf-8"):
            key, eq, value = line.rstrip("\n").partition("=")
            if eq:
                cfg[key] = value
    except OSError:
        pass
    return cfg


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        f.writelines("%s=%s\n" % kv for kv in cfg.items())


def brew_prefix():
    for prefix in ("/opt/homebrew", "/usr/local"):
        if os.path.isdir(os.path.join(prefix, "lib")):
            return prefix
    return "/opt/homebrew"


def memsize():
    try:
        out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2)
        return int(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def apple_play_env(environ, size, prefix):
    """What a launch on this Mac adds. A value the caller already set is left as it is."""
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


def game_exe(folder):
    for rel in ("hookshot", os.path.join("bin", "hookshot")):
        path = os.path.join(folder, rel)
        if os.path.isfile(path) and os.access(path, os.X_OK) and os.path.isfile(os.path.join(folder, "image.bin")):
            return path
    return None


def game_launcher_script(exe_rel, extra):
    """The game folder's Hookshot.app: it starts the game built beside it, with MoltenVK found."""
    lines = ["#!/bin/bash", "set -eu", 'cd "$(dirname "$0")/../../.."']
    for key, value in extra.items():
        lines.append("export %s=%s" % (key, shlex.quote(str(value))))
    lines.append("exec %s" % shlex.quote(exe_rel))
    return "\n".join(lines) + "\n"


def write_game_app(folder, extra):
    exe = game_exe(folder)
    if not exe:
        return None
    rel = os.path.relpath(exe, folder)
    app = os.path.join(folder, "Hookshot.app")
    mac = os.path.join(app, "Contents", "MacOS")
    os.makedirs(mac, exist_ok=True)
    plist = os.path.join(HERE, "Hookshot.app", "Contents", "Info.plist")
    dest_plist = os.path.join(app, "Contents", "Info.plist")
    if os.path.isfile(plist):
        text = open(plist, encoding="utf-8").read().replace("hookshot-builder", "play").replace(
            "Hookshot Builder", "Hookshot")
        with open(dest_plist, "w", encoding="utf-8") as f:
            f.write(text)
    script = os.path.join(mac, "play")
    with open(script, "w", encoding="utf-8") as f:
        f.write(game_launcher_script("./" + rel if not rel.startswith(".") else rel, extra))
    os.chmod(script, 0o755)
    subprocess.run(["/usr/bin/codesign", "-s", "-", "--force", app], capture_output=True)
    return app


def existing_build_python(root):
    """A Python that already has the build's packages, or None. Opening the window does not install any."""
    candidates = []
    forced = os.environ.get("HOOKSHOT_PYTHON")
    if forced:
        candidates.append(forced)
    candidates.append(os.path.join(root, "work", "py", "bin", "python3"))
    candidates.append(os.path.join(os.path.expanduser("~/.cache"), "hookshot-builder", "py", "bin", "python3"))
    for path in candidates:
        if path and os.path.isfile(path) and _imports(path, "zstandard"):
            return path
    return None


def build_python(root):
    """A Python that has the build's packages. This checkout's work/py is used when it has them; a shared folder makes
    one under ~/.cache/hookshot-builder the first time Build is pressed."""
    found = existing_build_python(root)
    if found:
        return found
    cache = os.path.join(os.path.expanduser("~/.cache"), "hookshot-builder", "py", "bin", "python3")
    host = _python_for_venv()
    if not host:
        return None
    os.makedirs(os.path.dirname(os.path.dirname(cache)), exist_ok=True)
    subprocess.run([host, "-m", "venv", os.path.dirname(os.path.dirname(cache))], check=True)
    subprocess.run([cache, "-m", "pip", "install", "-r", os.path.join(root, "requirements.txt")], check=True)
    return cache if _imports(cache, "zstandard") else None


def _imports(python, module):
    try:
        return subprocess.run([python, "-c", "import " + module], capture_output=True).returncode == 0
    except OSError:
        return False


def _python_for_venv():
    for path in ("/opt/homebrew/bin/python3.13", "/opt/homebrew/bin/python3.12", "/usr/local/bin/python3.13",
                 "/opt/homebrew/bin/python3", "/usr/local/bin/python3"):
        if not os.path.isfile(path):
            continue
        try:
            out = subprocess.run([path, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                                 capture_output=True, text=True, timeout=5)
            major, minor = (int(x) for x in out.stdout.split())
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        if (major, minor) >= (3, 11):
            return path
    return None


def build_command(python, root, nup, out, language):
    return [python, "-I", "-u", "-X", "utf8", os.path.join(root, "nx2", "make_game.py"),
            "--nup", nup, "--out", out, "--language", language]


def header_env(root, environ):
    """VMA is not in Homebrew's include. A checkout keeps the header under work/vma; a shared folder under third_party/vma."""
    env = dict(environ)
    if env.get("HOOKSHOT_VMA_HEADERS"):
        return env
    for rel in (os.path.join("work", "vma"), os.path.join("third_party", "vma")):
        root_dir = os.path.join(root, rel)
        if os.path.isfile(os.path.join(root_dir, "include", "vk_mem_alloc.h")):
            env["HOOKSHOT_VMA_HEADERS"] = root_dir
            break
    return env


def nup_from_argv(argv):
    for arg in argv:
        if arg.startswith("-psn"):
            continue
        if arg.lower().endswith(".nup") and os.path.isfile(arg):
            return os.path.abspath(arg)
    return None


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


def run_gui(initial_nup=None):
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    sys.path.insert(0, os.path.join(ROOT, "nx2"))
    import make_game

    class Builder(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Hookshot Builder")
            self.minsize(640, 480)
            self.cfg = load_config()
            self.proc = None
            self.lines = queue.Queue()
            self.nup = tk.StringVar(value=initial_nup or self.cfg.get("nup", ""))
            self.out = tk.StringVar(value=self.cfg.get("out", os.path.expanduser("~/Games/Hookshot")))
            names = [name for _, name in make_game.LANGUAGES]
            code = self.cfg.get("language", "en-US")
            self.language = tk.StringVar(value=dict(make_game.LANGUAGES).get(code, names[0]))
            self.status = tk.StringVar()
            self._form()
            self.after(100, self._pump)
            self.protocol("WM_DELETE_WINDOW", self._close)
            try:
                self.createcommand("::tk::mac::OpenDocument", self._open_document)
            except tk.TclError:
                pass
            if self.nup.get():
                self.after(200, self._check_version)

        def _form(self):
            f = ttk.Frame(self)
            f.pack(fill="both", expand=True, padx=12, pady=8)
            f.columnconfigure(1, weight=1)
            ttk.Label(f, text="Hookshot", font=("TkDefaultFont", 16, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=4)
            ttk.Label(f, text="Builds the game on this Mac from your own .nup. The file stays on this computer.",
                      wraplength=560).grid(row=1, column=0, columnspan=3, sticky="w", pady=4)
            self._path_row(f, 2, ".nup file", self.nup, self._pick_nup)
            self._path_row(f, 3, "Save the game to", self.out, self._pick_out)
            ttk.Label(f, text="Language").grid(row=4, column=0, sticky="w", pady=4)
            ttk.Combobox(f, textvariable=self.language, values=[name for _, name in make_game.LANGUAGES],
                         state="readonly").grid(row=4, column=1, sticky="w", pady=4)
            ttk.Label(f, textvariable=self.status, wraplength=560).grid(row=5, column=0, columnspan=3, sticky="w", pady=4)
            buttons = ttk.Frame(f)
            buttons.grid(row=6, column=0, columnspan=3, sticky="we", pady=8)
            self.build_button = ttk.Button(buttons, text="Build", command=self._build)
            self.build_button.pack(side="left", expand=True, fill="x", padx=(0, 6))
            self.play_button = ttk.Button(buttons, text="Play", command=self._play)
            self.play_button.pack(side="left", expand=True, fill="x")
            self.log = scrolledtext.ScrolledText(f, height=16, wrap="word")
            self.log.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=4)
            f.rowconfigure(7, weight=1)
            self._say_tools()

        def _path_row(self, frame, row, label, var, browse):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(frame, textvariable=var).grid(row=row, column=1, sticky="we", padx=8, pady=4)
            ttk.Button(frame, text="Browse", command=browse).grid(row=row, column=2, pady=4)

        def _pick_nup(self):
            path = filedialog.askopenfilename(
                title="Your game's .nup",
                filetypes=[("Switch 2 game package", "*.nup"), ("All files", "*")])
            if path:
                self._set_nup(path)

        def _pick_out(self):
            path = filedialog.askdirectory(title="Save the game to", initialdir=self.out.get() or os.path.expanduser("~"))
            if path:
                self.out.set(path)
                self._remember()

        def _open_document(self, *paths):
            for path in paths:
                if path.lower().endswith(".nup"):
                    self._set_nup(path)

        def _set_nup(self, path):
            self.nup.set(path)
            self._remember()
            self._check_version()

        def _remember(self):
            code = "en-US"
            for lang, name in make_game.LANGUAGES:
                if name == self.language.get():
                    code = lang
            save_config({"nup": self.nup.get(), "out": self.out.get(), "language": code})

        def _say_tools(self):
            icd = os.path.join(brew_prefix(), "etc", "vulkan", "icd.d", "MoltenVK_icd.json")
            if not os.path.isfile(icd):
                self.status.set("MoltenVK was not found. Install it with: brew install molten-vk vulkan-headers vulkan-loader sdl2 ffmpeg pkg-config")

        def _check_version(self):
            path = self.nup.get()
            if not os.path.isfile(path):
                return
            python = existing_build_python(ROOT)
            if not python:
                self.status.set("Press Build to set up Python, then the version is checked.")
                return
            self.status.set("Checking the game version...")

            def run():
                r = subprocess.run([python, "-I", os.path.join(ROOT, "nx2", "make_game.py"), "--check", "--nup", path],
                                   capture_output=True, text=True, cwd=ROOT)
                said = [make_game.reported(line) for line in (r.stdout or "").splitlines()]
                said = [line for line in said if line]
                tail = [line for line in (r.stderr or "").splitlines() if line.strip()]
                self.lines.put(("check", said[-1] if said else (tail[-1] if tail else "The version could not be read.")))

            threading.Thread(target=run, daemon=True).start()

        def _python(self):
            try:
                return build_python(ROOT)
            except (OSError, subprocess.CalledProcessError) as exc:
                self.status.set("Could not set up Python for the build (%s)." % exc)
                return None

        def _build(self):
            nup = self.nup.get().strip()
            out = os.path.expanduser(self.out.get().strip())
            if not os.path.isfile(nup):
                messagebox.showerror("Hookshot", "Choose your game's .nup file.")
                return
            if not out:
                messagebox.showerror("Hookshot", "Choose a folder to save the game to.")
                return
            python = self._python()
            if not python:
                messagebox.showerror("Hookshot", "Homebrew Python 3.11 or newer is needed to build. brew install python")
                return
            self._remember()
            code = load_config().get("language", "en-US")
            self.build_button.state(["disabled"])
            self.status.set("Building...")
            env = header_env(ROOT, os.environ)
            cmd = build_command(python, ROOT, nup, out, code)

            def run():
                try:
                    self.proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                 text=True, bufsize=1)
                except OSError as exc:
                    self.lines.put(("done", 1, "Could not start the build (%s)." % exc))
                    return
                for line in self.proc.stdout:
                    self.lines.put(("log", line.rstrip("\n")))
                code_ = self.proc.wait()
                self.lines.put(("done", code_, out))

            threading.Thread(target=run, daemon=True).start()

        def _play(self):
            folder = os.path.expanduser(self.out.get().strip())
            if not game_exe(folder):
                messagebox.showerror("Hookshot", "No built game in that folder yet.")
                return
            self._launch(folder)

        def _launch(self, folder):
            sys.path.insert(0, os.path.join(ROOT, "nx2"))
            import make_game as game
            env = game.game_env()
            env.update(apple_play_env(env, memsize(), brew_prefix()))
            env["HOOKSHOT_NO_UPDATE_CHECK"] = "1"
            exe = game_exe(folder)
            write_game_app(folder, {k: env[k] for k in (
                "DYLD_LIBRARY_PATH", "VK_DRIVER_FILES", "VK_ICD_FILENAMES",
                "MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS", "HOS_MEMORY_MB") if k in env})
            subprocess.Popen([exe], cwd=folder, env=env, start_new_session=True)

        def _pump(self):
            try:
                while True:
                    kind, *rest = self.lines.get_nowait()
                    if kind == "check":
                        self.status.set(rest[0])
                    elif kind == "log":
                        line = rest[0]
                        self.log.insert("end", line + "\n")
                        self.log.see("end")
                        if line.startswith("@@stage "):
                            self.status.set(line.split(" ", 2)[-1])
                        reported = make_game.reported(line)
                        if reported and line.startswith("@@error "):
                            self.status.set(reported)
                    elif kind == "done":
                        code, out = rest
                        self.build_button.state(["!disabled"])
                        self.proc = None
                        if code == 0:
                            self.status.set("Your game is ready.")
                            self._launch_ready(out)
                        else:
                            self.status.set("The build stopped.")
            except queue.Empty:
                pass
            self.after(100, self._pump)

        def _launch_ready(self, folder):
            sys.path.insert(0, os.path.join(ROOT, "nx2"))
            import make_game as game
            env = game.game_env()
            extra = apple_play_env(env, memsize(), brew_prefix())
            write_game_app(folder, extra)

        def _close(self):
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
            self.destroy()

    Builder().mainloop()


def main(argv):
    if "--package" in argv:
        index = argv.index("--package")
        if index + 1 >= len(argv):
            print("needs a folder after --package", file=sys.stderr)
            return 2
        package(argv[index + 1])
        return 0
    nup = nup_from_argv(argv)
    if "--nup" in argv:
        index = argv.index("--nup")
        if index + 1 < len(argv):
            nup = os.path.abspath(argv[index + 1])
    run_gui(nup)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
