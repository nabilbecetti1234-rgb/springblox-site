#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SpringBlox v7 — build the single-file site from scratch.
Keeps ONLY the holographic trade scale idea from the old site.
Everything (icons, values, fonts) is embedded so the file works fully offline,
including inside static sandboxed previews.
"""
import base64
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(ROOT, 'template_v3.html')
VALUES = os.path.abspath(os.path.join(ROOT, '..', 'site', 'data', 'values.json'))
ICONS = os.path.join(ROOT, 'data', 'icons_inline.json')
FONTS_DIR = os.path.abspath(os.path.join(ROOT, '..', 'site', 'assets', 'fonts'))
OUT = os.path.abspath(os.path.join(ROOT, '..', 'site', 'index.html'))

AM_RP_PER_FROST = 157.95

GAME_INFO = {
    'mm2': {'t': 'MM2', 's': 'Supreme Values', 'u': 'https://www.mm2values.com/', 'h': 12},
    'adoptme': {'t': 'أدوبت مي', 's': 'AMTV', 'u': 'https://adoptmetradingvalues.com/', 'h': 12},
    'bloxfruits': {'t': 'بلوكس فوورتس', 's': 'Blox Fruits Values', 'u': 'https://bloxfruitsvalues.net/', 'h': 3},
}

ARABIC_RANGE = 'U+0600-06FF, U+0750-077F, U+0870-088E, U+0890-0891, U+0897-08FF, U+FD3E-FD3F, U+FDF0-FDFF, U+FE70-FE74'
LATIN_RANGE = 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD'


def build_fonts_css():
    blocks = []
    for weight in (400, 700, 900):
        for subset, rng in (('arabic', ARABIC_RANGE), ('latin', LATIN_RANGE)):
            fname = f"Cairo-{weight}-{subset}.woff2"
            path = os.path.join(FONTS_DIR, fname)
            if not os.path.exists(path):
                continue
            b64 = base64.b64encode(open(path, 'rb').read()).decode('ascii')
            blocks.append(
                "@font-face {\n"
                "  font-family: 'Cairo';\n"
                f"  font-style: normal;\n"
                f"  font-weight: {weight};\n"
                "  font-display: swap;\n"
                f"  src: url(data:font/woff2;base64,{b64}) format('woff2');\n"
                f"  unicode-range: {rng};\n"
                "}"
            )
    return '\n'.join(blocks)


def build_data():
    values = json.load(open(VALUES, encoding='utf-8'))
    icons_all = json.load(open(ICONS, encoding='utf-8'))
    ov_path = os.path.join(ROOT, 'data', 'icon_overrides.json')
    overrides = json.load(open(ov_path, encoding='utf-8')) if os.path.exists(ov_path) else {}
    from build_inline_icons import encode as encode_icon
    site_dir = os.path.abspath(os.path.join(ROOT, '..', 'site'))
    NO_ICON = {('mm2', 'brew')}  # source only has a "coming soon" placeholder
    games = {}
    hd_all = {}
    used_icons = {}
    changes_out = {}
    for game in ('mm2', 'adoptme', 'bloxfruits'):
        gi = values['games'].get(game)
        if not gi:
            continue
        meta = GAME_INFO[game]
        rows = []
        cats = []
        seen_cats = []
        for it in gi['items']:
            key = it['key']
            val = it.get('value') or 0
            if game == 'adoptme':
                val = round(val / AM_RP_PER_FROST, 5)
            cat = it.get('category') or 'عناصر'
            if cat not in seen_cats:
                seen_cats.append(cat)
            icon_path = it.get('icon') or ''
            fixed = overrides.get(game, {}).get(key)
            if (game, key) in NO_ICON:
                uri, icon_path = '', ''
            elif fixed and os.path.exists(os.path.join(site_dir, fixed)):
                uri = encode_icon(os.path.join(site_dir, fixed))
                icon_path = fixed
            else:
                stem = os.path.splitext(os.path.basename(icon_path))[0] if icon_path else ''
                uri = icons_all.get(f"{game}/{stem}", '')
            if uri:
                used_icons[f"{game}/{key}"] = uri
            if icon_path:
                hd_all.setdefault(game, {})[key] = icon_path.replace(f'assets/icons/{game}/', '~')
            trend = it.get('trend') or ''
            rows.append([
                key,
                it['name'],
                cat,
                val,
                it.get('demand') if it.get('demand') is not None else 0,
                it.get('rarity') or '',
                trend,
                it.get('permValue') or 0,
            ])
        games[game] = {
            't': meta['t'], 's': meta['s'], 'u': meta['u'], 'h': meta['h'],
            'gen': gi.get('generatedAt'),
            'cats': sorted(seen_cats, key=lambda c: -sum(1 for r in rows if r[2] == c)),
            'items': rows,
            'icons': {k.split('/', 1)[1]: v for k, v in used_icons.items() if k.startswith(game + '/')},
            'hd': hd_all.get(game, {}),
        }
        ch = values.get('changes', {}).get(game, {})
        changes_out[game] = {
            k: [1 if v.get('dir') == 'up' else 2 if v.get('dir') == 'down' else 0,
                v.get('pct') if isinstance(v.get('pct'), (int, float)) else None]
            for k, v in ch.items()
        }
    return {
        'games': games,
        'changes': changes_out,
        'generatedAt': values.get('generatedAt'),
    }


def main():
    data = build_data()
    n_items = sum(len(g['items']) for g in data['games'].values())
    n_icons = sum(len(g['icons']) for g in data['games'].values())
    print(f"data: {n_items} items, {n_icons} inline icons")

    html = open(TEMPLATE, encoding='utf-8').read()
    assert '__SB_DATA_JSON__' in html and '__FONTS_CSS__' in html

    fonts_css = build_fonts_css()
    print(f"fonts css: {len(fonts_css)/1024:.0f} KB")

    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    assert '</script' not in payload.lower()

    html = html.replace('__FONTS_CSS__', fonts_css)
    sup_path = os.path.join(ROOT, 'data', 'support.json')
    support = json.load(open(sup_path, encoding='utf-8')) if os.path.exists(sup_path) else {}
    support = {'gamepasses': support.get('gamepasses', [])}
    html = html.replace('__SB_SUPPORT_JSON__', json.dumps(support, ensure_ascii=False))
    html = html.replace('__SB_DATA_JSON__', payload)

    # safety: verify final file has no external resource references
    for bad in ('https://cdn.tailwindcss.com', 'fonts.googleapis.com', 'fonts.gstatic.com'):
        if bad in html.split('<script>')[0]:
            print(f'FAIL: external reference {bad} in head')
            raise SystemExit(1)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w', encoding='utf-8').write(html)
    print(f"written {OUT} ({len(html)/1e6:.2f} MB)")


if __name__ == '__main__':
    main()
