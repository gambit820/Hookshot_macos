Hookshot on macOS

This is the builder, not the game. It does not contain a copy of the game, and it must not: each person builds from their own .nup. Do not add a .nup, image.bin, a built hookshot, romfs, exefs, or a Games/Hookshot folder to this package, and do not send those to anyone.

What you need

- Your own copy of the game at the supported version: program 0400486024DEC000, update v131072, build e0f3ccfa, as a .nup file.
- An Apple Silicon Mac with 16 GB of memory or more, and about 60 GB free while building.
- Xcode's command line tools (clang).
- Homebrew packages:

    brew install python molten-vk vulkan-headers vulkan-loader sdl2 ffmpeg pkg-config

Build and play

1. Double-click Hookshot.app. The window is a Mac app. The first time, right-click it and choose Open.
2. Press Browse and choose your .nup. You can also drop the .nup onto the Hookshot icon.
3. Leave the folder as ~/Games/Hookshot, or choose another.
4. Press Build. The first build takes a long time. The .nup is only read; it is not changed.
5. Press Play. On a Mac with 18 GB of memory or less, Play asks the game for 9400 MB so the game's own pool still fits.

The next time, double-click Hookshot.app and press Play, or double-click Hookshot.app inside the game folder. That second app only starts the game that was built on this Mac.

The first start prepares shaders and can sit on a black window for a while. Later starts are faster.

On this build the picture can be wrong in places, and moving through the menus can crash the game. Both are still open.

Saves are in the game folder's user directory and in ~/.local/share/hookshot. They stay on this Mac.
