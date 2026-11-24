#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Re-encode all item icons to tiny WebP data URIs (56px, q70) and save a JSON map:
    pipeline/data/icons_inline.json  ->  { "<game>/<icon-stem>": "data:image/webp;base64,..." }
These are embedded into site/index.html by patch_html2.py so icons render even in
fully-offline/static previews (no file fetches at all).
"""
import base64
import io
import json
import os
import sys
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.abspath(os.path.join(ROOT, '..', 'site', 'assets', 'icons'))
OUT = os.path.join(ROOT, 'data', 'icons_inline.json')
TARGET = 32
QUALITY = 55


def encode(path):
    img = Image.open(path)
    w, h = img.size
    r = TARGET / max(w, h)
    if r < 1:
        img = img.resize((max(1, round(w * r)), max(1, round(h * r))), Image.LANCZOS)
    if img.mode not in ('RGBA', 'RGB'):
        img = img.convert('RGBA')
    buf = io.BytesIO()
    img.save(buf, 'WEBP', quality=QUALITY, method=5)
    return 'data:image/webp;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def main():
    out = {}
    total = 0
    for game in sorted(os.listdir(ICON_DIR)):
        gdir = os.path.join(ICON_DIR, game)
        if not os.path.isdir(gdir):
            continue
        for fn in sorted(os.listdir(gdir)):
            stem, ext = os.path.splitext(fn)
            if ext.lower() not in ('.png', '.webp', '.jpg', '.jpeg', '.gif'):
                continue
            try:
                uri = encode(os.path.join(gdir, fn))
                out[f"{game}/{stem}"] = uri
                total += len(uri)
            except Exception as e:  # noqa: BLE001
                print('skip', game, fn, str(e)[:60])
    # hand-fixed originals (site/assets/icons_fixed/<game>/<key>.*) replace bad/placeholder source icons
    fixed_dir = os.path.join(os.path.dirname(ICON_DIR), 'icons_fixed')
    if os.path.isdir(fixed_dir):
        for game in sorted(os.listdir(fixed_dir)):
            gdir = os.path.join(fixed_dir, game)
            if not os.path.isdir(gdir):
                continue
            for fn in sorted(os.listdir(gdir)):
                stem, ext = os.path.splitext(fn)
                if ext.lower() in ('.png', '.webp', '.jpg', '.jpeg', '.gif'):
                    try:
                        out[f"{game}/{stem}"] = encode(os.path.join(gdir, fn))
                    except Exception as e:  # noqa: BLE001
                        print('skip fixed', game, fn, str(e)[:60])
    # keep previously inlined icons whose source file is missing (e.g. an icon download failed this run)
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        prev = {}
    kept = 0
    for k, v in prev.items():
        if k not in out:
            out[k] = v
            total += len(v)
            kept += 1
    if kept:
        print(f'kept {kept} previously inlined icons (source file missing)')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, OUT)
    print(f"inlined {len(out)} icons -> {OUT} ({total/1e6:.2f} MB)")


if __name__ == '__main__':
    main()
