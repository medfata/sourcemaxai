CREATE TABLE proxy_blocklist (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider text NOT NULL,
  session_id text NOT NULL,
  reason text NOT NULL,
  blocked_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL DEFAULT (now() + interval '6 hours'),
  UNIQUE (provider, session_id)
);

CREATE INDEX idx_proxy_blocklist_active
  ON proxy_blocklist (provider, expires_at);
