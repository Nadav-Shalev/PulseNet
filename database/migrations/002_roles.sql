-- 002_roles: user roles and flags, for moderation and for the AI agents.
--
--   role         'user' or 'admin'. Every account starts as 'user'; an admin is
--                promoted by hand with: python backend/manage.py make-admin <username>
--   is_banned    set by an admin; a banned user can neither log in nor use a session
--                (enforced from S11).
--   is_agent     an AI agent account (S14). Agents have no password, so they cannot
--                log in (/api/login already rejects an empty password_hash).
--   personality  the agent's persona text; NULL for people.
--
-- One ALTER TABLE, so the four columns are added together or not at all; existing
-- users get the defaults. No IF NOT EXISTS (MySQL has none for ADD COLUMN): a
-- column that is already there is drift, and the migration should fail loudly.

ALTER TABLE users
    ADD COLUMN role        ENUM('user', 'admin') NOT NULL DEFAULT 'user',
    ADD COLUMN is_banned   BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN is_agent    BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN personality TEXT;
