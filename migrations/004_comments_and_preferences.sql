-- ============================================================================
-- MIGRATION 004: Match comments + user sport/league preferences
-- ============================================================================
-- Run in Supabase SQL Editor AFTER 003_subscriptions.sql
--
-- Two features, both keyed to an authenticated user:
--
--   match_comments    — readers add context a model cannot see ("first-choice
--                       setter is out", "this Liga Pro table is indoors today").
--                       Public to read, one author per row, author or backend
--                       may delete.
--   user_preferences  — which sports and leagues a reader follows, so the board
--                       can lead with them instead of 670 events in time order.
--
-- Comments are user-generated content on a paid product, so the guards are part
-- of the schema rather than left to the API: a length ceiling, a per-author
-- uniqueness-free but rate-limitable timestamp, and a soft-delete flag so
-- removing abuse keeps the audit trail.
-- ============================================================================

-- ── Comments ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS match_comments (
    id BIGSERIAL PRIMARY KEY,
    -- The match id the API exposes. Not a foreign key: matches live in JSON
    -- files, not in Postgres, and a comment must survive a re-scrape.
    match_key TEXT NOT NULL,
    user_id UUID NOT NULL,
    -- Shown next to the comment. Denormalised on purpose: auth.users is not
    -- readable from the client, and a comment with no visible author is useless.
    author_label TEXT,
    body TEXT NOT NULL CHECK (char_length(btrim(body)) BETWEEN 1 AND 1000),
    -- Set instead of deleting, so moderation leaves a trail.
    is_hidden BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- The only read pattern: newest comments for one match.
CREATE INDEX IF NOT EXISTS idx_match_comments_match
    ON match_comments(match_key, created_at DESC);
-- Rate limiting and "my comments" both filter by author and time.
CREATE INDEX IF NOT EXISTS idx_match_comments_author
    ON match_comments(user_id, created_at DESC);

ALTER TABLE match_comments ENABLE ROW LEVEL SECURITY;

-- Anyone may read comments that have not been hidden.
DROP POLICY IF EXISTS "Anyone reads visible comments" ON match_comments;
CREATE POLICY "Anyone reads visible comments" ON match_comments
    FOR SELECT USING (
        is_hidden = FALSE OR auth.uid() = user_id OR auth.role() = 'service_role'
    );

-- A signed-in reader may post, but only as themselves.
DROP POLICY IF EXISTS "Users write own comments" ON match_comments;
CREATE POLICY "Users write own comments" ON match_comments
    FOR INSERT WITH CHECK (
        auth.uid() = user_id OR auth.role() = 'service_role'
    );

-- Authors edit and remove their own; the backend can moderate any.
DROP POLICY IF EXISTS "Authors update own comments" ON match_comments;
CREATE POLICY "Authors update own comments" ON match_comments
    FOR UPDATE USING (
        auth.uid() = user_id OR auth.role() = 'service_role'
    ) WITH CHECK (
        auth.uid() = user_id OR auth.role() = 'service_role'
    );

DROP POLICY IF EXISTS "Authors delete own comments" ON match_comments;
CREATE POLICY "Authors delete own comments" ON match_comments
    FOR DELETE USING (
        auth.uid() = user_id OR auth.role() = 'service_role'
    );

-- ── Preferences ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id UUID PRIMARY KEY,
    -- Sport keys exactly as the API reports them ('football', 'table_tennis').
    sports TEXT[] NOT NULL DEFAULT '{}',
    -- League names as they appear on the events, matched exactly.
    leagues TEXT[] NOT NULL DEFAULT '{}',
    -- Whether the reader has been through the questionnaire, so it is not shown
    -- again to someone who deliberately chose nothing.
    onboarded BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users read own preferences" ON user_preferences;
CREATE POLICY "Users read own preferences" ON user_preferences
    FOR SELECT USING (
        auth.uid() = user_id OR auth.role() = 'service_role'
    );

DROP POLICY IF EXISTS "Users write own preferences" ON user_preferences;
CREATE POLICY "Users write own preferences" ON user_preferences
    FOR ALL USING (
        auth.uid() = user_id OR auth.role() = 'service_role'
    ) WITH CHECK (
        auth.uid() = user_id OR auth.role() = 'service_role'
    );

-- ============================================================================
-- CONFIRMATION
-- ============================================================================
SELECT 'Migration 004 complete' as status;
