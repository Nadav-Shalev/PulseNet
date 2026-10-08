-- 004_llm_usage: one row per LLM call, the usage log behind the daily limit
-- (backend/llm/). It is shared by every process that calls the LLM: the API
-- workers and, later, the agents' timer.
--
-- No IF NOT EXISTS: schema_migrations already guarantees this runs once per
-- database, so an llm_usage table that is somehow there already is drift, and the
-- migration should fail loudly instead of skipping it.
--
--   usage_day     the UTC day the call counts against, computed by the service. Kept
--                 as its own column so the daily count never depends on the session
--                 time zone of whoever connects.
--   purpose       what the call was for: 'check', and later e.g. 'moderation'.
--   user_id       who it was for, if anyone. ON DELETE SET NULL: a deleted user's
--                 calls were still made, so they keep counting.
--   status        'over_limit' rows record calls refused by the daily limit; they
--                 never reached a provider, so the limit does not count them.
--   prompt_chars, reply_chars
--                 sizes only: the prompt and reply text are never stored.
-- idx_llm_usage_day answers the daily count from the index alone;
-- idx_llm_usage_user serves a per-user count and the user_id foreign key.

CREATE TABLE llm_usage (
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
