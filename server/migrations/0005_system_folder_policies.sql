-- Administrator-managed visibility for the read-only mounted catalogue.
--
-- Rows exist only for folders that deviate from the default: a top-level
-- mounted folder without a row is public, matching historical behaviour.
-- 'admin' hides a folder from everyone except administrators.
CREATE TABLE system_folder_policies (
  path TEXT PRIMARY KEY,
  visibility TEXT NOT NULL CHECK(visibility IN ('authenticated', 'admin')),
  updated_at TEXT NOT NULL
);
