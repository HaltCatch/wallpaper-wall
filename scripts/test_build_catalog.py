import unittest
from pathlib import Path

from build_catalog import grouped_variants


class GroupingTests(unittest.TestCase):
    def test_every_sibling_image_is_a_variant_regardless_of_name(self):
        groups = grouped_variants([
            Path("003.png"),
            Path("completely unrelated export name.png"),
            Path("429 - 电脑_20241130_160955.png"),
            Path("cover-final-copy.png"),
        ])
        self.assertEqual(list(groups), ["__folder__"])
        self.assertEqual(len(groups["__folder__"]), 4)

    def test_distinct_prefixes_do_not_split_a_folder(self):
        groups = grouped_variants([Path("003.png"), Path("004.png")])
        self.assertEqual(set(groups), {"__folder__"})
        self.assertEqual(len(groups["__folder__"]), 2)

    def test_timestamped_device_exports_stay_with_the_original(self):
        groups = grouped_variants([
            Path("429.png"),
            Path("429 - 电脑.png"),
            Path("429 - 电脑_20241130_160955.png"),
            Path("429 - 手机_20241205_160921.png"),
            Path("429_20241205_160922.png"),
        ])
        self.assertEqual(list(groups), ["__folder__"])
        self.assertEqual(len(groups["__folder__"]), 5)

    def test_descriptor_only_file_is_a_variant_too(self):
        groups = grouped_variants([Path("003.png"), Path("封面.png")])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups["__folder__"]), 2)


if __name__ == "__main__":
    unittest.main()
