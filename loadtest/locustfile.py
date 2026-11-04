"""Load scenario: mostly the policy list, some detail pages.

Reads only, so it never trips the rating rate limit and changes no data.
"""

import random

import requests
from locust import HttpUser, between, events, task

SLUGS: list[str] = []


@events.test_start.add_listener
def load_real_slugs(environment, **kwargs):
    """Fetch the real slugs once, before any simulated user starts."""
    response = requests.get(f"{environment.host}/api/policies", timeout=10)
    response.raise_for_status()
    SLUGS[:] = [policy["slug"] for policy in response.json()]
    if not SLUGS:
        raise RuntimeError("No policies found. Seed the database first.")


class Reader(HttpUser):
    # A short pause, so 50 users keep the server busy and we see its limit.
    wait_time = between(0.05, 0.2)

    @task(8)
    def list_policies(self):
        self.client.get("/api/policies", name="GET /api/policies")

    @task(2)
    def policy_detail(self):
        slug = random.choice(SLUGS)
        self.client.get(f"/api/policies/{slug}", name="GET /api/policies/{slug}")
