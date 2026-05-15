"""Reconcile proxy costs against provider invoice.

Usage:
    python -m backend.scripts.reconcile_proxy_costs --invoice-gb 5.0
    python -m backend.scripts.reconcile_proxy_costs --invoice-gb 5.0 --month 2025-03
"""

import argparse
import sys
from datetime import datetime, timezone

from backend import storage
from backend.quotas import SupabaseQuotaStore


def _month_window(month_str: str) -> tuple[str, str]:
    year, month = month_str.split("-")
    start = datetime(int(year), int(month), 1, tzinfo=timezone.utc)
    if month == "12":
        end = datetime(int(year) + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(int(year), int(month) + 1, 1, tzinfo=timezone.utc)
    return start.isoformat(), end.isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile proxy costs against invoice")
    parser.add_argument("--invoice-gb", type=float, required=True, help="Invoice GB from provider")
    parser.add_argument("--month", type=str, default=None, help="Month to reconcile (YYYY-MM)")
    args = parser.parse_args()

    backend = storage.get_storage_backend()
    if not isinstance(backend, storage.SupabaseStorageBackend):
        print("Error: only Supabase backend is supported for cost reconciliation")
        sys.exit(1)

    quota_store = SupabaseQuotaStore(backend)
    now = datetime.now(timezone.utc)
    month_str = args.month or now.strftime("%Y-%m")
    start_iso, end_iso = _month_window(month_str)

    rows = backend._select(
        "usage_events",
        select="proxy_provider,proxy_bytes",
        filters={
            "event_type": backend._eq("transcript_fetch"),
            "created_at": f"gte.{start_iso}",
            "proxy_bytes": "gt.0",
        },
        limit=50000,
    )

    total_bytes = 0
    by_provider: dict[str, int] = {}
    for row in rows:
        b = int(row.get("proxy_bytes") or 0)
        provider = str(row.get("proxy_provider") or "unknown")
        by_provider[provider] = by_provider.get(provider, 0) + b
        total_bytes += b

    tracked_gb = total_bytes / (1024**3)
    invoice_gb = args.invoice_gb
    discrepancy_pct = ((tracked_gb - invoice_gb) / invoice_gb * 100) if invoice_gb else 0.0

    print(f"=== Proxy Cost Reconciliation — {month_str} ===")
    print(f"Total tracked:      {tracked_gb:.3f} GB ({total_bytes:,} bytes)")
    print(f"Invoice GB:         {invoice_gb:.3f} GB")
    print(f"Discrepancy:        {discrepancy_pct:+.2f}%")
    print()
    print("Per-provider breakdown:")
    for provider, b in sorted(by_provider.items(), key=lambda x: x[1], reverse=True):
        gb = b / (1024**3)
        pct = (b / total_bytes * 100) if total_bytes else 0.0
        print(f"  {provider:20s}  {gb:.3f} GB  ({pct:.1f}%)")


if __name__ == "__main__":
    main()
