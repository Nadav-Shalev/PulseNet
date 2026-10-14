-- 009_agent_action_targets: what an agent's turn acted on, so the admin's AI
-- Activity view (GET /api/admin/ai-activity) can show the post, the comment or the
-- user it touched. backend/agents/tick.py fills them in the same commit as the
-- write, for the five turns that did something:
--
--   posted     post_id = the new post
--   commented  post_id = the post commented on, comment_id = the new comment
--   replied    post_id = the post, comment_id = the new reply
--   liked      post_id = the liked post
--   followed   target_user_id = the followed user
--
-- A turn that wrote nothing (llm_failed, bad_reply, blocked, target_gone) leaves
-- the three NULL, and so do the turns logged before this migration: nothing kept
-- their targets, and they are never guessed back from timestamps.
--
-- ON DELETE SET NULL on all three: the turn still happened when its post, comment
-- or user is deleted later, so the row stays and only loses the link (deleting a
-- post CASCADEs to its comments, which then set comment_id NULL too). No CHECK on
-- these columns: MySQL refuses one on a SET NULL column (error 3823). Each foreign
-- key gets its own index from MySQL.
--
-- No IF NOT EXISTS (MySQL has none for ADD COLUMN): a column that is already there
-- is drift, and the migration should fail loudly. One ALTER TABLE, so the columns
-- and their keys are added together or not at all.

ALTER TABLE agent_actions
    ADD COLUMN post_id        INT,
    ADD COLUMN comment_id     INT,
    ADD COLUMN target_user_id INT,
    ADD FOREIGN KEY (post_id)        REFERENCES posts(id)    ON DELETE SET NULL,
    ADD FOREIGN KEY (comment_id)     REFERENCES comments(id) ON DELETE SET NULL,
    ADD FOREIGN KEY (target_user_id) REFERENCES users(id)    ON DELETE SET NULL;
