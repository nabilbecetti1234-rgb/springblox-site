#!/usr/bin/env python3
"""Build a Cloudflare Pages *direct upload* package (dashboard limit: 1000 files).

The crisp item images (4000+ files) are bundled into hd/<game>/<n>.json packs
({key: data-uri}) so the whole site fits in < 1000 files. The page loads a pack
only when one of its items is on screen (see initHdPacks/loadPack in the template).

usage: python pipeline/build_cf_package.py [out.zip]
"""
import base64
import json
import os
import re
import shutil
import sys
import io
import zipfile

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'site')
FILE_LIMIT = 1000
PACKS_TARGET = 170      # few big packs upload reliably (dashboard uploads of ~1000 files stall)
ICON_PX, ICON_Q = 160, 80
MIME = {'.png': 'image/png', '.webp': 'image/webp', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif'}

NOT_FOUND = """<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>404</title>
<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0f19;color:#e2e8f0;font-family:system-ui,sans-serif;text-align:center">
<div><div style="font-size:64px">🧭</div><h1 style="margin:.2em 0">الصفحة مش موجودة</h1>
<a href="/" style="color:#2dd4bf">← رجوع للموقع</a></div></body></html>
"""
HEADERS = """/hd/*
  Cache-Control: public, max-age=604800
/assets/*
  Cache-Control: public, max-age=604800
/data/*
  Cache-Control: no-cache
"""


def shrink(path):
    """re-encode to webp <= ICON_PX (keeps the whole item + transparency); keep original if smaller"""
    raw = open(path, 'rb').read()
    try:
        im = Image.open(io.BytesIO(raw)).convert('RGBA')
        im.thumbnail((ICON_PX, ICON_PX), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, 'WEBP', quality=ICON_Q, method=4)
        out = buf.getvalue()
        if path.lower().endswith('.webp') and len(raw) <= len(out):
            return raw
        return out
    except Exception:
        return raw


def load_sb_data(html):
    m = re.search(r'const SB_DATA = (\{.*?\});\n', html, re.S)
    if not m:
        raise SystemExit('SB_DATA not found in site/index.html')
    return json.loads(m.group(1))


def main():
    out_zip = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'springblox-cloudflare.zip')
    html = open(os.path.join(SITE, 'index.html'), encoding='utf-8').read()
    data = load_sb_data(html)

    # every HD icon goes into a pack ('~file' = assets/icons/<game>/file, otherwise a site-relative path)
    pack_keys, real_files = {}, set()
    for g, d in data['games'].items():
        hd, seen, order = d.get('hd') or {}, set(), []
        for r in d['items']:
            p = hd.get(r[0])
            if not p or r[0] in seen:
                continue
            seen.add(r[0])
            src = os.path.join(SITE, 'assets', 'icons', g, p[1:]) if p[0] == '~' else os.path.join(SITE, p.split('?')[0])
            order.append((r[0], src))
        pack_keys[g] = order

    base_files = 10 + len(real_files)  # index.html, 404.html, _headers, data/values.json, hd/index.json, margin
    total_icons = sum(len(v) for v in pack_keys.values())
    n = max(1, -(-total_icons // PACKS_TARGET))
    while sum(-(-len(v) // n) for v in pack_keys.values()) > FILE_LIMIT - base_files - 40:
        n += 1

    stage = os.path.join(ROOT, '_cf_stage')
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(os.path.join(stage, 'data'))
    # slim page: drop embedded 32px previews for every icon that has an HD pack (the page loads packs instead)
    m = re.search(r'const SB_DATA = (\{.*?\});\n', html, re.S)
    slim = json.loads(m.group(1))
    dropped = 0
    for g, d in slim['games'].items():
        keep = {k: v for k, v in (d.get('icons') or {}).items() if k not in {k2 for k2, _ in pack_keys[g]}}
        dropped += len(d.get('icons') or {}) - len(keep)
        d['icons'] = keep
    slim_html = html[:m.start(1)] + json.dumps(slim, ensure_ascii=False, separators=(',', ':')) + html[m.end(1):]
    open(os.path.join(stage, 'index.html'), 'w', encoding='utf-8').write(slim_html)
    print(f'index.html {len(html.encode()) / 1e6:.2f} MB -> {len(slim_html.encode()) / 1e6:.2f} MB (dropped {dropped} embedded previews)')
    shutil.copy(os.path.join(SITE, 'data', 'values.json'), os.path.join(stage, 'data'))
    open(os.path.join(stage, '404.html'), 'w', encoding='utf-8').write(NOT_FOUND)
    for icon in ('favicon.ico', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png'):
        if os.path.isfile(os.path.join(SITE, icon)):
            shutil.copy(os.path.join(SITE, icon), stage)
    open(os.path.join(stage, '_headers'), 'w', encoding='utf-8').write(HEADERS)
    for rel in sorted(real_files):
        src = os.path.join(SITE, rel)
        if os.path.isfile(src):
            dst = os.path.join(stage, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(src, dst)

    packs, missing, pack_bytes = 0, 0, 0
    for g, order in pack_keys.items():
        os.makedirs(os.path.join(stage, 'hd', g), exist_ok=True)
        for i in range(0, len(order), n):
            pack = {}
            for key, path in order[i:i + n]:
                if not os.path.isfile(path):
                    missing += 1
                    continue
                pack[key] = 'data:image/webp;base64,' + base64.b64encode(shrink(path)).decode()
            body = json.dumps(pack, separators=(',', ':'))
            open(os.path.join(stage, 'hd', g, f'{i // n}.json'), 'w', encoding='utf-8').write(body)
            packs += 1
            pack_bytes += len(body)
    ver = data.get('generatedAt') or str(total_icons)
    json.dump({'n': n, 'v': re.sub(r'[^0-9A-Za-z]', '', ver)}, open(os.path.join(stage, 'hd', 'index.json'), 'w'))

    files = [os.path.join(r, f) for r, _, fs in os.walk(stage) for f in fs]
    assert len(files) <= FILE_LIMIT, f'{len(files)} files > {FILE_LIMIT}'
    big = [f for f in files if os.path.getsize(f) > 25 * 1024 * 1024]
    assert not big, big
    if os.path.exists(out_zip):
        os.remove(out_zip)
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(files):
            z.write(f, os.path.relpath(f, stage))
    shutil.rmtree(stage, ignore_errors=True)
    print(f'{total_icons} HD icons -> {packs} packs of {n} ({pack_bytes / 1e6:.1f} MB), missing {missing}; '
          f'{len(files)} files; zip {os.path.getsize(out_zip) / 1e6:.1f} MB -> {out_zip}')


if __name__ == '__main__':
    main()
