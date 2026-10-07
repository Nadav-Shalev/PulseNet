-- 001_likes: a user likes a post.
--
-- No IF NOT EXISTS: schema_migrations already guarantees this runs once per
-- database, so a likes table that is somehow there already is drift, and the
-- migration should fail loudly instead of skipping it.
--
-- One statement, so a failure leaves nothing half-created. The composite primary
-- key allows one like per user per post (POST /like uses INSERT IGNORE, so liking
-- twice is a no-op). idx_likes_post serves counting a post's likes, which the
-- primary key (user_id first) cannot. ON DELETE CASCADE removes a post's likes
-- with the post (and a user's likes with the user). Unlike follows, there is no
-- CHECK: liking your own post is allowed.

CREATE TABLE likes (
    user_id    INT NOT NULL,
    post_id    INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, post_id),
    INDEX idx_likes_post (post_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);
