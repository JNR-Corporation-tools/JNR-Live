#!/usr/bin/env python3
"""Verify the protected release files in the current checkout."""
from backend.integrity import verify_integrity

result = verify_integrity()
print(f"Live Server integrity: {result['status']} ({result['checked']} files checked)")
if result.get("mismatches"):
    for item in result["mismatches"]:
        print(f" - {item['path']}: {item['reason']}")
raise SystemExit(0 if result["ok"] else 1)
