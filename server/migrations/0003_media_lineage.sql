-- Associate generated thumbnails with the original variant they represent.
-- Existing rows remain valid with a NULL lineage and are handled by the API's
-- compatibility fallback.
ALTER TABLE media_objects ADD COLUMN source_media_id TEXT REFERENCES media_objects(id) ON DELETE CASCADE;
CREATE INDEX media_objects_source_kind ON media_objects(source_media_id, kind);
CREATE INDEX folders_parent_id ON folders(parent_id);
