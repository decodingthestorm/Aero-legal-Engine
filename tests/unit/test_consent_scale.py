"""Characterises ConsentLedger's startup replay cost.

The README carried "untested at scale" for ConsentLedger since it was
written — an honest disclaimer, but a disclaimer is not a measurement,
and the thing it disclaims (a full WAL replay on every process start) is
on the startup path of every deployment.

These assert **scaling**, not wall-clock. A timing test with an absolute
threshold is a flaky test on a shared runner; the ratio of per-entry cost
between two sizes is scale-invariant, so a machine being twice as slow
moves both measurements equally and the ratio holds. That's the same
reasoning as tests/unit/test_hjb.py's convergence-rate check: assert the
exponent, not the constant.

Quadratic replay at 4x the entries would show ~4x the per-entry cost.
Linear shows ~1x. The band below sits between the two, and each
measurement is a best-of-three to blunt scheduling jitter.

Measured on the machine this was written on, for calibration rather than
assertion:

    entries   file size   disk load        replay
      2,000     1.09 MB    5.8 ms          1.36 ms
      8,000     4.36 MB   27.1 ms          4.17 ms
     32,000    17.47 MB  124.8 ms         18.03 ms

Both paths are linear. Disk load dominates at ~3.9 us/entry against
~0.6 us/entry for indexing. Extrapolating, a million-entry WAL costs
roughly five seconds of startup — tolerable — but ~546 bytes/entry means
that same log is ~550 MB held in memory, because WriteAheadLog keeps
every entry in a list. **Memory is the real ceiling here, not time**, and
neither this test nor the ledger does anything about it.
"""

from __future__ import annotations

import time

from legal_engine.compliance.consent import ConsentLedger
from legal_engine.core.key_signer import generate_signing_key
from legal_engine.core.wal import WriteAheadLog

_SMALL = 4_000
_LARGE = 16_000  # 4x, so quadratic growth would be unmistakable
_MAX_PER_ENTRY_GROWTH = 3.0
_REPEATS = 3


def _populated_wal(entry_count: int, tenant_count: int = 500) -> WriteAheadLog:
    wal = WriteAheadLog(generate_signing_key())
    for i in range(entry_count):
        wal.append(
            "legal_disclaimer_accepted",
            {
                "tenant_id": f"tenant-{i % tenant_count}",
                "subject": f"subject-{i}",
                "disclaimer_version": "v1",
            },
        )
    return wal


def _best_replay_seconds_per_entry(wal: WriteAheadLog, entry_count: int) -> float:
    """Best of several runs. The minimum is the right statistic for a
    benchmark: noise only ever makes a measurement slower, so the fastest
    observation is the closest to the true cost."""
    best = float("inf")
    for _ in range(_REPEATS):
        start = time.perf_counter()
        ConsentLedger(wal)
        best = min(best, time.perf_counter() - start)
    return best / entry_count


class TestReplayScaling:
    def test_replay_cost_per_entry_does_not_grow_with_log_size(self):
        small = _best_replay_seconds_per_entry(_populated_wal(_SMALL), _SMALL)
        large = _best_replay_seconds_per_entry(_populated_wal(_LARGE), _LARGE)

        growth = large / small
        assert growth < _MAX_PER_ENTRY_GROWTH, (
            f"per-entry replay cost grew {growth:.2f}x when the log grew "
            f"{_LARGE // _SMALL}x — replay is meant to be linear, and this "
            f"looks super-linear ({small * 1e6:.2f}us/entry -> {large * 1e6:.2f}us/entry)"
        )


class TestCorrectnessAtScale:
    def test_replay_indexes_every_tenant(self):
        wal = _populated_wal(_SMALL, tenant_count=250)
        ledger = ConsentLedger(wal)

        for tenant in range(250):
            assert ledger.has_accepted_current_disclaimer(f"tenant-{tenant}")

    def test_the_latest_acceptance_wins_across_many_supersessions(self):
        """Each tenant here accepts repeatedly. The projection keeps only
        the most recent, and "most recent" has to survive replaying
        thousands of entries in order."""
        wal = _populated_wal(_SMALL, tenant_count=10)
        ledger = ConsentLedger(wal)

        # Entry i went to tenant i % 10, so the last entry for tenant t is
        # the highest i < _SMALL with i % 10 == t.
        for tenant in range(10):
            last_index = max(i for i in range(_SMALL) if i % 10 == tenant)
            record = ledger.latest_acceptance(f"tenant-{tenant}")
            assert record.subject == f"subject-{last_index}"

    def test_a_revocation_late_in_a_large_log_still_takes_effect(self):
        """The ordering property that matters most: a revocation buried
        among thousands of acceptances must not be lost."""
        wal = _populated_wal(_SMALL, tenant_count=100)
        ConsentLedger(wal).revoke_acceptance("tenant-7", reason="signer changed")

        replayed = ConsentLedger(wal)

        assert replayed.has_accepted_current_disclaimer("tenant-7") is False
        assert replayed.has_accepted_current_disclaimer("tenant-8") is True

    def test_rebuilding_reproduces_identical_state(self):
        """The property that justifies calling this a projection rather
        than a second source of truth, asserted at a size where an
        accidental dependence on insertion order would show up."""
        wal = _populated_wal(_SMALL, tenant_count=250)

        first = ConsentLedger(wal)
        second = ConsentLedger(wal)

        for tenant in range(250):
            name = f"tenant-{tenant}"
            assert first.latest_acceptance(name) == second.latest_acceptance(name)
