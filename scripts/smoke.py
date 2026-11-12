"""Smoke test for a running site: python scripts/smoke.py https://your-site.example

Prints PASS or FAIL per check and exits 1 if any fail. Reads only; changes nothing.
"""

import sys

import httpx


def main(base: str) -> int:
    base = base.rstrip("/")
    failed = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        failed += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}".rstrip())

    with httpx.Client(timeout=30.0, follow_redirects=True) as http:
        def get(path: str) -> httpx.Response | None:
            try:
                return http.get(base + path)
            except httpx.HTTPError as exc:
                check(f"GET {path}", False, type(exc).__name__)
                return None

        r = get("/health")
        if r is not None:
            check("GET /health", r.status_code == 200, str(r.status_code))
        r = get("/health/ready")
        if r is not None:
            check("GET /health/ready", r.status_code == 200, r.text[:80])
        r = get("/")
        if r is not None:
            check("GET / loads", r.status_code == 200 and "critiSizer" in r.text)
        r = get("/api/policies")
        slug = None
        if r is not None and r.status_code == 200:
            policies = r.json()
            check("GET /api/policies has policies", len(policies) > 0, f"{len(policies)}")
            slug = policies[0]["slug"] if policies else None
        elif r is not None:
            check("GET /api/policies", False, str(r.status_code))
        if slug:
            r = get(f"/api/policies/{slug}")
            if r is not None:
                check(f"GET policy {slug}", r.status_code == 200, str(r.status_code))
            r = get(f"/api/policies/{slug}/history")
            if r is not None:
                check("GET history", r.status_code == 200, str(r.status_code))
            r = get(f"/policies/{slug}")
            if r is not None:
                check(
                    "policy page carries the review note",
                    r.status_code == 200 and "AI-drafted, human-reviewed" in r.text,
                )
        r = get("/policies/no-such-policy-xyz")
        if r is not None:
            check("unknown policy page is 404", r.status_code == 404, str(r.status_code))

    print(f"\n{'all passed' if not failed else f'{failed} failed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/smoke.py <base-url>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))