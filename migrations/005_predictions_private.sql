-- 005_predictions_private.sql
-- S-2: stop serving pending predictions to anyone holding the anon key.
-- NOT EXECUTED automatically: run it by hand in the Supabase SQL editor.
--
-- Readers of `predictions` and the key they use (all bypass RLS via service_role):
--   * Heroku API (api_server.py / supabase_manager.py): SUPABASE_SERVICE_ROLE_KEY config var
--     (check it is set on Heroku before running this).
--   * GitHub workflows passing SUPABASE_SERVICE_ROLE_KEY: backtest.yml, check_results.yml,
--     daily_report.yml, scrape.yml, scrape_away.yml, scrape_baseball.yml, scrape_forebet.yml,
--     scrape_table_tennis_aiscore_away.yml, scrape_table_tennis_aiscore_home.yml, top_rules.yml.
-- The dashboard does not query `predictions` directly with the anon key; it uses the API.

DROP POLICY IF EXISTS "Allow public read" ON predictions;
