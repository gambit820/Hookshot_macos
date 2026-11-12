"""The macOS builder's launch environment and the share package. No window, and no game files."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "builder", "macos"))
import hookshot_builder as mac  # noqa: E402


class PlayEnvTests(unittest.TestCase):
    def test_a_small_mac_gets_moltenvk_and_a_memory_cap(self):
        prefix = tempfile.mkdtemp(prefix="hookshot-brew-")
        os.makedirs(os.path.join(prefix, "lib"))
        icd = os.path.join(prefix, "etc", "vulkan", "icd.d")
        os.makedirs(icd)
        open(os.path.join(icd, "MoltenVK_icd.json"), "w").close()
        env = mac.apple_play_env({}, 16 * 1024 ** 3, prefix)
        self.assertEqual(env["VK_DRIVER_FILES"], os.path.join(icd, "MoltenVK_icd.json"))
        self.assertEqual(env["DYLD_LIBRARY_PATH"], os.path.join(prefix, "lib"))
        self.assertEqual(env["MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS"], "1")
        self.assertEqual(env["HOS_MEMORY_MB"], "9400")

    def test_an_existing_choice_is_kept_and_a_larger_mac_is_not_capped(self):
        prefix = tempfile.mkdtemp(prefix="hookshot-brew-")
        os.makedirs(os.path.join(prefix, "lib"))
        given = {"VK_DRIVER_FILES": "/mine.json", "HOS_MEMORY_MB": "9809",
                 "MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS": "0", "DYLD_LIBRARY_PATH": os.path.join(prefix, "lib")}
        env = mac.apple_play_env(given, 32 * 1024 ** 3, prefix)
        self.assertEqual(env, {})


class ShareTests(unittest.TestCase):
    def test_game_files_are_left_out_and_the_allocator_header_is_kept(self):
        src = tempfile.mkdtemp(prefix="hookshot-src-")
        dest = tempfile.mkdtemp(prefix="hookshot-share-")
        os.makedirs(os.path.join(src, "nx2"))
        with open(os.path.join(src, "nx2", "make_game.py"), "w", encoding="utf-8") as f:
            f.write("# builder\n")
        with open(os.path.join(src, "mine.nup"), "w", encoding="utf-8") as f:
            f.write("game")
        os.makedirs(os.path.join(src, "work", "vma", "include"))
        header = os.path.join(src, "work", "vma", "include", "vk_mem_alloc.h")
        with open(header, "wb") as f:
            f.write(b"/* Permission is hereby granted */\n#define AMD_VULKAN_MEMORY_ALLOCATOR_H\n")
        os.makedirs(os.path.join(src, "work", "dump"))
        with open(os.path.join(src, "work", "dump", "image.bin"), "wb") as f:
            f.write(b"game")
        os.makedirs(os.path.join(src, "builder", "macos"))
        with open(os.path.join(src, "builder", "macos", "README.txt"), "w", encoding="utf-8") as f:
            f.write("read me\n")
        mac.copy_share(src, dest)
        self.assertTrue(os.path.isfile(os.path.join(dest, "source", "nx2", "make_game.py")))
        self.assertFalse(os.path.exists(os.path.join(dest, "source", "mine.nup")))
        self.assertFalse(os.path.exists(os.path.join(dest, "source", "work")))
        kept = os.path.join(dest, "source", "third_party", "vma", "include", "vk_mem_alloc.h")
        with open(kept, "rb") as f:
            self.assertIn(b"AMD_VULKAN_MEMORY_ALLOCATOR_H", f.read())
        with open(os.path.join(dest, "README.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "read me\n")

    def test_a_refused_header_stops_the_package(self):
        src = tempfile.mkdtemp(prefix="hookshot-src-")
        dest = tempfile.mkdtemp(prefix="hookshot-share-")
        os.makedirs(os.path.join(src, "work", "vma", "include"))
        with open(os.path.join(src, "work", "vma", "include", "vk_mem_alloc.h"), "wb") as f:
            f.write(b"not the allocator\n")
        with self.assertRaises(SystemExit):
            mac.copy_share(src, dest)


class LauncherTests(unittest.TestCase):
    def test_the_game_app_points_at_the_built_game(self):
        text = mac.game_launcher_script("./hookshot", {"VK_DRIVER_FILES": "/opt/homebrew/etc/vulkan/icd.d/MoltenVK_icd.json",
                                                      "HOS_MEMORY_MB": "9400"})
        self.assertIn('export VK_DRIVER_FILES=/opt/homebrew/etc/vulkan/icd.d/MoltenVK_icd.json\n', text)
        self.assertIn('export HOS_MEMORY_MB=9400\n', text)
        self.assertIn('exec ./hookshot\n', text)
        self.assertIn('cd "$(dirname "$0")/../../.."', text)


if __name__ == "__main__":
    unittest.main()
