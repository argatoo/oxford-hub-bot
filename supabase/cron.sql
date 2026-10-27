-- Supabase Cron: calls the bot every minute (escalations of unanswered calls, cleanup).
-- Normally `python -m bot.setup_webhook ...` does this for you. Run it by hand only if that failed:
--   1. Dashboard → Database → Extensions: enable pg_cron and pg_net
--   2. Replace both placeholders below and run this in the SQL Editor.

select cron.schedule(
  'oxford-bot-tick',
  '* * * * *',
  $$
  select net.http_post(
    url := 'https://SIZNING-LOYIHA.vercel.app/api',
    headers := jsonb_build_object('Authorization', 'Bearer SIZNING_WEBHOOK_SECRET'),
    body := '{}'::jsonb,
    timeout_milliseconds := 30000
  );
  $$
);

-- Check that it runs:
--   select * from cron.job_run_details order by start_time desc limit 5;
-- Stop it:
--   select cron.unschedule('oxford-bot-tick');
