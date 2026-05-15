-- Per-user proxy bandwidth + rate-limit + concurrency quotas (plan §2.1).
ALTER TABLE public.plan_tiers
  ADD COLUMN IF NOT EXISTS proxy_bytes_per_month bigint NOT NULL DEFAULT 524288000,
  ADD COLUMN IF NOT EXISTS proxy_requests_per_minute int NOT NULL DEFAULT 30,
  ADD COLUMN IF NOT EXISTS transcript_concurrency int NOT NULL DEFAULT 2;

-- Tier-specific defaults; only existing seed rows are updated (UPDATE no-ops for missing tiers).
UPDATE public.plan_tiers
SET proxy_bytes_per_month = 104857600,
    proxy_requests_per_minute = 10,
    transcript_concurrency = 1
WHERE tier_key = 'free';

UPDATE public.plan_tiers
SET proxy_bytes_per_month = 2147483648,
    proxy_requests_per_minute = 60,
    transcript_concurrency = 4
WHERE tier_key = 'pro';

UPDATE public.plan_tiers
SET proxy_bytes_per_month = 21474836480,
    proxy_requests_per_minute = 200,
    transcript_concurrency = 8
WHERE tier_key = 'business';
