-- Migration 006: why each value is absent (issue #29). The coverage snapshot writes one row per
-- value the coverage measures but the database doesn't hold, with the reason, so an absent
-- value that doesn't exist (the company wasn't listed yet, a bank has no capex, the statements
-- have no such line) is told apart from a real gap. The table holds the latest snapshot only.

CREATE TABLE out_coverage_gap (
    snapshot_date   DATE NOT NULL,
    symbol          TEXT NOT NULL,
    item            TEXT NOT NULL,
    period          TEXT NOT NULL,      -- 'FY2024' (fiscal year) or '2026-06' (quarter end)
    period_type     TEXT NOT NULL CHECK (period_type IN ('FY', 'Q', 'I')),
    status          TEXT NOT NULL CHECK (status IN ('before_listing', 'not_applicable',
                                                    'not_reported', 'explained', 'missing')),
    reason          TEXT,               -- the rule's reason, or the listing date
    PRIMARY KEY (symbol, item, period, period_type)
);
CREATE INDEX out_coverage_gap_status ON out_coverage_gap (status, item);
