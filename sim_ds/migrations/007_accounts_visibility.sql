-- 007: account system, sessions, user quotas, set visibility.
BEGIN;

CREATE TABLE sim_user (
  id                TEXT PRIMARY KEY,
  username          TEXT NOT NULL UNIQUE,
  password_hash     TEXT NOT NULL,
  display_name      TEXT,
  role              TEXT NOT NULL DEFAULT 'user'
                    CHECK (role IN ('super_admin', 'admin', 'user')),
  status            TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'disabled')),
  project           TEXT NOT NULL DEFAULT 'default',
  max_priority      INT  NOT NULL DEFAULT 5 CHECK (max_priority BETWEEN 0 AND 9),
  max_running_cases INT,
  max_cpu           INT,
  max_mem_gb        INT,
  max_gpu           INT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sim_session (
  token      TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES sim_user(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_sim_session_user ON sim_session(user_id);
CREATE INDEX idx_sim_session_expiry ON sim_session(expires_at);

INSERT INTO sim_user(
  id, username, password_hash, display_name, role, project,
  max_priority, max_running_cases, max_cpu, max_mem_gb, max_gpu
) VALUES (
  'usr_super_admin_df_sim',
  'df_sim',
  'pbkdf2_sha256$210000$cb64e4d62e13c7e1bf7d6010ca173ed6$adf7530e6c926ffa9236f1bce2de2dc54f4650b62264f1c5979e445b9c8d4954',
  '超级管理员',
  'super_admin',
  'default',
  9, 96, 192, 768, 12
);

ALTER TABLE scenario_set
  ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'
  CHECK (visibility IN ('private', 'public'));
CREATE INDEX idx_scenario_set_visibility
  ON scenario_set(project, visibility, created_at DESC);

ALTER TABLE resource_reservation ADD COLUMN owner TEXT;
CREATE INDEX idx_resource_reservation_owner_active
  ON resource_reservation(owner) WHERE released_at IS NULL;

COMMIT;
