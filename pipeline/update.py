#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-shot updater used by the scheduled GitHub Action (or cron on any server).

  python pipeline/update.py            # refresh only the games that are due
  python pipeline/update.py --force    # refresh every game now

For each due game it scrapes the live source, then VALIDATES the result before
accepting it. A bad scrape (site down, layout changed, Cloudflare page, half the
items missing, values zeroed) is rejected and the previous good data is kept, so
the published site never shows broken numbers. Afterwards it rebuilds the inline
icon pack and site/index.html.

Exit code 0 = all due games OK, 1 = at least one game failed validation
(GitHub then emails the repo owner, and the site's badge shows the data age).
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import scrape  # noqa: E402

VALUES = os.path.abspath(os.path.join(ROOT, '..', 'site', 'data', 'values.json'))
MIN_COUNT_RATIO = 0.80   # new item count must be >= 80% of the previous count
MIN_VALUED_RATIO = 0.90  # >= 90% of items must have a positive value
MAX_MEDIAN_JUMP = 5.0    # median value may not move more than 5x in one run


def load_prev():
    try:
        return json.load(open(VALUES, encoding='utf-8'))
    except Exception:
        return {}


def age_hours(prev, game):
    try:
        ts = prev['games'][game]['generatedAt']
        dt = datetime.strptime(ts, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 1e9


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def validate(game, items, prev):
    if not items:
        return 'no items returned'
    valued = [i['value'] for i in items if isinstance(i.get('value'), (int, float)) and i['value'] > 0]
    if len(valued) < MIN_VALUED_RATIO * len(items):
        return f'only {len(valued)}/{len(items)} items have a value'
    old = (prev.get('games') or {}).get(game)
    if old and old.get('items'):
        oc = len(old['items'])
        if len(items) < MIN_COUNT_RATIO * oc:
            return f'item count dropped {oc} -> {len(items)}'
        om = median([i['value'] for i in old['items'] if (i.get('value') or 0) > 0])
        nm = median(valued)
        if om and nm and not (1 / MAX_MEDIAN_JUMP <= nm / om <= MAX_MEDIAN_JUMP):
            return f'median value jumped {om} -> {nm}'
    return None


def main():
    force = '--force' in sys.argv
    prev = load_prev()
    due = [g for g in scrape.GAMES
           if force or age_hours(prev, g) >= scrape.GAME_META[g]['refreshHours'] - 0.25]
    if not due:
        print('nothing due — all games fresh')
        return 0

    good, failed = {}, {}
    for g in due:
        t0 = time.time()
        try:
            items = scrape.scrape_game(g)
            err = validate(g, items, prev)
        except Exception as e:  # network / parse errors
            items, err = None, f'{type(e).__name__}: {e}'
        dt = time.time() - t0
        if err:
            failed[g] = err
            print(f'[{g}] REJECTED ({dt:.0f}s): {err} — keeping previous data', flush=True)
        else:
            good[g] = items
            print(f'[{g}] OK {len(items)} items ({dt:.0f}s)', flush=True)

    if good:
        scrape.build_outputs(good)
        subprocess.run([sys.executable, os.path.join(ROOT, 'build_inline_icons.py')], check=True)
        subprocess.run([sys.executable, os.path.join(ROOT, 'build_site_v2.py')], check=True)
        print('site rebuilt')

    if failed:
        print('FAILED:', json.dumps(failed, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
