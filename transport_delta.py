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

    return 0 if reimport_list is not None else 1


if __name__ == "__main__":
    sys.exit(main())
