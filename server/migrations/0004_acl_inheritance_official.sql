-- Folder-level ACL inheritance and the admin-managed official library.
--
-- inherit_acl = 1 means the folder takes its effective visibility and viewer
-- grants from the nearest ancestor with inherit_acl = 0 (root folders always
-- act as their own source).  Existing folders keep explicit ACLs (0), so
-- behaviour does not change for already-published data.
--
-- is_official = 1 marks folders of the built-in library: they are created and
-- managed by administrators only, default to public visibility, and are shown
-- to every visitor as the default gallery.  The flag is copied from the parent
-- at creation time so an official subtree stays official.
ALTER TABLE folders ADD COLUMN inherit_acl INTEGER NOT NULL DEFAULT 0 CHECK(inherit_acl IN (0, 1));
ALTER TABLE folders ADD COLUMN is_official INTEGER NOT NULL DEFAULT 0 CHECK(is_official IN (0, 1));
CREATE INDEX folders_official ON folders(is_official) WHERE is_official = 1;
