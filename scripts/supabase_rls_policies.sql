-- ============================================================
-- Foxhound — Supabase RLS Policies
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- ============================================================

-- ─── 1. ENABLE RLS ON ALL TABLES ───

ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE application_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE interaction_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_listings ENABLE ROW LEVEL SECURITY;
ALTER TABLE waitlist_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE discovery_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE foxhound_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE foxhound_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE tinyfish_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_destinations ENABLE ROW LEVEL SECURITY;
ALTER TABLE dossiers ENABLE ROW LEVEL SECURITY;
ALTER TABLE foxhound_briefs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchdog_checks ENABLE ROW LEVEL SECURITY;
ALTER TABLE recon_dossiers ENABLE ROW LEVEL SECURITY;
ALTER TABLE tinyfish_brief_cache ENABLE ROW LEVEL SECURITY;


-- ─── 2. USER-SCOPED TABLES (direct user_id) ───
-- Users can only read/write their own rows.
-- The backend uses the service_role key which bypasses RLS,
-- so these policies only protect against direct anon key access.

-- user_profiles
CREATE POLICY "users_read_own_profile" ON user_profiles
  FOR SELECT USING (user_id = auth.uid()::text);
CREATE POLICY "users_update_own_profile" ON user_profiles
  FOR UPDATE USING (user_id = auth.uid()::text);
-- No INSERT via anon key — profile creation goes through the backend API
-- No DELETE — users can't delete profiles directly

-- applications
CREATE POLICY "users_read_own_applications" ON applications
  FOR SELECT USING (user_id = auth.uid()::text);
-- No INSERT/UPDATE/DELETE via anon key — all writes go through backend

-- job_matches
CREATE POLICY "users_read_own_matches" ON job_matches
  FOR SELECT USING (user_id = auth.uid()::text);
CREATE POLICY "users_update_own_matches" ON job_matches
  FOR UPDATE USING (user_id = auth.uid()::text);
-- Users can dismiss/save matches, but creation is backend-only

-- agent_sessions
CREATE POLICY "users_read_own_sessions" ON agent_sessions
  FOR SELECT USING (user_id = auth.uid()::text);
-- No direct writes — backend manages sessions

-- agent_messages (indirect via session)
CREATE POLICY "users_read_own_messages" ON agent_messages
  FOR SELECT USING (
    session_id IN (
      SELECT id FROM agent_sessions WHERE user_id = auth.uid()::text
    )
  );

-- application_questions (indirect via application)
CREATE POLICY "users_read_own_questions" ON application_questions
  FOR SELECT USING (
    application_id IN (
      SELECT id FROM applications WHERE user_id = auth.uid()::text
    )
  );

-- channel_identities
CREATE POLICY "users_read_own_channels" ON channel_identities
  FOR SELECT USING (user_id = auth.uid()::text);

-- interaction_events
CREATE POLICY "users_read_own_events" ON interaction_events
  FOR SELECT USING (user_id = auth.uid()::text);
CREATE POLICY "users_insert_own_events" ON interaction_events
  FOR INSERT WITH CHECK (user_id = auth.uid()::text OR user_id IS NULL);

-- dossiers
CREATE POLICY "users_read_own_dossiers" ON dossiers
  FOR SELECT USING (user_id = auth.uid()::text);

-- foxhound_briefs
CREATE POLICY "users_read_own_briefs" ON foxhound_briefs
  FOR SELECT USING (user_id = auth.uid()::text);

-- agent_activities
CREATE POLICY "users_read_own_activities" ON agent_activities
  FOR SELECT USING (user_id = auth.uid()::text);

-- watchdog_checks
CREATE POLICY "users_read_own_watchdog_checks" ON watchdog_checks
  FOR SELECT USING (user_id = auth.uid()::text);

-- recon_dossiers
CREATE POLICY "users_read_own_recon_dossiers" ON recon_dossiers
  FOR SELECT USING (user_id = auth.uid()::text);

-- tinyfish_brief_cache
CREATE POLICY "users_read_own_tinyfish_cache" ON tinyfish_brief_cache
  FOR SELECT USING (user_id = auth.uid()::text);


-- ─── 3. PUBLIC-READABLE TABLES ───

-- job_listings — anyone can browse jobs (including anon)
CREATE POLICY "public_read_jobs" ON job_listings
  FOR SELECT USING (true);
-- No writes via anon key — only backend inserts/updates jobs


-- ─── 4. PUBLIC-INSERT TABLES ───

-- waitlist_entries — anyone can sign up for the waitlist
CREATE POLICY "public_insert_waitlist" ON waitlist_entries
  FOR INSERT WITH CHECK (true);
-- No SELECT for anon — only admin can read the waitlist
-- No UPDATE/DELETE for anon


-- ─── 5. ADMIN-ONLY / SYSTEM TABLES ───
-- RLS is enabled but NO policies are created for anon/authenticated roles.
-- This means these tables are only accessible via the service_role key (backend).
-- The anon key cannot read or write these tables at all.

-- discovery_runs: system-only (no policy = no access via anon/authenticated)
-- foxhound_jobs: system-only
-- foxhound_runs: system-only
-- tinyfish_runs: system-only
-- notification_deliveries: system-only
-- notification_destinations: system-only


-- ─── 6. VERIFY ───
-- After running, check that all tables have RLS enabled:
-- SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public';
