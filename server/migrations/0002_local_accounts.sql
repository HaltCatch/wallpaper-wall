-- Local username/password accounts live alongside OIDC identities.  A
-- partial unique index lets existing OIDC users continue without usernames.
ALTER TABLE users ADD COLUMN username TEXT;
ALTER TABLE users ADD COLUMN password_hash TEXT;
CREATE UNIQUE INDEX users_username_unique ON users(username COLLATE NOCASE) WHERE username IS NOT NULL;
