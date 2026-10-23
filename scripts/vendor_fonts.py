"""Vendor the Google Fonts we use into app/static/fonts/ as woff2, plus the CSS.

Asks the Google Fonts CSS2 API for exactly the weights and styles the site uses,
keeps the latin and latin-ext subsets (the rest are Cyrillic, Greek, Vietnamese —
nothing in this album needs them), downloads each file once and writes @font-face
rules pointing at the local copies.
"""
import pathlib
import re
import sys
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
KEEP_SUBSETS = ("latin", "latin-ext")

ROOT = pathlib.Path("app/static")
FONT_DIR = ROOT / "fonts"

SHEETS = {
    # The two faces every page uses.
    "fonts.css": {
        "title": "Geist for body text, Instrument Serif for display",
        "spec": "family=Geist:wght@400..600&family=Instrument+Serif:ital@0;1",
    },
    # Only the cover editor loads these seven display faces.
    "cover-fonts.css": {
        "title": "the seven mastheads the cover editor offers",
        "spec": ("family=Abril+Fatface"
                 "&family=Bodoni+Moda:ital,opsz,wght@0,6..96,400..900;1,6..96,400..900"
                 "&family=DM+Serif+Display:ital@0;1"
                 "&family=Gloock"
                 "&family=Libre+Bodoni:ital,wght@0,400..700;1,400..700"
                 "&family=Noto+Serif+Display:ital,wght@0,100..900;1,100..900"
                 "&family=Playfair+Display:ital,wght@0,400..900;1,400..900"),
    },
}

BLOCK = re.compile(r"/\*\s*([\w-]+)\s*\*/\s*@font-face\s*\{(.*?)\}", re.S)


def fetch(url: str, binary: bool = False) -> bytes | str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=120).read()
    return data if binary else data.decode()


def field(block: str, name: str) -> str:
    m = re.search(rf"{name}\s*:\s*([^;]+);", block)
    return m.group(1).strip() if m else ""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def main() -> None:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    downloads: dict[str, dict] = {}   # remote url -> {faces: [...], name: str}

    for sheet, info in SHEETS.items():
        css = fetch(f"https://fonts.googleapis.com/css2?{info['spec']}&display=swap")
        faces = []
        for subset, block in BLOCK.findall(css):
            if subset not in KEEP_SUBSETS:
                continue
            src = re.search(r"url\((https://[^)]+\.woff2)\)", block)
            if not src:
                continue
            face = {
                "family": field(block, "font-family").strip("'\""),
                "style": field(block, "font-style") or "normal",
                "weight": field(block, "font-weight") or "400",
                "stretch": field(block, "font-stretch"),
                "range": field(block, "unicode-range"),
                "subset": subset,
                "url": src.group(1),
            }
            faces.append(face)
            downloads.setdefault(face["url"], {"faces": []})["faces"].append(face)
        info["faces"] = faces
        print(f"{sheet}: {len(faces)} faces over {KEEP_SUBSETS}")

    # Name each file once. A variable font arrives as one file shared by several
    # weight declarations, so the weight only goes in the name when it identifies it.
    for url, item in downloads.items():
        f = item["faces"][0]
        weights = {g["weight"] for g in item["faces"]}
        parts = [slug(f["family"])]
        if len(weights) == 1 and " " not in f["weight"]:
            parts.append(f["weight"])
        if f["style"] != "normal":
            parts.append(f["style"])
        parts.append(f["subset"])
        item["name"] = "-".join(parts) + ".woff2"

    names = [i["name"] for i in downloads.values()]
    assert len(names) == len(set(names)), "two files want the same name: " + str(names)

    print(f"\ndownloading {len(downloads)} unique woff2 files")
    total = 0
    for url, item in sorted(downloads.items(), key=lambda kv: kv[1]["name"]):
        data = fetch(url, binary=True)
        assert data[:4] == b"wOF2", f"{item['name']} is not woff2"
        (FONT_DIR / item["name"]).write_bytes(data)
        total += len(data)
        uses = ", ".join(sorted({f"{g['weight']} {g['style']}" for g in item["faces"]}))
        print(f"  {len(data):>7,}  {item['name']:<44} [{uses}]")
    print(f"  {total:>7,}  TOTAL ({total / 1024:.0f} KB)")

    # --- write the stylesheets ---
    for sheet, info in SHEETS.items():
        out = [f"/* Self-hosted: {info['title']}.",
               " * Nothing here calls out to Google —",
               " * the woff2 files sit in app/static/fonts/, latin and latin-ext only.",
               " * Regenerate with scripts/vendor_fonts.py if the set ever changes. */",
               ""]
        last_family = None
        for f in info["faces"]:
            if f["family"] != last_family:
                out.append(f"/* {f['family']} */")
                last_family = f["family"]
            name = downloads[f["url"]]["name"]
            out.append("@font-face {")
            out.append(f"  font-family: '{f['family']}';")
            out.append(f"  font-style: {f['style']};")
            out.append(f"  font-weight: {f['weight']};")
            if f["stretch"]:
                out.append(f"  font-stretch: {f['stretch']};")
            out.append("  font-display: swap;")
            out.append(f"  src: url('/static/fonts/{name}') format('woff2');")
            out.append(f"  unicode-range: {f['range']};")
            out.append("}")
        text = "\n".join(out) + "\n"
        (ROOT / sheet).write_text(text, encoding="utf-8")
        print(f"\nwrote app/static/{sheet} ({len(text):,} bytes, "
              f"{text.count('@font-face')} rules)")


if __name__ == "__main__":
    sys.exit(main())
