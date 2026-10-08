-- 005_reports: users report a post or a comment, and an admin handles the reports
-- (GET /api/admin/reports). They catch what moderation let through.
--
-- No IF NOT EXISTS: schema_migrations already guarantees this runs once per
-- database, so a reports table that is somehow there already is drift, and the
-- migration should fail loudly instead of skipping it.
--
--   post_id, comment_id
--               the reported content: exactly one of the two is set
--               (chk_reports_one_target; the API checks it first, for a clear 400).
--               ON DELETE CASCADE deletes the row, so MySQL allows the CHECK on
--               these columns (it refuses one with SET NULL: error 3823).
--   reason      a fixed list, so the admin page can group and filter by it.
--   details     the reporter's optional note, plain text (never rendered as HTML).
--   status      'open' until an admin dismisses it ('resolved'). Banning the author
--               leaves it open; deleting the content deletes the report with it.
--   resolved_by the admin who dismissed it. ON DELETE SET NULL: the report stays
--               resolved when that admin's account goes.
-- The two unique keys allow one report per user and target. They work although one
-- column of each is NULL: a NULL never equals another, so (reporter, NULL) pairs
-- never collide. A second report is a duplicate-key error (1062) that the API
-- answers as "already reported". Each key's leading reporter_id also serves the
-- reporter_id foreign key. idx_reports_status serves the admin list, newest first;
-- post_id and comment_id get their own indexes from their foreign keys.
-- ON DELETE CASCADE removes a report with its post, its comment or its reporter.

CREATE TABLE reports (
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
