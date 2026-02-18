#!/usr/bin/env python3
"""
SAP Transport Delta List Generator

Automates the process of identifying delta transports that need to be
reimported into the Test system after a system refresh (database restore)
from Production.

System Landscape:
    Development (DE1) -> Test (TE1) -> Production (PE1)

After refreshing TE1 from PE1's database backup, transports that were in TE1
but not yet in PE1 are lost. This script identifies those "delta" transports.

Input:
    - Transport history export from Test system (TE1) as CSV
    - Transport history export from Production system (PE1) as CSV

    CSV columns expected: Request, Short Text
    (At minimum these two columns; additional columns are preserved in output)

Logic:
    1. Find transports present in TE1 but NOT in PE1 (raw delta)
    2. For each delta transport, check if it is a Transport of Copies (ToC)
       by parsing "ToC from <TRANSPORT_ID>" pattern in Short Text
    3. If it IS a ToC:
       - Look up the main/original transport referenced in the ToC description
       - If the main transport is NOT in PE1 -> INCLUDE the ToC in reimport list
       - If the main transport IS in PE1 -> EXCLUDE the ToC (already covered)
    4. If it is NOT a ToC -> INCLUDE in reimport list (standard delta transport)

Output:
    - CSV file containing the delta transport reimport list
    - HTML report (interactive, color-coded, shareable)
    - Summary report printed to console
"""

import argparse
import csv
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime


# Pattern to detect Transport of Copies in the Short Text field
# Matches: "ToC from DEVK935391" or "ToC from DEVK935391 : <description>"
TOC_PATTERN = re.compile(
    r"ToC\s+from\s+([A-Z0-9]{3,4}K\d{6})",
    re.IGNORECASE
)


