from __future__ import annotations

import unittest

from rabotyaga_gateway.rate_limit import (
    RateLimit,
    RateLimitExceeded,
    SlidingWindowLimiter,
)


class SlidingWindowLimiterTests(unittest.TestCase):
    def test_rejects_limit_and_reports_retry_after(self) -> None:
        limiter = SlidingWindowLimiter()
        rule = RateLimit("pair", "203.0.113.10", 2, 60)

        limiter.check([rule], now=100)
        limiter.check([rule], now=110)

        with self.assertRaises(RateLimitExceeded) as captured:
            limiter.check([rule], now=120)
        self.assertEqual(captured.exception.retry_after, 40)

    def test_expired_events_no_longer_count(self) -> None:
        limiter = SlidingWindowLimiter()
        rule = RateLimit("submit", "device", 1, 10)

        limiter.check([rule], now=100)
        limiter.check([rule], now=110)

    def test_failed_multi_rule_check_does_not_consume_other_buckets(self) -> None:
        limiter = SlidingWindowLimiter()
        strict = RateLimit("strict", "source", 1, 60)
        roomy = RateLimit("roomy", "global", 2, 60)

        limiter.check([strict], now=100)
        with self.assertRaises(RateLimitExceeded):
            limiter.check([strict, roomy], now=101)

        limiter.check([roomy], now=102)
        limiter.check([roomy], now=103)


if __name__ == "__main__":
    unittest.main()
