-- Record which storage backend holds each object so the configured driver can
-- change (local -> S3 or back) without breaking previously uploaded media.
-- Existing rows are backfilled at startup with the driver configured at that
-- moment, which matches where those objects actually live.
ALTER TABLE media_objects ADD COLUMN storage_driver TEXT NOT NULL DEFAULT '';
ALTER TABLE uploads ADD COLUMN storage_driver TEXT NOT NULL DEFAULT '';
