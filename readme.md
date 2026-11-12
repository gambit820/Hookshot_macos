<h1 align="center">
  <br>
  <a>
  <img src="assets/hookshot.png" alt="Hookshot" width="200">
</a>

  <br>
  <b>Hookshot for Mac</b>
  <br>
</h1>

<h4 align="center">The Legend of Zelda: Ocarina of Time (Nintendo Switch 2) on Apple Silicon, built on your Mac from your own copy.
</h4>

<p align="center">
  <a href="#where-this-build-is">Status</a> |
  <a href="#what-you-need">What you need</a> |
  <a href="#build-and-play">Build and play</a> |
  <a href="#controls">Controls</a> |
  <a href="#where-the-files-go">Files</a> |
  <a href="#if-something-goes-wrong">Problems</a>
</p>

This is a Mac port of [Hookshot](https://github.com/NotRexed/Hookshot). The game's code is translated to C and compiled
on your Mac, the console's system software is reimplemented, and the Switch 2 graphics are replayed through MoltenVK.
There is no emulator. Windows and Linux builds stay on the upstream project. This repository does not ship those, and
it does not ship the game.

> [!IMPORTANT]
> This repository **does not contain the game, keys, or a built game**, and it does not explain how to get them. You
> need your own copy. Everything the build creates (`hookshot`, `image.bin`, shader caches, and your saves) comes from
> your game and stays on your Mac. Never share those files.

Hookshot is an unofficial fan project, not affiliated with or endorsed by Nintendo.

## Where this build is

Tried on an Apple M5 with 16 GB of memory. It is early.

| What | Status |
|---|---|
| Builder | ✅ A Mac app. Browse or drop your `.nup`, then Build and Play |
| Opening and the title screen | ✅ They come up |
| Sound, keyboard, a controller, and saves | ✅ Present |
| Menus | ⚠️ They open, and they can crash. Heavy menus are slow |
| Picture | ⚠️ Can be wrong in places: textures and shapes are sometimes off |
| Graphics path | MoltenVK. This is not a Metal renderer. The Mac has no mesh shaders, so those draws run as compute |
| Memory | A Mac with 18 GB or less asks the game for 9400 MB, so the game's own pool still fits. A larger Mac keeps the game's usual amount |
| First start | The game prepares shaders and can sit on a black window for a while. Later starts are faster |

The supported game is program `0400486024DEC000`, update v131072, build `e0f3ccfa`. Other versions are refused.

## What you need

- Your own copy of that version, as a `.nup` file.
- An Apple Silicon Mac with 16 GB of memory or more.
- About 60 GB free while building, on the internal disk if you can.
- Xcode's command line tools, then Homebrew's packages:

```sh
xcode-select --install
brew install python molten-vk vulkan-headers vulkan-loader sdl2 ffmpeg pkg-config
```

Python 3.11 or newer does the build. The window itself does not need it. The first time you press **Build**, the app
uses a Python that already has the build's packages, or makes one under `~/.cache/hookshot-builder`.

## Build and play

1. Double-click `builder/macos/Hookshot.app`. The first time, right-click it and choose **Open**.
2. Press **Browse** and choose your `.nup`. You can also drop the `.nup` on the app.
3. Under **Save the game to**, keep `~/Games/Hookshot` or choose another folder. Choose a **Language**.
4. Press **Build**. The `.nup` is only read. It is not changed.
5. When it says **Your game is ready**, press **Play**.

Play finds MoltenVK from Homebrew and, on a Mac with 18 GB of memory or less, sets the 9400 MB pool. Closing the
builder does not close the game.

The build also writes `Hookshot.app` into the game folder. That one only starts the game that was built on this Mac.

From a terminal, after a build, on this 16 GB Mac:

```sh
cd ~/Games/Hookshot
export DYLD_LIBRARY_PATH="$(brew --prefix)/lib"
export VK_DRIVER_FILES="$(brew --prefix)/etc/vulkan/icd.d/MoltenVK_icd.json"
export MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS=1
export HOS_MEMORY_MB=9400
./hookshot
```

Leave out `HOS_MEMORY_MB` on a Mac with more than 18 GB. Do not set `HOS_WINDOW_SIZE`.

The same build from a source checkout, without the window:

```sh
python -I nx2/make_game.py --nup ~/your-game.nup --out ~/Games/Hookshot --language en-US
```

Vulkan and SPIR-V headers come from Homebrew. The Vulkan Memory Allocator header does not. A checkout that has already
built once has it at `work/vma`. Point `HOOKSHOT_VMA_HEADERS` at a folder whose `include/vk_mem_alloc.h` is that header
if the build cannot find it. The Mac app sets this when the header is at `work/vma` or `third_party/vma`.

To rebuild the builder after a change to its Swift sources:

```sh
builder/macos/build_app.sh
```

To hand someone the builder, without your game:

```sh
python -I builder/macos/hookshot_builder.py --package dist/Hookshot-mac
```

That writes `dist/Hookshot-mac.zip`. It has no `.nup`, no `image.bin`, and no built game. Each person points the app
at their own `.nup`. Do not send the game folder.

## Controls

Insert or F1 opens the menu. F11 toggles fullscreen. Esc lets the mouse go. `-` and `=` change the mouse sensitivity.

On the title screen, E selects **New Game**.

| | |
|---|---|
| Move | W A S D |
| Camera | Arrow keys, or I J K L |
| A | E |
| B | Shift |
| X | Space |
| Y | Left click, once the mouse is captured |
| L | Q |
| R | R |
| ZL | Z, or right click |
| ZR | X or F |
| Left stick click | Control |
| Right stick click | C |
| Plus | Tab or Enter |
| Minus | M |
| D-pad | 1 2 3 4 |

Menu mouse control from the Windows build is not part of this Mac build.

## Where the files go

- The build reads your `.nup` and does not change it.
- The game is written to the folder you chose, `~/Games/Hookshot` unless you picked another.
- The builder remembers that folder and the `.nup` in `~/Library/Application Support/Hookshot/builder.ini`.
- Work files for the build go to `~/.cache/hookshot-builder`.
- Saves are in the game folder's `user` directory and in `~/.local/share/hookshot`. They stay on this Mac.
- The last run's log is `hookshot_log.txt` in the game folder. A terminal run prints there as well.

## If something goes wrong

| Problem | What to do |
|---|---|
| "This version isn't supported" or the app names build `e0f3ccfa` | The `.nup` has to be program `0400486024DEC000`, update v131072, build `e0f3ccfa` |
| The window stays black the first time | The game is preparing shaders. Later starts are faster |
| The picture looks wrong | Known on this build. It is not fixed yet |
| The game closes while you move through the menus | Known on this build. It is not fixed yet. `hookshot_log.txt` in the game folder is the last run |
| Play cannot find Vulkan | Install MoltenVK and start from the app, or set `VK_DRIVER_FILES` as in the terminal example above |
| A Mac with 16 GB runs out of memory | Keep `HOS_MEMORY_MB=9400`. A smaller pool fails the game's own memory check |

## Credits

Hookshot is [NotRexed's project](https://github.com/NotRexed/Hookshot). This repository is a Mac port of it: the Darwin
host, the MoltenVK path, and the Mac builder. The game, the shader recompiler, and the rest of the credits belong to
the people named in the upstream readme.

## License

Hookshot is free software under the [GNU General Public License, version 3 or later](LICENSE) (GPL-3.0-or-later).
Third-party parts under other licenses that work with the GPL keep their own notices in their folders.

The Legend of Zelda and Ocarina of Time are trademarks of Nintendo.
