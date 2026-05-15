CREATE TABLE IF NOT EXISTS proxy_circuit_state (
  provider text PRIMARY KEY,
  status text NOT NULL DEFAULT 'closed' CHECK (status IN ('closed', 'half_open', 'open')),
  open_until timestamptz,
  consecutive_failures int NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO proxy_circuit_state (provider) VALUES ('iproyal'), ('webshare')
ON CONFLICT (provider) DO NOTHING;
