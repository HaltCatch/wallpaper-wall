from __future__ import annotations

import unittest

from app.rate_limit import SlidingWindowRateLimiter


class RateLimitTests(unittest.TestCase):
    def test_blocks_after_configured_attempts(self) -> None:
        limiter = SlidingWindowRateLimiter()
        self.assertIsNone(limiter.retry_after("login:user", 2, 60))
        self.assertIsNone(limiter.retry_after("login:user", 2, 60))
        self.assertGreaterEqual(limiter.retry_after("login:user", 2, 60) or 0, 1)


if __name__ == "__main__":
    unittest.main()
