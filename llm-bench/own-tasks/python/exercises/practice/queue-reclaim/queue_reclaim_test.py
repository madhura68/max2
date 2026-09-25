import copy
import unittest

from queue_reclaim import reclaimable

NOW = 1_000_000


def msg(id, status="claimed", via="mcp", claimed_at=NOW - 1000, renewed=None, **extra):
    m = {"id": id, "status": status, "claimed_via": via, "claimed_at": claimed_at,
         "lease_renewed_at": renewed}
    m.update(extra)
    return m


class QueueReclaimTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(reclaimable([], NOW), [])

    def test_only_claimed_messages(self):
        ms = [msg(s, status=s, claimed_at=0) for s in ("pending", "done", "failed", "cancelled")]
        self.assertEqual(reclaimable(ms, NOW), [])

    def test_mcp_expired_without_renewal(self):
        self.assertEqual(reclaimable([msg("a", claimed_at=NOW - 301)], NOW), ["a"])

    def test_mcp_boundary_is_not_expired(self):
        self.assertEqual(reclaimable([msg("a", claimed_at=NOW - 300)], NOW), [])

    def test_mcp_renewal_keeps_claim_alive(self):
        self.assertEqual(reclaimable([msg("a", claimed_at=NOW - 5000, renewed=NOW - 10)], NOW), [])

    def test_mcp_stale_renewal_expires(self):
        self.assertEqual(reclaimable([msg("a", claimed_at=NOW - 5000, renewed=NOW - 301)], NOW), ["a"])

    def test_mcp_missing_renewal_key(self):
        m = msg("a", claimed_at=NOW - 400)
        del m["lease_renewed_at"]
        self.assertEqual(reclaimable([m], NOW), ["a"])

    def test_renewal_older_than_claim_uses_claim(self):
        # A renewal timestamp before the claim (clock skew, stale row) must not expire a fresh claim.
        self.assertEqual(reclaimable([msg("a", claimed_at=NOW - 10, renewed=NOW - 9999)], NOW), [])

    def test_cli_uses_claimed_at_only(self):
        ms = [msg("fresh", via="cli", claimed_at=NOW - 3600, renewed=None),
              msg("old", via="cli", claimed_at=NOW - 4 * 3600 - 1, renewed=NOW)]
        self.assertEqual(reclaimable(ms, NOW), ["old"])

    def test_cli_boundary(self):
        self.assertEqual(reclaimable([msg("a", via="cli", claimed_at=NOW - 4 * 3600)], NOW), [])

    def test_custom_timeouts(self):
        ms = [msg("m", claimed_at=NOW - 61), msg("c", via="cli", claimed_at=NOW - 121)]
        self.assertEqual(reclaimable(ms, NOW, cli_timeout=120, mcp_timeout=60), ["c", "m"])

    def test_unknown_owner_left_alone(self):
        ms = [msg("x", via="ssh", claimed_at=0), msg("y", via=None, claimed_at=0)]
        m = msg("z", claimed_at=0)
        del m["claimed_via"]
        self.assertEqual(reclaimable(ms + [m], NOW), [])

    def test_order_oldest_first_ties_by_id(self):
        ms = [msg("b", claimed_at=NOW - 900), msg("c", claimed_at=NOW - 2000),
              msg("a", claimed_at=NOW - 900), msg("d", via="cli", claimed_at=NOW - 90000)]
        self.assertEqual(reclaimable(ms, NOW), ["d", "c", "a", "b"])

    def test_input_not_modified(self):
        ms = [msg("a", claimed_at=NOW - 900), msg("b", via="cli", claimed_at=0)]
        before = copy.deepcopy(ms)
        reclaimable(ms, NOW)
        self.assertEqual(ms, before)


if __name__ == "__main__":
    unittest.main()
