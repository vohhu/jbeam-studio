"""Makes the screenshots of docs/images smaller: 256 colours are enough for the colours the add-on draws.

    python scripts/shrink_images.py [<folder>]

Needs Pillow (`python -m pip install pillow`).
"""

import sys
from pathlib import Path

from PIL import Image

folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "docs" / "images"
for path in sorted(folder.glob("*.png")):
    image = Image.open(path).convert("RGB")
    image.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)
    print(f"{path.name}: {path.stat().st_size // 1024} KB")
