"""Oblivion Estates prospecting engine — pipeline driver.

Usage:
    python main.py run [suburb-slug ...] [--sources a,b] [--pages N] [--no-ai]
    python main.py scrape [suburb-slug ...] [--sources a,b] [--pages N]
    python main.py score [--no-ai] [--limit N] [--new-only]
    python main.py dedupe
    python main.py erf [--all] [--force] # resolve erf numbers via CoCT cadastre
    python main.py cma [group_id] [--all]# comps summary / full CMA for a group
    python main.py gv [--force]          # fetch CoCT GV-roll valuations
    python main.py lifecycle             # delisting / sold-proxy sweep + stats
    python main.py report [--all]        # --all includes sole-mandate stock
    python main.py discover-locations [suburb-slug ...]
    python main.py import-tracker <xlsx>
    python main.py row <group_id|listing_key> [--cols a,b] [--header] [--print]
    python main.py row --set price=4500000 --set address="12 Oak Ave"
    python main.py sources               # list portals
    python main.py suburbs               # list areas

Portals crawled: Property24, Private Property, Pam Golding, Seeff, RE/MAX.
They run concurrently, each at its own polite rate.
"""

import sys
import webbrowser

import config
import db
import dedupe
import report
import scorer


def _flag_value(args: list[str], name: str, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    for a in args:
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def cmd_run(suburbs, source_names, pages, use_ai, do_score=True,
            only_stale=False):
    import pipeline
    targets = suburbs or list(config.SUBURBS)
    unknown = [s for s in targets if s not in config.SUBURBS]
    for s in unknown:
        print(f"unknown suburb: {s}")
    targets = [s for s in targets if s in config.SUBURBS]
    pipeline.run(targets, source_names, pages=pages, use_ai=use_ai,
                 do_score=do_score, only_stale=only_stale)


def cmd_dedupe():
    with db.connect() as conn:
        s = dedupe.rebuild_groups(conn)
    print(f"  {s['listings']} listings -> {s['groups']} properties; "
          f"{s['multi_agency_groups']} multi-agency (open-mandate proof), "
          f"{s['multi_source_groups']} on multiple portals")


def cmd_score(use_ai, limit, only_stale=False):
    with db.connect() as conn:
        n = scorer.score_all(conn, use_ai=use_ai, limit=limit,
                             only_stale=only_stale)
    print(f"  scored {n} property groups")


def cmd_erf(include_all: bool = True, force: bool = False):
    # include_all kept for the old --all flag; every property resolves now.
    import erf
    with db.connect() as conn:
        s = erf.resolve_all(conn, force=force)
    print(f"  {s['groups']} properties: {s['resolved']} resolved, "
          f"{s['check']} need a check, {s['candidates']} have candidate lists, "
          f"{s['unresolved']} unresolved, {s['skipped']} already done")
    a = erf.ai_locate_all()
    if a["groups"]:
        print(f"  AI locate: {a['located']} located from photos, "
              f"{a['errors']} failed")


def cmd_cma(group_id: str | None, include_all: bool):
    import json

    import cma
    with db.connect() as conn:
        if group_id:
            result = cma.analyse(conn, int(group_id))
            if result is None:
                print(f"  property group {group_id} not found")
                return
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return
        # index-style summary of sellable groups (--all includes sole-mandate)
        import cma_web
        rows = cma_web._index_rows(conn, include_sole=include_all)
        if not rows:
            print("  no sellable property groups yet — run a scrape first")
            return
        print(f"  {'grp':>4} {'tier':5} {'score':>5} {'asking':>14} "
              f"{'GV value':>14} {'erf':>7} {'ag':>2}  title / suburb")
        for r in rows:
            price = f"R{r['price_zar']:,}" if r["price_zar"] else "POA"
            gv = f"R{r['gv_value']:,}" if r["gv_value"] else "—"
            print(f"  {r['group_id']:>4} {(r['tier'] or '—'):5} "
                  f"{(r['score'] if r['score'] is not None else '—'):>5} "
                  f"{price:>14} {gv:>14} {(r['erf_number'] or '—'):>7} "
                  f"{r['agency_count']:>2}  {r['title'][:48]} — {r['suburb']}"
                  + ("  [owner known]" if r["owner_known"] else ""))
        print(f"  {len(rows)} sellable property groups — "
              "open one with: python main.py cma <group_id>")


def cmd_gv(force: bool):
    import sbm_roll
    import valuations
    with db.connect() as conn:
        counts = valuations.resolve_all(conn, force=force)
        sbm = sbm_roll.resolve_all(conn, force=force)
    print(f"  GV valuations: {counts['fetched']} fetched, "
          f"{counts['cached']} cached, {counts['not_found']} not found, "
          f"{counts['errors']} errors")
    print(f"  SBM roll: {sbm['matched']} matched, {sbm['cached']} cached, "
          f"{sbm['not_found']} not found ({sbm['towns']} towns)")


def cmd_lifecycle():
    import lifecycle
    with db.connect() as conn:
        counts = lifecycle.update(conn)
        conn.commit()
        overall = lifecycle.stats(conn)
    print(f"  lifecycle: {counts['active']} active, "
          f"{counts['newly_delisted']} newly delisted, "
          f"{counts['newly_relisted']} newly relisted, "
          f"{counts['delisted_total']} delisted total, "
          f"{counts['likely_sold_total']} likely sold")
    print(f"  medians: DOM active {overall['median_dom_active']}, "
          f"DOM delisted {overall['median_dom_delisted']}, "
          f"cut {overall['median_cut_pct']}%")


def cmd_report(include_sole: bool):
    with db.connect() as conn:
        path = report.generate(conn, include_sole=include_sole)
    print(f"  report written to {path}")
    try:
        import os
        webbrowser.open(f"file://{os.path.abspath(path)}")
    except Exception:
        pass


def cmd_import_tracker(path):
    import tracker
    with db.connect() as conn:
        s = tracker.import_xlsx(conn, path)
    print(f"  read {s['rows_read']} rows -> {s['unique']} unique properties "
          f"({s['prospected']} already prospected, excluded from reports)")


def cmd_sources():
    for name, cfg in config.SOURCES.items():
        state = "on " if cfg.get("enabled") else "off"
        print(f"  [{state}] {name:16} {cfg['label']:18} "
              f"{cfg['delay']:.0f}s+{cfg['jitter']:.0f}s between requests")


def cmd_suburbs():
    import locations
    data = locations.load()
    for slug, info in config.SUBURBS.items():
        have = [s for s in config.SOURCES if s == "property24"
                or (data.get(slug) or {}).get(s) or locations.get(s, slug)]
        print(f"  {slug:24} {info['name']:24} {len(have)} portal(s)")


def cmd_row(ident, sets, cols_spec, want_header, print_only):
    """Copy one spreadsheet row to the clipboard, ready to paste."""
    import sheets
    columns = sheets.parse_columns(cols_spec) if cols_spec else None

    fields = {}
    if ident:
        with db.connect() as conn:
            fields = sheets.fields_for(conn, ident) or {}
        if not fields:
            print(f"  no property found for {ident!r} "
                  f"(try a group id from the dashboard, or a listing key)")
            return
    # --set wins over the database, so you can correct a field on the way out
    for pair in sets:
        key, _, value = pair.partition("=")
        fields[key.strip()] = value

    line = sheets.tsv_row(fields, columns)
    text = (sheets.tsv_header(columns) + "\n" + line) if want_header else line

    cols = columns or sheets.COLUMNS
    width = max(len(h) for _, h in cols)
    for (key, header), cell in zip(cols, line.split("\t")):
        print(f"  {header:{width}}  {cell}")

    if print_only:
        return
    if sheets.to_clipboard(text):
        n = len(cols)
        print(f"\n  copied {n} columns to the clipboard — "
              f"click the first cell of an empty row in Excel or Google "
              f"Sheets and press Cmd+V")
    else:
        print("\n  could not reach the clipboard; here is the raw row:")
        print(text)


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "run"
    rest = args[1:]

    use_ai = "--no-ai" not in rest
    limit = int(_flag_value(rest, "--limit", 0) or 0) or None
    pages = int(_flag_value(rest, "--pages", config.MAX_PAGES_PER_SUBURB))
    src_arg = _flag_value(rest, "--sources")
    source_names = ([s.strip() for s in src_arg.split(",") if s.strip()]
                    if src_arg else None)

    cols_spec = _flag_value(rest, "--cols")
    sets = [rest[i + 1] for i, a in enumerate(rest)
            if a == "--set" and i + 1 < len(rest)]
    sets += [a.split("=", 1)[1] for a in rest if a.startswith("--set=")]

    skip = {"--limit", "--pages", "--sources", "--cols", "--set"}
    positional, skip_next = [], False
    for a in rest:
        if skip_next:
            skip_next = False
            continue
        if a in skip:
            skip_next = True
            continue
        if a.startswith("--"):
            continue
        positional.append(a)

    if cmd == "scrape":
        cmd_run(positional, source_names, pages, use_ai, do_score=False)
    elif cmd == "run":
        cmd_run(positional, source_names, pages, use_ai, do_score=True,
                only_stale="--new-only" in rest)
        # erf + GV valuations run inside pipeline.run now, for every property.
        cmd_report(include_sole="--all" in rest)
    elif cmd == "dedupe":
        cmd_dedupe()
    elif cmd == "erf":
        cmd_erf(include_all="--all" in rest, force="--force" in rest)
    elif cmd == "cma":
        cmd_cma(positional[0] if positional else None,
                include_all="--all" in rest)
    elif cmd == "gv":
        cmd_gv(force="--force" in rest)
    elif cmd == "lifecycle":
        cmd_lifecycle()
    elif cmd == "score":
        cmd_score(use_ai, limit, only_stale="--new-only" in rest)
    elif cmd == "report":
        cmd_report(include_sole="--all" in rest)
    elif cmd == "discover-locations":
        import locations
        locations.discover(positional or None)
    elif cmd == "import-tracker":
        if not positional:
            print("usage: python main.py import-tracker <xlsx>")
            return
        cmd_import_tracker(positional[0])
    elif cmd == "row":
        cmd_row(positional[0] if positional else None, sets, cols_spec,
                "--header" in rest, "--print" in rest)
    elif cmd == "sources":
        cmd_sources()
    elif cmd == "suburbs":
        cmd_suburbs()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
