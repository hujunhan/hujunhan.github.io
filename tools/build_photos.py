#!/usr/bin/env python3
"""Build the photo gallery: resized WebP variants + inline blur placeholders.

Usage: python3 tools/build_photos.py [SRC_DIR]   (default ~/Downloads/portfolio)

- Source files are sorted by the number in their name; that order is the page order.
- Each photo is auto-oriented, converted to sRGB, and stripped of ALL metadata
  (EXIF/GPS/XMP) before being written to assets/photos/NN-{640,1280,2048}.webp.
- photos/index.html is regenerated between the GALLERY markers.
Requires ImageMagick 7 (`magick`) and exiftool.
"""
import base64, html, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "Downloads/portfolio")
OUT = ROOT / "assets/photos"
PAGE = ROOT / "photos/index.html"
SIZES = [640, 1280, 2048]          # long edge, px
QUALITY = 80
EAGER = 6                          # first N images load eagerly (above the fold)
OG_PHOTO = 25                      # which photo becomes the link-preview image (og.jpg)
PROFILES = Path("/System/Library/ColorSync/Profiles")
SRGB = PROFILES / "sRGB Profile.icc"
P3 = PROFILES / "Display P3.icc"

CAMERAS = {
    "ILCE-7CM2": "Sony A7C II", "E-M5MarkIII": "Olympus E-M5 III", "DMC-GM1": "Lumix GM1",
    "NEX-5T": "Sony NEX-5T", "X-S10": "Fujifilm X-S10", "DC-GX9": "Lumix GX9",
    "NIKON Z 5": "Nikon Z5", "DC-ZS200D": "Lumix ZS200", "Canon EOS R6": "Canon EOS R6",
    "iPhone 14 Pro": "iPhone 14 Pro",
}


def run(*args):
    return subprocess.run(args, check=True, capture_output=True).stdout


def num(p):
    m = re.search(r"(\d+)\D*$", p.stem)
    return int(m.group(1)) if m else 0


def main():
    srcs = sorted((p for p in SRC.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff")), key=num)
    if not srcs:
        sys.exit(f"no images in {SRC}")
    meta = json.loads(run("exiftool", "-j", "-Model", "-DateTimeOriginal", "-ProfileDescription",
                          "-ColorSpace", "-Make", *map(str, srcs)))
    meta = {Path(m["SourceFile"]).name: m for m in meta}
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.webp"):
        old.unlink()

    items = []
    for i, src in enumerate(srcs, 1):
        m = meta[src.name]
        stem = f"{i:02d}"
        # Colour: embedded ICC is honoured by -profile; an iPhone file without ICC but
        # flagged "Uncalibrated" is Display P3, so assign that before converting.
        color = ["-profile", str(SRGB)]
        if not m.get("ProfileDescription") and m.get("ColorSpace") == "Uncalibrated" and m.get("Make") == "Apple":
            color = ["-profile", str(P3), "-profile", str(SRGB)]
        base = ["magick", str(src), "-auto-orient", *color, "-strip"]
        variants = []
        for s in SIZES:
            out = OUT / f"{stem}-{s}.webp"
            run(*base, "-resize", f"{s}x{s}>", "-quality", str(QUALITY), "-define", "webp:method=6", str(out))
            w, h = map(int, run("magick", "identify", "-format", "%w %h", str(out)).split())
            variants.append((out.name, w, h))
        lqip = run(*base, "-resize", "24x24", "-quality", "50", "webp:-")
        year = (m.get("DateTimeOriginal") or "")[:4]
        cam = CAMERAS.get(m.get("Model", ""), m.get("Model", ""))
        items.append(dict(stem=stem, variants=variants, lqip=base64.b64encode(lqip).decode(),
                          caption=" · ".join(x for x in (year, cam) if x)))
        print(f"{stem}  {src.name}  {variants[-1][1]}x{variants[-1][2]}  {items[-1]['caption']}")

    run("magick", str(OUT / f"{OG_PHOTO:02d}-1280.webp"), "-quality", "85", str(OUT / "og.jpg"))
    write_page(items)
    total = sum(f.stat().st_size for f in OUT.glob("*.webp"))
    print(f"\n{len(items)} photos, {total / 1e6:.1f} MB in {OUT.relative_to(ROOT)}")
    leak = run("exiftool", "-q", "-q", "-a", "-gps:all", "-s", *map(str, OUT.glob("*.webp"))).strip()
    if leak:
        sys.exit("GPS metadata found in output!\n" + leak.decode())


def write_page(items):
    rows = []
    for n, it in enumerate(items):
        name, w, h = it["variants"][-1]
        srcset = ", ".join(f"../assets/photos/{f} {fw}w" for f, fw, _ in it["variants"])
        mid = it["variants"][1][0]
        load = 'fetchpriority="high"' if n < EAGER else 'loading="lazy"'
        cap = html.escape(it["caption"], quote=True)
        # Displayed width ≈ aspect × row height (CSS: 300px desktop / 180px phone,
        # rows stretch up to ~1.5× to fill). Lets the browser pick the smallest file.
        r = w / h
        sizes = f"(max-width: 600px) {min(100, round(r * 270 / 3.75))}vw, {round(r * 420)}px"
        rows.append(
            f'<a href="../assets/photos/{name}" style="--r:{w / h:.4f};--ph:url(data:image/webp;base64,{it["lqip"]})" '
            f'data-cap="{cap}">'
            f'<img src="../assets/photos/{mid}" srcset="{srcset}" sizes="{sizes}" '
            f'width="{w}" height="{h}" {load} decoding="async" alt="Photo {n + 1}"></a>')
    page = PAGE.read_text()
    page = re.sub(r"(<!-- GALLERY:START -->\n).*?(<!-- GALLERY:END -->)",
                  lambda mo: mo.group(1) + "\n".join(rows) + "\n" + mo.group(2), page, flags=re.S)
    PAGE.write_text(page)


if __name__ == "__main__":
    main()
