-- 006_password_resets: one row per "forgot password" link
-- (POST /api/password/forgot and /api/password/reset).
--
-- No IF NOT EXISTS: schema_migrations already guarantees this runs once per
-- database, so a password_resets table that is somehow there already is drift, and
-- the migration should fail loudly instead of skipping it.
--
--   token_hash  SHA-256 (hex) of the link's token. The token itself is only in the
--               email, so a copy of this table opens no account. A random 256-bit
--               token needs no slow hash (bcrypt), and a lookup needs the same hash
--               every time; UNIQUE gives that lookup its index.
--   expires_at  30 minutes after the request (set by the API in UTC, like sessions).
--   used_at     when the link reset the password. A reset also marks every other
--               open link of the user as used, so an older email stops working.
--   created_at  counts the requests of the last hour (at most 3 per user); a link
--               whose email could not be sent is deleted, so it does not count.
-- idx_password_resets_user serves that count and the user_id foreign key.
-- ON DELETE CASCADE removes a user's links with the user.

CREATE TABLE password_resets (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NOT NULL,
    token_hash CHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMP NOT NULL,
    used_at    TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_password_resets_user (user_id, created_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
