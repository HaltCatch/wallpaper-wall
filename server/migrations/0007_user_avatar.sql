-- Persist the avatar advertised by the OIDC provider (authentik exposes it as
-- the `picture` claim) so the signed-in header and 管理中心 can show the same
-- portrait the identity provider uses. Local accounts leave it NULL and fall
-- back to the generic person glyph.
ALTER TABLE users ADD COLUMN avatar_url TEXT;
