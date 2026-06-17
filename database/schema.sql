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
    password_hash VARCHAR(255) NOT NULL DEFAULT ''
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
