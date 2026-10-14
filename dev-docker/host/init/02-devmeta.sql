CREATE SCHEMA IF NOT EXISTS devmeta;
CREATE TABLE IF NOT EXISTS devmeta.databases (
  name        text PRIMARY KEY,
  created_at  timestamptz NOT NULL DEFAULT now(),
  created_by  text NOT NULL,          -- 'mac:claude' | 'mac:codex' | 'mac:jp' | 'prune:first-seen'
  keep        boolean NOT NULL DEFAULT false,
  note        text
);
