#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SpringBlox live-value pipeline.
Scrapes tradable items + real values + original icons for:
  - Murder Mystery 2  (mm2values.com  — Supreme Values)
  - Adopt Me          (adoptmetradingvalues.com)
  - Blox Fruits       (bloxfruitsvalues.net)
Downloads every item icon locally and writes:
  - site/data/values.json          (combined live data, consumed by the site & API)
  - pipeline/data/values_<game>.json
  - pipeline/data/history.json     (value history for rise/fall arrows)
"""
import json
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.abspath(os.path.join(ROOT, '..', 'site'))
DATA_DIR = os.path.join(ROOT, 'data')
ICON_DIR = os.path.join(SITE, 'assets', 'icons')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
HEADERS = {'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9'}

_lock = threading.Semaphore(12)

def http_get(url, timeout=30, binary=False, retries=2):
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            return data if binary else data.decode('utf-8', 'ignore')
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.2 * (attempt + 1))
    raise last_err


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip('-')
    return s or 'item'


def norm_name(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def sniff_ext(data):
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    if data[:3] == b'\xff\xd8\xff':
        return 'jpg'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if data[:4] == b'<svg' or data[:5] == b'<?xml':
        return 'svg'
    return None


ICON_MAX_DIM = 160
ICON_WEBP_QUALITY = 92


def save_icon(game, key, url):
    """Download an icon and save it under site/assets/icons/<game>/<key>.<ext>.
    Large images are downscaled and converted to WebP to keep the bundle small.
    Returns the site-relative path or None on failure."""
    try:
        with _lock:
            data = http_get(url, binary=True, timeout=25)
        ext = sniff_ext(data)
        if not ext or len(data) < 300:
            return None
        out_ext = ext
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(data))
            w, h = img.size
            if max(w, h) > ICON_MAX_DIM:
                ratio = ICON_MAX_DIM / max(w, h)
                img = img.resize((max(1, round(w * ratio)), max(1, round(h * ratio))), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, 'WEBP', quality=ICON_WEBP_QUALITY, method=4)
                if 0 < len(buf.getvalue()) < len(data):
                    data = buf.getvalue()
                    out_ext = 'webp'
        except Exception:
            pass
        gdir = os.path.join(ICON_DIR, game)
        os.makedirs(gdir, exist_ok=True)
        fname = f"{key}.{out_ext}"
        path = os.path.join(gdir, fname)
        with open(path, 'wb') as f:
            f.write(data)
        return f"assets/icons/{game}/{fname}"
    except Exception:
        return None


def parse_number(txt):
    return int(re.sub(r"[^0-9]", "", txt)) if txt else None


def parse_bmk(txt):
    """'480M' -> 480000000 ; '4.92B' -> 4920000000"""
    if not txt:
        return None
    m = re.match(r"^\$?([\d.,]+)\s*([BbMmKk]?)", txt.strip())
    if not m:
        return parse_number(txt)
    num = float(m.group(1).replace(',', ''))
    mult = {'b': 1e9, 'm': 1e6, 'k': 1e3}.get(m.group(2).lower(), 1)
    return int(num * mult)


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# --------------------------------------------------------------------------- #
# MM2 — mm2values.com (Supreme Values)
# --------------------------------------------------------------------------- #
MM2_CATEGORIES = [
    ('chroma', 'Chromas'), ('ancient', 'Ancients'), ('godly', 'Godlies'),
    ('vintage', 'Vintages'), ('legend', 'Legendaries'), ('rare', 'Rares'),
    ('uncommon', 'Uncommons'), ('common', 'Commons'), ('unique', 'Uniques'),
    ('pets', 'Pets'), ('misc', 'Misc'),
]

MM2_ITEM_RE = re.compile(
    r"<img src='img/([^']+)'[^>]*>\s*<b>(?:<div[^>]*>)?([^<]+)(?:</div>)?</b>\s*(?:<br>\s*)?"
    r"Value:\s*([\d,]+)<br>Range:\s*([^<]+?)\s*<br>Demand:\s*([\d.]+)\s*-\s*Rarity:\s*([\d.]+)"
    r"<br>Stability:\s*([^<]+)", re.I)

MM2_STABILITY_AR = {
    'doing well': 'مستقرة — أداء جيد',
    'stable': 'مستقرة',
    'underpaid for': 'أقل من قيمتها الحقيقية (فرصة شراء)',
    'overpaid for': 'أعلى من قيمتها الحقيقية',
}


def scrape_mm2():
    items = []
    seen = set()
    for page_key, cat_label in MM2_CATEGORIES:
        html = http_get(f"https://www.mm2values.com/?p={page_key}")
        for m in MM2_ITEM_RE.finditer(html):
            img_file, name, value, rng, demand, rarity, stability = m.groups()
            name = name.strip()
            key = slugify(name)
            if key in seen:
                key = f"{key}-{slugify(cat_label)}"
            if key in seen:
                continue
            seen.add(key)
            stab = stability.strip().lower()
            stab_ar = None
            for k, v in MM2_STABILITY_AR.items():
                if stab.startswith(k):
                    stab_ar = v
                    break
            items.append({
                'key': key,
                'name': name,
                'category': cat_label,
                'rarity': 'Godly' if page_key == 'godly' else cat_label.rstrip('s') if page_key not in ('pets', 'misc') else cat_label,
                'value': parse_number(value),
                'valueDisplay': value,
                'range': rng.strip(),
                'demand': float(demand),
                'rarityTier': float(rarity),
                'stability': stability.strip(),
                'trend': stab_ar or stability.strip(),
                'iconSource': f"https://www.mm2values.com/img/{img_file}",
                'icon': None,
                'source': 'mm2values.com',
            })
    # download icons concurrently
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = {pool.submit(save_icon, 'mm2', it['key'], it['iconSource']): it for it in items}
        for fut in as_completed(futs):
            futs[fut]['icon'] = fut.result()
    return items


# --------------------------------------------------------------------------- #
# Adopt Me — adoptmetradingvalues.com
# --------------------------------------------------------------------------- #
def _parse_alt(alt):
    """'Bat Dragon - Legendary from Halloween 2019 (Candy)' -> (name, rarity, origin)"""
    alt = alt.strip()
    if ' - ' not in alt:
        return alt, '', ''
    name, rest = alt.split(' - ', 1)
    if ' from ' in rest:
        rarity, origin = rest.split(' from ', 1)
    else:
        rarity, origin = rest, ''
    return name.strip(), rarity.strip(), origin.strip()


AM_PARAMS = [
    ('pets', 'Pets'), ('foods', 'Foods'), ('gifts', 'Gifts'), ('houses', 'Houses'),
    ('petwear', 'Pet Wear'), ('stickers', 'Stickers'), ('strollers', 'Strollers'),
    ('toys', 'Toys'), ('vehicles', 'Vehicles'),
]

AM_ITEM_RE = re.compile(
    r'href="what-is-worth/(\d+)"><div class="list-group-item"><image src="images\\(\d+)\.png"[^>]*alt="([^"]+)"')


def _fetch_am_demand(item_id):
    try:
        html = http_get(f"https://adoptmetradingvalues.com/what-is-worth/{item_id}")
        m = re.search(r'images/demandmeter(\d)\.png', html)
        return m.group(1) if m else None
    except Exception:
        return None


def scrape_adoptme():
    demand_cache_path = os.path.join(DATA_DIR, 'demand_cache.json')
    demand_cache = _load_json(demand_cache_path, {})

    merged = {}
    for params, cat_label in AM_PARAMS:
        html = http_get(f"https://adoptmetradingvalues.com/pet-value-list.php?params={params}")
        for chunk in re.split(r'<li id="li\d+"', html)[1:]:
            vm = re.search(r'<span class="ctr">([\d.]+)\s*RP</span>', chunk)
            if not vm:
                continue
            value = parse_number(vm.group(1))
            for m in AM_ITEM_RE.finditer(chunk):
                _href, img_id, alt = m.groups()
                name, rarity, origin = _parse_alt(alt)
                if img_id in merged:
                    # keep first specific category; pets win over generic repeats
                    if merged[img_id]['category'] == 'Pets':
                        continue
                    continue
                cat = cat_label
                if 'egg' in name.lower():
                    cat = 'Eggs'
                merged[img_id] = {
                    'key': f"pet-{img_id}",
                    'id': img_id,
                    'name': name,
                    'category': cat,
                    'rarity': rarity,
                    'origin': origin.strip(),
                    'value': value,
                    'valueDisplay': f"{value:,} RP",
                    'valueUnit': 'RP',
                    'demand': None,
                    'iconSource': f"https://adoptmetradingvalues.com/images/{img_id}.png",
                    'icon': None,
                    'source': 'adoptmetradingvalues.com',
                }
    items = list(merged.values())

    # demand: 1) demand cache, 2) index icons, 3) detail pages for the rest (cached forever)
    index_html = http_get("https://adoptmetradingvalues.com/")
    demand_by_id = {}
    ends = [m.start() for m in re.finditer(r'<div id="[^"]+" class="grid-item', index_html)]
    ends.append(len(index_html))
    for k in range(len(ends) - 1):
        seg = index_html[ends[k]:ends[k + 1]]
        im = re.search(r'images\\(\d+)\.png', seg)
        dm = re.search(r'images/demand(\d)\.png', seg)
        if im and dm:
            demand_by_id[im.group(1)] = int(dm.group(1))

    to_fetch = []
    for it in items:
        iid = it['id']
        if iid in demand_cache:
            it['demand'] = int(demand_cache[iid])
        elif iid in demand_by_id:
            it['demand'] = demand_by_id[iid]
            demand_cache[iid] = it['demand']
        else:
            to_fetch.append((it, iid))
    if to_fetch:
        with ThreadPoolExecutor(max_workers=10) as pool:
            futs = {pool.submit(_fetch_am_demand, iid): (it, iid) for it, iid in to_fetch}
            for fut in as_completed(futs):
                it, iid = futs[fut]
                lvl = fut.result()
                if lvl:
                    it['demand'] = int(lvl)
                    demand_cache[iid] = it['demand']
        _write_json(demand_cache_path, demand_cache)

    with ThreadPoolExecutor(max_workers=14) as pool:
        futs = {pool.submit(save_icon, 'adoptme', it['key'], it['iconSource']): it for it in items}
        for fut in as_completed(futs):
            futs[fut]['icon'] = fut.result()
    return items


# --------------------------------------------------------------------------- #
# Blox Fruits — bloxfruitsvalues.net
# --------------------------------------------------------------------------- #
BF_TREND_AR = {
    'rising': 'صاعدة ⬆', 'falling': 'هابطة ⬇', 'stable': 'مستقرة',
    'overpaid': 'مبالغ بها', 'underpaid': 'أقل من قيمتها', 'projected rise': 'متوقع ارتفاع',
    'projected fall': 'متوقع انخفاض', 'unstable': 'متقلّبة', 'soon': 'قريبًا',
    'hyped': 'عليها طلب', 'declining': 'هابطة ⬇',
}


def _parse_bf_card(chunk):
    nm = re.search(r'<a class="hover:text-brand-red" href="/values/([^"]+)">([^<]+)</a>', chunk)
    if not nm:
        return None
    slug, name = nm.group(1), nm.group(2).strip()
    rm = re.search(r'text-\S*-700">([^<]+)</p>', chunk)
    rarity = rm.group(1).strip() if rm else ''
    tm = re.search(r'bg-surface-alt px-2 py-0\.5 text-\[11px\][^>]*>([^<]+)</p>', chunk)
    ftype = tm.group(1).strip() if tm else ''
    vm = re.search(r'title="([\d,]+)"', chunk)
    value = parse_number(vm.group(1)) if vm else None
    dm = re.search(r'text-demand-\d+">([\d.]+)/10', chunk)
    demand = float(dm.group(1)) if dm else None
    trm = re.search(r'Trend</dt><dd[^>]*><span[^>]*>([^<]+)</span>', chunk)
    trend = trm.group(1).strip().lower() if trm else ''
    bm = re.search(r'Beli Price</span><span[^>]*>([^<]+)</span>', chunk)
    beli = bm.group(1).strip() if bm else ''
    im = re.search(r'src="(/img/[^"]+)"', chunk)
    return {
        'key': slug,
        'name': name,
        'slug': slug,
        'category': ftype or 'Fruits',
        'rarity': rarity,
        'value': value,
        'valueDisplay': f"{value:,}" if value else '',
        'valueUnit': 'absolute',
        'demand': demand,
        'trend': BF_TREND_AR.get(trend, trend),
        'beli': beli,
        'iconSource': f"https://bloxfruitsvalues.net{im.group(1)}" if im else None,
        'icon': None,
        'permValue': None,
        'permValueDisplay': None,
        'source': 'bloxfruitsvalues.net',
    }


def _fetch_bf_perm(slug, name):
    try:
        html = http_get(f"https://bloxfruitsvalues.net/values/{slug}")
        # exact values from FAQ text: "valued at 480,000,000 and a Permanent Kitsune at 4,920,000,000"
        faq = re.search(r"valued at ([\d,]+) and a Permanent [\w' -]+ at ([\d,]+)", html)
        if faq:
            return slug, parse_number(faq.group(1)), parse_number(faq.group(2))
        # fallback: meta description approximations
        meta = re.search(r'is worth ([\d.]+[BMK]?) \(Regular\) and ([\d.]+[BMK]?) \(Permanent\)', html)
        if meta:
            return slug, parse_bmk(meta.group(1)), parse_bmk(meta.group(2))
    except Exception:
        pass
    return slug, None, None


def scrape_bloxfruits(with_perm=True):
    html = http_get("https://bloxfruitsvalues.net/values")
    chunks = html.split('<article')[1:]
    items = [c for c in (_parse_bf_card(ch) for ch in chunks) if c]
    if with_perm:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(_fetch_bf_perm, it['slug'], it['name']) for it in items]
            for fut in as_completed(futs):
                slug, reg, perm = fut.result()
                for it in items:
                    if it['slug'] == slug:
                        if reg:
                            it['value'] = reg
                            it['valueDisplay'] = f"{reg:,}"
                        it['permValue'] = perm
                        it['permValueDisplay'] = f"{perm:,}" if perm else None
                        break
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = {pool.submit(save_icon, 'bloxfruits', it['key'], it['iconSource']): it
                for it in items if it['iconSource']}
        for fut in as_completed(futs):
            futs[fut]['icon'] = fut.result()
    return items


# --------------------------------------------------------------------------- #
# History + output
# --------------------------------------------------------------------------- #
GAME_META = {
    'mm2': {'title': 'Murder Mystery 2', 'sourceName': 'Supreme Values', 'sourceUrl': 'https://www.mm2values.com/', 'refreshHours': 12, 'unit': ''},
    'adoptme': {'title': 'Adopt Me!', 'sourceName': 'AdoptMe Trading Values', 'sourceUrl': 'https://adoptmetradingvalues.com/', 'refreshHours': 12, 'unit': 'RP'},
    'bloxfruits': {'title': 'Blox Fruits', 'sourceName': 'Blox Fruits Values', 'sourceUrl': 'https://bloxfruitsvalues.net/', 'refreshHours': 3, 'unit': ''},
}
GAMES = list(GAME_META.keys())


def _load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


TREND_DAYS = 7


def _age_days(iso):
    try:
        dt = datetime.strptime(iso, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return 1e9


def build_outputs(results):
    history_path = os.path.join(DATA_DIR, 'history.json')
    history = _load_json(history_path, {g: {} for g in GAMES})
    changes = {}
    for game, items in results.items():
        gch = {}
        gh = history.setdefault(game, {})
        for it in items:
            entry = gh.get(it['key'])
            prev = entry[-1]['value'] if entry else None
            ts = now_iso()
            if entry and entry[-1]['value'] == it['value']:
                entry[-1]['t'] = ts
                ch = {'dir': 'same', 'pct': 0, 'prev': prev}
                # keep showing the last change (arrow + %) for 7 days after it happened
                since = entry[-1].get('since')
                if since and len(entry) >= 2 and _age_days(since) <= TREND_DAYS:
                    old = entry[-2]['value']
                    if old and it['value'] and old != it['value']:
                        ch = {'dir': 'up' if it['value'] > old else 'down',
                              'pct': round((it['value'] - old) / old * 100, 2), 'prev': old}
            elif entry:
                pct = None
                if prev and it['value']:
                    pct = round((it['value'] - prev) / prev * 100, 2)
                entry.append({'t': ts, 'value': it['value'], 'since': ts})
                del entry[:-40]
                ch = {'dir': 'up' if (it['value'] or 0) > (prev or 0) else 'down',
                      'pct': pct, 'prev': prev}
            else:
                gh[it['key']] = [{'t': ts, 'value': it['value']}]
                ch = {'dir': 'same', 'pct': None, 'prev': None}
            gch[it['key']] = ch
        changes[game] = gch
    _write_json(history_path, history)

    games_out = {}
    for game, items in results.items():
        meta = GAME_META[game]
        ok_icons = sum(1 for i in items if i['icon'])
        games_out[game] = {
            'meta': meta,
            'generatedAt': now_iso(),
            'count': len(items),
            'iconsOk': ok_icons,
            'items': items,
        }
    # merge with any previously scraped games so per-game runs don't wipe others
    prev = _load_json(os.path.join(SITE, 'data', 'values.json'), {})
    merged_games = {}
    for g in GAMES:
        if g in games_out:
            merged_games[g] = games_out[g]
        elif g in prev.get('games', {}):
            merged_games[g] = prev['games'][g]
    changes_prev = prev.get('changes', {})
    for g in GAMES:
        if g not in changes and g in changes_prev:
            changes[g] = changes_prev[g]
    payload = {
        'generatedAt': now_iso(),
        'games': merged_games,
        'changes': changes,
    }
    _write_json(os.path.join(SITE, 'data', 'values.json'), payload)
    for game, items in results.items():
        _write_json(os.path.join(DATA_DIR, f"values_{game}.json"), {'generatedAt': now_iso(), 'items': items})
    return payload


def scrape_game(game, with_perm=True):
    if game == 'mm2':
        return scrape_mm2()
    if game == 'adoptme':
        return scrape_adoptme()
    if game == 'bloxfruits':
        return scrape_bloxfruits(with_perm=with_perm)
    raise ValueError(game)


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else 'all'
    games = GAMES if only == 'all' else [only]
    results = {}
    for g in games:
        t0 = time.time()
        items = scrape_game(g)
        dt = time.time() - t0
        ok = sum(1 for i in items if i['icon'])
        print(f"[{g}] items={len(items)} icons_ok={ok} in {dt:.1f}s", flush=True)
        results[g] = items
    payload = build_outputs(results)
    for g, gi in payload['games'].items():
        print(f"[{g}] wrote {gi['count']} items, icons {gi['iconsOk']}/{gi['count']}")


if __name__ == '__main__':
    main()
