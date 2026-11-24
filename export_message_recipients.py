#!/usr/bin/env python3
"""Export recipient counts from the OLÁ v1 messages API using Python 3.9+.

Examples (the API key is requested with a hidden prompt):
    python3 export_message_recipients.py --status failed --page 1 --limit 100
    python3 export_message_recipients.py --status sent --page 1 --limit 100 \
        --all-pages --output sent_recipients.csv

Authentication can also come from KATEMBE_API_KEY or --api-key. The hidden
prompt avoids putting the key in command history or process arguments.
Counts cover only fetched pages. Recipients are kept as strings, with outer
whitespace removed. Different message IDs count as separate messages.
"""

import argparse
import base64
import csv
import getpass
import json
import math
import os
from collections import Counter
from pathlib import Path
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_BASE_URL = "https://api.ola.pavulla.com"
STATUSES = (
    "draft", "submitted", "validating", "queued", "processing", "sending",
    "sent", "retrying", "failed", "scheduled", "cancelled", "awaiting_balance",
)


class ExportError(Exception):
    """An error safe to display without credentials or API response bodies."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ExportError("The API redirected the request. Check --base-url.")


def positive_integer(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def positive_timeout(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive number of seconds")
    return number


def parser():
    args = argparse.ArgumentParser(
        description="Export each recipient once, with its message count, to CSV.",
        epilog=(
            "The status is sent directly to the API. This v1 server filters by "
            "stored status: 'sent' includes messages with delivery receipts. "
            "'pending' and 'delivered' are display statuses, not supported filters. "
            "Page-based listing is not a snapshot; avoid changing the message "
            "list during a multi-page export."
        ),
    )
    args.add_argument("--api-key", help="API key; otherwise use KATEMBE_API_KEY or the hidden prompt")
    args.add_argument("--status", required=True, choices=STATUSES, help="stored message status")
    args.add_argument("--page", type=positive_integer, default=1, help="page to fetch or start from (default: 1)")
    args.add_argument("--limit", type=positive_integer, default=100, help="messages per page, 1–100 (default: 100)")
    args.add_argument("--all-pages", action="store_true", help="continue from --page until has_more is false")
    args.add_argument("--output", type=Path, default=Path("recipients.csv"), help="CSV output path (default: recipients.csv)")
    args.add_argument("--base-url", default=DEFAULT_BASE_URL, help="HTTPS API origin, without /v1/messages")
    args.add_argument("--timeout", type=positive_timeout, default=30.0, help="request timeout in seconds (default: 30)")
    return args


def fetch_page(opener, base_url, key, status, page, limit, timeout):
    query = urlencode({"status": status, "page": page, "limit": limit})
    authorization = base64.b64encode((key + ":").encode("utf-8")).decode("ascii")
    request = Request(
        base_url + "/v1/messages?" + query,
        headers={"Accept": "application/json", "Authorization": "Basic " + authorization},
        method="GET",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        code = exc.code
        exc.close()
        raise ExportError(f"API returned HTTP {code} on page {page}.") from None
    except (URLError, TimeoutError, OSError):
        raise ExportError(f"Could not reach the API or the request timed out on page {page}.") from None
    except (ValueError, UnicodeError):
        raise ExportError(f"API returned invalid JSON on page {page}.") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ExportError(f"Expected a JSON object containing a data list on page {page}.")
    if not isinstance(payload.get("has_more"), bool):
        raise ExportError(f"Missing or invalid has_more on page {page}.")
    if payload.get("page", page) != page or payload.get("limit", limit) != limit:
        raise ExportError(f"The API did not honour the requested page/limit on page {page}.")
    return payload


def collect(args, key):
    counts = Counter()
    seen_ids = set()
    missing_recipient = 0
    pages = 0
    page = args.page
    opener = build_opener(NoRedirects())
    while True:
        payload = fetch_page(opener, args.base_url, key, args.status, page, args.limit, args.timeout)
        new_messages = 0
        for message in payload["data"]:
            if not isinstance(message, dict) or not isinstance(message.get("id"), str) or not message["id"]:
                raise ExportError(f"A message is missing its ID on page {page}.")
            if message["id"] in seen_ids:
                continue
            seen_ids.add(message["id"])
            new_messages += 1
            recipient = message.get("recipient")
            if recipient is None or recipient == "":
                missing_recipient += 1
                continue
            if not isinstance(recipient, str):
                raise ExportError(f"A recipient is not a string on page {page}.")
            recipient = recipient.strip()
            if recipient:
                counts[recipient] += 1
            else:
                missing_recipient += 1
        pages += 1
        if not args.all_pages or not payload["has_more"]:
            return counts, pages, missing_recipient, payload["has_more"]
        if new_messages == 0:
            raise ExportError(f"Pagination made no progress on page {page}; export stopped.")
        page += 1


def write_csv(path, counts):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent,
            prefix=".recipient-export-", suffix=".tmp", delete=False,
        ) as output:
            temporary = Path(output.name)
            writer = csv.writer(output)
            writer.writerow(["recipient", "message_count"])
            for recipient, count in sorted(counts.items(), key=lambda row: (-row[1], row[0])):
                writer.writerow([recipient, count])
        os.replace(temporary, path)
    except OSError:
        raise ExportError("Could not write the CSV. Check the output folder and permissions.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if args.limit > 100:
        argument_parser.error("--limit cannot exceed the v1 API maximum of 100")
    url = urlsplit(args.base_url)
    if url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment:
        argument_parser.error("--base-url must be an HTTPS URL without credentials, query parameters, or a fragment")
    args.base_url = args.base_url.rstrip("/")
    try:
        key = args.api_key or os.environ.get("KATEMBE_API_KEY") or getpass.getpass("API key: ")
        if not key or key != key.strip() or ":" in key or any(ch.isspace() for ch in key):
            raise ExportError("Provide a nonempty API key without whitespace or a colon.")
        counts, pages, skipped, has_more = collect(args, key)
        write_csv(args.output, counts)
    except (ExportError, EOFError) as exc:
        message = str(exc) if isinstance(exc, ExportError) else "API key input was unavailable."
        print("Error: " + message, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Export cancelled.", file=sys.stderr)
        return 130
    print(f"Exported {len(counts)} unique recipients from {sum(counts.values())} messages across {pages} page(s).")
    if skipped:
        print(f"Skipped {skipped} message(s) without a recipient.")
    if has_more:
        print("More pages exist. Use --all-pages to include subsequent pages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
