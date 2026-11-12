CREATE TABLE users (
  id TEXT PRIMARY KEY,
  issuer TEXT NOT NULL,
  subject TEXT NOT NULL,
  display_name TEXT NOT NULL,
  email TEXT,
  role TEXT NOT NULL CHECK(role IN ('user', 'admin')) DEFAULT 'user',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(issuer, subject)
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE folders (
  id TEXT PRIMARY KEY,
  source_scope TEXT NOT NULL CHECK(source_scope IN ('system', 'user')),
  owner_id TEXT REFERENCES users(id) ON DELETE CASCADE,
  parent_id TEXT REFERENCES folders(id) ON DELETE RESTRICT,
  name TEXT NOT NULL,
  visibility TEXT NOT NULL CHECK(visibility IN ('private', 'authenticated', 'public')) DEFAULT 'private',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK((source_scope = 'system' AND owner_id IS NULL) OR (source_scope = 'user' AND owner_id IS NOT NULL))
);

CREATE UNIQUE INDEX folders_user_name_parent ON folders(owner_id, parent_id, name) WHERE source_scope = 'user';

CREATE TABLE folder_grants (
  folder_id TEXT NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('viewer')),
  created_at TEXT NOT NULL,
  PRIMARY KEY(folder_id, user_id)
);

CREATE TABLE wallpapers (
  id TEXT PRIMARY KEY,
  folder_id TEXT REFERENCES folders(id) ON DELETE CASCADE,
  source_scope TEXT NOT NULL CHECK(source_scope IN ('system', 'user')),
  title TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('processing', 'ready', 'failed', 'deleted')) DEFAULT 'processing',
  width INTEGER,
  height INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE media_objects (
  id TEXT PRIMARY KEY,
  wallpaper_id TEXT NOT NULL REFERENCES wallpapers(id) ON DELETE CASCADE,
  object_key TEXT NOT NULL UNIQUE,
  original_name TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('original', 'thumbnail', 'thumbnail_small')),
  created_at TEXT NOT NULL
);

CREATE INDEX media_objects_wallpaper_kind ON media_objects(wallpaper_id, kind);

CREATE TABLE uploads (
  id TEXT PRIMARY KEY,
  folder_id TEXT NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
  owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  object_key TEXT NOT NULL UNIQUE,
  original_name TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('created', 'uploaded', 'processing', 'ready', 'failed', 'expired')),
  error_message TEXT,
  expected_bytes INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE favorites (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  wallpaper_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(user_id, wallpaper_id)
);

CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('queued', 'running', 'succeeded', 'failed')) DEFAULT 'queued',
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
