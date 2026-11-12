"""Regression tests for neutral Homepage derivatives."""

from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.build_catalog import make_homepage_background  # noqa: E402


class HomepageDerivativeTests(unittest.TestCase):
    def test_homepage_derivative_preserves_a_white_wallpaper(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            target = root / "homepage.webp"
            Image.new("RGB", (1280, 720), "white").save(source)
            make_homepage_background(str(source), str(target))
            with Image.open(target) as generated:
                red, green, blue = generated.convert("RGB").getpixel((0, 0))
            self.assertGreaterEqual(red, 248)
            self.assertGreaterEqual(green, 248)
            self.assertGreaterEqual(blue, 248)