def read_transport_csv(filepath):
    """
    Read a transport history CSV file and return a dict keyed by transport
    request ID.

    Args:
        filepath: Path to the CSV file

    Returns:
        OrderedDict mapping request ID -> dict of row data
    """
    transports = OrderedDict()

    if not os.path.exists(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    with open(filepath, newline="", encoding="utf-8-sig") as f:
        # Try to detect delimiter
        sample = f.read(2048)
        f.seek(0)

        sniffer = csv.Sniffer()
        try:
            dialect = sniffer.sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel  # fallback to comma-separated

        reader = csv.DictReader(f, dialect=dialect)

        # Normalize header names: strip whitespace and lowercase for matching
        if reader.fieldnames is None:
            print(f"ERROR: Could not read headers from {filepath}", file=sys.stderr)
            sys.exit(1)

        # Build a mapping from normalized name to original name
        header_map = {}
        for name in reader.fieldnames:
            header_map[name.strip().lower()] = name

        # Find the request and short text columns
        request_col = None
        short_text_col = None

        for normalized, original in header_map.items():
            if normalized in ("request", "transport", "transport request",
                              "request id", "transport_request", "tr"):
                request_col = original
            if normalized in ("short text", "description", "short_text",
                              "short text for request", "text", "desc"):
                short_text_col = original

        if request_col is None:
            print(f"ERROR: Could not find 'Request' column in {filepath}",
                  file=sys.stderr)
            print(f"  Available columns: {reader.fieldnames}", file=sys.stderr)
            sys.exit(1)

        if short_text_col is None:
            print(f"ERROR: Could not find 'Short Text' column in {filepath}",
                  file=sys.stderr)
            print(f"  Available columns: {reader.fieldnames}", file=sys.stderr)
            sys.exit(1)

        for row in reader:
            request_id = row[request_col].strip()
            if request_id:
                transports[request_id] = {
                    "request": request_id,
                    "short_text": row[short_text_col].strip() if row.get(short_text_col) else "",
                    "_raw": row  # preserve all original columns
                }

    return transports


def extract_toc_main_transport(short_text):
    """
    Check if a transport's short text indicates it is a Transport of Copies.

    Args:
        short_text: The short text / description of the transport

    Returns:
        The main transport request ID if this is a ToC, else None
    """
    match = TOC_PATTERN.search(short_text)
    if match:
        return match.group(1).upper()
    return None


def compute_delta_transports(te1_transports, pe1_transports):
    """
    Compute the delta transport list: transports in TE1 not in PE1,
    with ToC logic applied.

    Args:
        te1_transports: dict of transports from Test system
        pe1_transports: dict of transports from Production system

    Returns:
        Tuple of:
          - list of dicts for transports to reimport (the delta list)
          - list of dicts for excluded transports (with exclusion reason)
    """
    pe1_ids = set(pe1_transports.keys())
    reimport_list = []
    excluded_list = []

    for request_id, transport in te1_transports.items():
        # Step 1: If transport is in PE1, it will be restored with the
        # database refresh — no reimport needed
        if request_id in pe1_ids:
            excluded_list.append({
                **transport,
                "reason": "Already in Production (PE1) - will be in refreshed DB"
            })
            continue

        # Step 2: Transport is in TE1 but NOT in PE1 — candidate for reimport
        short_text = transport["short_text"]
        main_transport_id = extract_toc_main_transport(short_text)

        if main_transport_id is not None:
            # This is a Transport of Copies
            # Check if the MAIN transport is in PE1
            if main_transport_id in pe1_ids:
                excluded_list.append({
                    **transport,
                    "reason": (
                        f"ToC - main transport {main_transport_id} is in "
                        f"Production (PE1), no reimport needed"
                    )
                })
            else:
                # Main transport is NOT in PE1 — include the ToC
                reimport_list.append({
                    **transport,
                    "is_toc": True,
                    "main_transport": main_transport_id,
                    "note": f"ToC of {main_transport_id} (main not in PE1)"
                })
        else:
            # Regular transport, not a ToC — include in reimport list
            reimport_list.append({
                **transport,
                "is_toc": False,
                "main_transport": "",
                "note": "Direct transport (not in PE1)"
            })

    return reimport_list, excluded_list


def write_output_csv(filepath, transports, fieldnames):
    """Write a list of transport dicts to a CSV file."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for t in transports:
            writer.writerow(t)


def print_summary(reimport_list, excluded_list, te1_count, pe1_count):
    """Print a summary report to the console."""
    print("=" * 70)
    print("  SAP TRANSPORT DELTA LIST — SUMMARY REPORT")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()
    print(f"  Transports in Test system (TE1):        {te1_count}")
    print(f"  Transports in Production system (PE1):  {pe1_count}")
    print()
    print(f"  Delta transports to REIMPORT:           {len(reimport_list)}")

    toc_count = sum(1 for t in reimport_list if t.get("is_toc"))
    direct_count = len(reimport_list) - toc_count
    print(f"    - Direct transports:                  {direct_count}")
    print(f"    - Transport of Copies (ToC):          {toc_count}")

    print(f"  Excluded transports:                    {len(excluded_list)}")
    print()

    if reimport_list:
        print("-" * 70)
        print("  TRANSPORTS TO REIMPORT:")
        print("-" * 70)
        for i, t in enumerate(reimport_list, 1):
            toc_marker = " [ToC]" if t.get("is_toc") else ""
            print(f"  {i:4d}. {t['request']}{toc_marker}")
            print(f"        {t['short_text']}")
            if t.get("main_transport"):
                print(f"        Main transport: {t['main_transport']}")
            print()

    if excluded_list:
        print("-" * 70)
        print("  EXCLUDED TRANSPORTS (no reimport needed):")
        print("-" * 70)
        for i, t in enumerate(excluded_list, 1):
            print(f"  {i:4d}. {t['request']}")
            print(f"        {t['short_text']}")
            print(f"        Reason: {t['reason']}")
            print()

    print("=" * 70)


def generate_html_report(reimport_list, excluded_list, te1_count, pe1_count,
                         output_path):
    """Generate an interactive HTML report of the delta transport analysis."""
    toc_count = sum(1 for t in reimport_list if t.get("is_toc"))
    direct_count = len(reimport_list) - toc_count
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build reimport table rows
    reimport_rows = ""
    for i, t in enumerate(reimport_list, 1):
        toc_badge = ('<span class="badge toc">ToC</span>' if t.get("is_toc")
                     else '<span class="badge direct">Direct</span>')
        main_ref = (f'<span class="mono">{t["main_transport"]}</span>'
                    if t.get("main_transport") else "-")
        reimport_rows += f"""
        <tr>
          <td>{i}</td>
          <td class="mono">{t['request']}</td>
          <td>{t['short_text']}</td>
          <td>{toc_badge}</td>
          <td>{main_ref}</td>
          <td>{t.get('note', '')}</td>
        </tr>"""

    # Build excluded table rows
    excluded_rows = ""
    for i, t in enumerate(excluded_list, 1):
        excluded_rows += f"""
        <tr>
          <td>{i}</td>
          <td class="mono">{t['request']}</td>
          <td>{t['short_text']}</td>
          <td>{t['reason']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SAP Transport Delta Report</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      background: #f0f2f5;
      color: #1a1a2e;
      padding: 20px;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    header {{
      background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
      color: #fff;
      padding: 30px 40px;
      border-radius: 12px;
      margin-bottom: 24px;
    }}
    header h1 {{ font-size: 1.8em; margin-bottom: 4px; }}
    header .subtitle {{ opacity: 0.8; font-size: 0.95em; }}
    header .timestamp {{ opacity: 0.6; font-size: 0.85em; margin-top: 8px; }}

    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .stat-card {{
      background: #fff;
      border-radius: 10px;
      padding: 20px 24px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.06);
      border-left: 4px solid #0f3460;
    }}
    .stat-card.reimport {{ border-left-color: #e94560; }}
    .stat-card.toc {{ border-left-color: #f5a623; }}
    .stat-card.direct {{ border-left-color: #27ae60; }}
    .stat-card.excluded {{ border-left-color: #95a5a6; }}
    .stat-card .label {{ font-size: 0.85em; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
    .stat-card .value {{ font-size: 2em; font-weight: 700; margin-top: 4px; }}
    .stat-card.reimport .value {{ color: #e94560; }}
    .stat-card.toc .value {{ color: #f5a623; }}
    .stat-card.direct .value {{ color: #27ae60; }}

    .section {{
      background: #fff;
      border-radius: 10px;
      padding: 24px;
      margin-bottom: 24px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }}
    .section h2 {{
      font-size: 1.2em;
      margin-bottom: 16px;
      padding-bottom: 10px;
      border-bottom: 2px solid #f0f2f5;
    }}
    .section h2.reimport {{ color: #e94560; }}
    .section h2.excluded {{ color: #95a5a6; }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9em;
    }}
    thead th {{
      background: #f8f9fa;
      padding: 10px 12px;
      text-align: left;
      font-weight: 600;
      color: #555;
      border-bottom: 2px solid #e9ecef;
      position: sticky;
      top: 0;
    }}
    tbody tr {{ border-bottom: 1px solid #f0f2f5; }}
    tbody tr:hover {{ background: #f8f9fb; }}
    tbody td {{ padding: 10px 12px; vertical-align: top; }}

    .mono {{ font-family: 'Courier New', Courier, monospace; font-weight: 600; }}
    .badge {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 12px;
      font-size: 0.8em;
      font-weight: 600;
    }}
    .badge.toc {{ background: #fff3e0; color: #e65100; }}
    .badge.direct {{ background: #e8f5e9; color: #2e7d32; }}

    .filter-bar {{
      display: flex;
      gap: 10px;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }}
    .filter-btn {{
      padding: 6px 16px;
      border: 2px solid #e0e0e0;
      background: #fff;
      border-radius: 20px;
      cursor: pointer;
      font-size: 0.85em;
      font-weight: 500;
      transition: all 0.2s;
    }}
    .filter-btn:hover {{ border-color: #0f3460; color: #0f3460; }}
    .filter-btn.active {{ background: #0f3460; color: #fff; border-color: #0f3460; }}

    .search-box {{
      padding: 8px 16px;
      border: 2px solid #e0e0e0;
      border-radius: 8px;
      font-size: 0.9em;
      width: 280px;
      outline: none;
      transition: border-color 0.2s;
    }}
    .search-box:focus {{ border-color: #0f3460; }}

    .landscape {{
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 16px 0;
      font-size: 0.95em;
    }}
    .sys-box {{
      padding: 8px 18px;
      border-radius: 8px;
      font-weight: 600;
      color: #fff;
    }}
    .sys-dev {{ background: #2196f3; }}
    .sys-test {{ background: #ff9800; }}
    .sys-prod {{ background: #4caf50; }}
    .arrow {{ font-size: 1.4em; color: #999; }}

    footer {{
      text-align: center;
      color: #999;
      font-size: 0.8em;
      padding: 20px;
    }}

    @media print {{
      body {{ background: #fff; padding: 10px; }}
      header {{ background: #1a1a2e !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
      .filter-bar, .search-box {{ display: none; }}
      .section {{ box-shadow: none; border: 1px solid #ddd; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>SAP Transport Delta Report</h1>
      <div class="subtitle">System Refresh: Production (PE1) &rarr; Test (TE1)</div>
      <div class="landscape">
        <span class="sys-box sys-dev">DEV (DE1)</span>
        <span class="arrow">&rarr;</span>
        <span class="sys-box sys-test">TEST (TE1)</span>
        <span class="arrow">&rarr;</span>
        <span class="sys-box sys-prod">PROD (PE1)</span>
      </div>
      <div class="timestamp">Generated: {timestamp}</div>
    </header>

    <div class="stats-grid">
      <div class="stat-card">
        <div class="label">Test System (TE1)</div>
        <div class="value">{te1_count}</div>
      </div>
      <div class="stat-card">
        <div class="label">Production (PE1)</div>
        <div class="value">{pe1_count}</div>
      </div>
      <div class="stat-card reimport">
        <div class="label">Delta Reimport</div>
        <div class="value">{len(reimport_list)}</div>
      </div>
      <div class="stat-card toc">
        <div class="label">ToC Transports</div>
        <div class="value">{toc_count}</div>
      </div>
      <div class="stat-card direct">
        <div class="label">Direct Transports</div>
        <div class="value">{direct_count}</div>
      </div>
      <div class="stat-card excluded">
        <div class="label">Excluded</div>
        <div class="value">{len(excluded_list)}</div>
      </div>
    </div>

    <div class="section">
      <h2 class="reimport">Transports to Reimport ({len(reimport_list)})</h2>
      <div class="filter-bar">
        <input type="text" class="search-box" id="searchReimport"
               placeholder="Search transports..." oninput="filterTable('reimportTable', this.value, currentFilter)">
        <button class="filter-btn active" onclick="setFilter('all', this)">All</button>
        <button class="filter-btn" onclick="setFilter('toc', this)">ToC Only</button>
        <button class="filter-btn" onclick="setFilter('direct', this)">Direct Only</button>
      </div>
      <table id="reimportTable">
        <thead>
          <tr>
            <th>#</th>
            <th>Request</th>
            <th>Short Text</th>
            <th>Type</th>
            <th>Main Transport</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>{reimport_rows}
        </tbody>
      </table>
    </div>

    <div class="section">
      <h2 class="excluded">Excluded Transports ({len(excluded_list)})</h2>
      <input type="text" class="search-box" id="searchExcluded"
             placeholder="Search excluded..." oninput="filterTable('excludedTable', this.value, 'all')"
             style="margin-bottom:16px">
      <table id="excludedTable">
        <thead>
          <tr>
            <th>#</th>
            <th>Request</th>
            <th>Short Text</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>{excluded_rows}
        </tbody>
      </table>
    </div>

    <footer>
      SAP Transport Delta List Generator &mdash; Auto-generated report
    </footer>
  </div>

  <script>
    let currentFilter = 'all';

    function setFilter(type, btn) {{
      currentFilter = type;
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const searchVal = document.getElementById('searchReimport').value;
      filterTable('reimportTable', searchVal, type);
    }}

    function filterTable(tableId, search, typeFilter) {{
      const table = document.getElementById(tableId);
      const rows = table.querySelectorAll('tbody tr');
      const term = search.toLowerCase();

      rows.forEach(row => {{
        const text = row.textContent.toLowerCase();
        const matchesSearch = !term || text.includes(term);
        let matchesType = true;

        if (typeFilter === 'toc') {{
          matchesType = row.querySelector('.badge.toc') !== null;
        }} else if (typeFilter === 'direct') {{
          matchesType = row.querySelector('.badge.direct') !== null;
        }}

        row.style.display = (matchesSearch && matchesType) ? '' : 'none';
      }});
    }}
  </script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    parser = argparse.ArgumentParser(
        description="SAP Transport Delta List Generator - Identifies transports "
                    "to reimport after system refresh from Production to Test.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --te1 te1_transports.csv --pe1 pe1_transports.csv
  %(prog)s --te1 te1_transports.csv --pe1 pe1_transports.csv --output delta_list.csv
  %(prog)s --te1 te1_transports.csv --pe1 pe1_transports.csv --excluded excluded.csv

CSV Format:
  Input files should have at least these columns:
    Request       - Transport request ID (e.g., DEVK935733)
    Short Text    - Description of the transport

  The tool auto-detects common column name variations and CSV delimiters.
        """
    )

    parser.add_argument(
        "--te1", required=True,
        help="Path to Test system (TE1) transport history CSV"
    )
    parser.add_argument(
        "--pe1", required=True,
        help="Path to Production system (PE1) transport history CSV"
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output CSV file for delta reimport list "
             "(default: delta_reimport_list_<timestamp>.csv)"
    )
    parser.add_argument(
        "--excluded", default=None,
        help="Optional: Output CSV file for excluded transports with reasons"
    )
    parser.add_argument(
        "--html", default=None,
        help="Output HTML report file (interactive, color-coded, shareable). "
             "Use --html auto to auto-name, or --html report.html for custom name"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Suppress detailed console output (only print file paths)"
    )

    args = parser.parse_args()

    # Read input files
    print(f"Reading Test system (TE1) transports from: {args.te1}")
    te1_transports = read_transport_csv(args.te1)
    print(f"  -> Found {len(te1_transports)} transports")

    print(f"Reading Production system (PE1) transports from: {args.pe1}")
    pe1_transports = read_transport_csv(args.pe1)
    print(f"  -> Found {len(pe1_transports)} transports")
    print()

    # Compute delta
    reimport_list, excluded_list = compute_delta_transports(
        te1_transports, pe1_transports
    )

    # Print summary
    if not args.quiet:
        print_summary(
            reimport_list, excluded_list,
            len(te1_transports), len(pe1_transports)
        )

    # Write output files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_path = args.output or f"delta_reimport_list_{timestamp}.csv"
    reimport_fields = ["request", "short_text", "is_toc", "main_transport", "note"]
    write_output_csv(output_path, reimport_list, reimport_fields)
    print(f"\nDelta reimport list written to: {output_path}")
    print(f"  -> {len(reimport_list)} transports to reimport")

    if args.excluded:
        excluded_fields = ["request", "short_text", "reason"]
        write_output_csv(args.excluded, excluded_list, excluded_fields)
        print(f"Excluded transports written to: {args.excluded}")
        print(f"  -> {len(excluded_list)} transports excluded")

    # Generate HTML report
    if args.html is not None:
        html_path = (f"delta_report_{timestamp}.html"
                     if args.html == "auto" else args.html)
        generate_html_report(
            reimport_list, excluded_list,
            len(te1_transports), len(pe1_transports),
            html_path
        )
        print(f"\nHTML report generated: {html_path}")
        print(f"  -> Open in a browser to view the interactive report")

    return 0 if reimport_list is not None else 1


if __name__ == "__main__":
    sys.exit(main())
