-- Run this once in the Supabase SQL Editor after applying Alembic migrations.
-- It deletes at most 1,000 expired rate-limit rows every ten minutes.
-- The outer expiry predicate prevents deleting a bucket refreshed concurrently.

create extension if not exists pg_cron with schema pg_catalog;

select cron.unschedule(jobid)
from cron.job
where jobname = 'payment-rate-limit-cleanup';

select cron.schedule(
    'payment-rate-limit-cleanup',
    '*/10 * * * *',
    $job$
    with expired as (
        select bucket_key
        from public.rate_limit_buckets
        where expires_at <= extract(epoch from clock_timestamp())::bigint
        order by expires_at, bucket_key
        limit 1000
    )
    delete from public.rate_limit_buckets as buckets
    using expired
    where buckets.bucket_key = expired.bucket_key
      and buckets.expires_at <= extract(epoch from clock_timestamp())::bigint;
    $job$
);
