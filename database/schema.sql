CREATE DATABASE IF NOT EXISTS pulsenet_db;
USE pulsenet_db;

CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    username      VARCHAR(100) NOT NULL UNIQUE,
    email         VARCHAR(100) NOT NULL UNIQUE,
    bio           TEXT,
    avatar        VARCHAR(500),
    profile_image VARCHAR(500),
    -- bcrypt hashes are ~60 chars; column is sized for safety and stores both salt+hash.
    password_hash VARCHAR(255) NOT NULL DEFAULT '',
    -- Roles and flags (migration 002). Admins are promoted with backend/manage.py
    -- make-admin; agents have no password and cannot log in; personality is the
    -- agent's persona text (NULL for people).
    role          ENUM('user', 'admin') NOT NULL DEFAULT 'user',
    is_banned     BOOLEAN NOT NULL DEFAULT FALSE,
    is_agent      BOOLEAN NOT NULL DEFAULT FALSE,
    personality   TEXT
);

-- Server-side session store. Cookie holds only the opaque session_id (slide 13);
-- the row maps it to a user and an expiry the server controls.
CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(255) NOT NULL PRIMARY KEY,
    user_id    INT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS posts (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    author_id             INT NOT NULL,
    title                 VARCHAR(150) NOT NULL,
    body                  TEXT NOT NULL,
    body_html             LONGTEXT,
    description           TEXT,
    cover_image           VARCHAR(500),
    devto_id              INT UNIQUE,
    devto_url             VARCHAR(500),
    readable_publish_date VARCHAR(50),
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (author_id) REFERENCES users(id)
);

-- tags.name uses utf8mb4_bin so "react", "React", "REACT" are distinct rows.
-- Autocomplete uses LOWER(name) LIKE LOWER(...) for case-insensitive search.
CREATE TABLE IF NOT EXISTS tags (
    id   INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS posts_tags (
    post_id INT NOT NULL,
    tag_id  INT NOT NULL,
    PRIMARY KEY (post_id, tag_id),
    FOREIGN KEY (post_id) REFERENCES posts(id),
    FOREIGN KEY (tag_id)  REFERENCES tags(id)
);

-- Directed follow relationship: follower_id follows following_id.
-- Composite PK prevents duplicate follows; CHECK blocks self-follows (also
-- enforced in the backend for older MySQL where CHECK is parsed but ignored).
CREATE TABLE IF NOT EXISTS follows (
    follower_id  INT NOT NULL,
    following_id INT NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (follower_id, following_id),
    FOREIGN KEY (follower_id)  REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (following_id) REFERENCES users(id) ON DELETE CASCADE,
    CHECK (follower_id <> following_id)
);
CREATE INDEX idx_follows_following ON follows(following_id);

-- A user likes a post (migration 001). Composite PK = one like per user per post;
-- idx_likes_post serves per-post counts. Deleting a post or user removes its likes.
CREATE TABLE IF NOT EXISTS likes (
    user_id    INT NOT NULL,
    post_id    INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, post_id),
    INDEX idx_likes_post (post_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);

-- A comment on a post (migration 003). parent_id is NULL for a comment on the post,
-- else the comment it replies to; the API keeps replies one level deep. body_html is
-- sanitized. Deleting a post, a comment or a user removes the comments under it.
CREATE TABLE IF NOT EXISTS comments (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    post_id    INT NOT NULL,
    author_id  INT NOT NULL,
    parent_id  INT,
    body_html  TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_comments_post (post_id, created_at),
    FOREIGN KEY (post_id)   REFERENCES posts(id)    ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES users(id)    ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES comments(id) ON DELETE CASCADE
);

-- One row per LLM call (migration 004): the usage log behind the daily limit in
-- backend/llm/. usage_day is the UTC day the call counts against; 'over_limit' rows
-- were refused before reaching a provider and are not counted. Only sizes are kept,
-- never the prompt or reply text. A deleted user's calls keep counting (SET NULL).
CREATE TABLE IF NOT EXISTS llm_usage (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    usage_day    DATE NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    provider     VARCHAR(32) NOT NULL,
    model        VARCHAR(100),
    purpose      VARCHAR(32) NOT NULL,
    user_id      INT,
    status       ENUM('ok', 'error', 'timeout', 'rate_limited', 'over_limit') NOT NULL,
    latency_ms   INT,
    prompt_chars INT NOT NULL,
    reply_chars  INT NOT NULL DEFAULT 0,
    INDEX idx_llm_usage_day (usage_day, status),
    INDEX idx_llm_usage_user (user_id, usage_day),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

-- A user's report of a post or a comment (migration 005), for the admin page.
-- Exactly one of post_id / comment_id is set (chk_reports_one_target). One report
-- per user and target (the unique keys: NULLs never collide, so each key only binds
-- its own target). Status 'open' until an admin dismisses it; banning the author
-- leaves it open, and deleting the content deletes the report (CASCADE).
CREATE TABLE IF NOT EXISTS reports (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    reporter_id INT NOT NULL,
    post_id     INT,
    comment_id  INT,
    reason      ENUM('spam', 'harassment', 'hate', 'misinformation', 'other') NOT NULL,
    details     VARCHAR(500),
    status      ENUM('open', 'resolved') NOT NULL DEFAULT 'open',
    resolved_by INT,
    resolved_at TIMESTAMP NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_reports_post (reporter_id, post_id),
    UNIQUE KEY uq_reports_comment (reporter_id, comment_id),
    INDEX idx_reports_status (status, created_at),
    CONSTRAINT chk_reports_one_target CHECK ((post_id IS NULL) <> (comment_id IS NULL)),
    FOREIGN KEY (reporter_id) REFERENCES users(id)    ON DELETE CASCADE,
    FOREIGN KEY (post_id)     REFERENCES posts(id)    ON DELETE CASCADE,
    FOREIGN KEY (comment_id)  REFERENCES comments(id) ON DELETE CASCADE,
    FOREIGN KEY (resolved_by) REFERENCES users(id)    ON DELETE SET NULL
);
