-- 003_comments: users comment on posts, and reply to a comment one level deep.
--
-- No IF NOT EXISTS: schema_migrations already guarantees this runs once per
-- database, so a comments table that is somehow there already is drift, and the
-- migration should fail loudly instead of skipping it.
--
-- One statement, so a failure leaves nothing half-created.
--   parent_id   NULL for a comment on the post, else the comment it replies to.
--               Replies are one level deep: a reply's parent must itself have no
--               parent. The API enforces that, because MySQL cannot: a CHECK may
--               not look at another row, nor use a column with an ON DELETE action.
--   body_html   sanitized HTML (the API cleans it on the way in and on the way out).
-- idx_comments_post serves the post's comment thread in order and its comment
-- count, and doubles as the index of the post_id foreign key. ON DELETE CASCADE
-- removes a post's comments with the post (so DELETE /api/articles/<id> keeps
-- working), a comment's replies with the comment, and a user's comments with the user.

CREATE TABLE comments (
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
