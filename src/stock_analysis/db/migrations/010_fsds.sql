-- Migration 010: SEC's Financial Statement Data Sets in raw_sec_xbrl_fact (issue #29). The
-- quarterly files (one zip a quarter, every filing's numbers) give the facts company facts
-- leaves out, for every year at once: the companies' own tags (Dominion's "plant construction
-- and other property additions") and the values per share class. `statement` is the statement
-- the line is shown in (BS, IS, CF, EQ, CI), `custom` marks a company's own tag.

ALTER TABLE raw_sec_xbrl_fact ADD COLUMN statement TEXT;
ALTER TABLE raw_sec_xbrl_fact ADD COLUMN custom BOOLEAN NOT NULL DEFAULT FALSE;
