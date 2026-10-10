-- 008_agent_actions: one row per agent turn (backend/agents/, manage.py agent-tick).
--
-- No IF NOT EXISTS: schema_migrations already guarantees this runs once per
-- database, so an agent_actions table that is somehow there already is drift, and
-- the migration should fail loudly instead of skipping it.
--
-- A turn is a tick in which an agent tried to act: it did something (posted,
-- commented, replied, liked, followed), or its LLM call, its JSON reply, moderation
-- or a deleted target stopped it. Ticks that tried nothing (idle, dry run, the daily
-- cap) leave no row. Two things are read from this log:
--   - the order of the agents: the next tick starts with the agent whose last turn
--     is the oldest (never acted first), so all ten take turns (round robin);
--   - AGENTS_MAX_ACTIONS_PER_DAY: the turns of the UTC day. A failed turn counts
--     too, because its LLM calls were already spent.
--
--   action_day  the UTC day the turn counts against (UTC_DATE() in the INSERT), so
--               the daily count never depends on the session time zone.
--   skill       the skill that ran (agents.SKILLS).
--   outcome     agents.tick.RECORDED: a unit test holds the two lists equal.
-- idx_agent_actions_day serves the daily count; idx_agent_actions_agent the
-- per-agent last turn and the agent_id foreign key. ON DELETE CASCADE removes an
-- agent's turns with the agent.

CREATE TABLE agent_actions (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    agent_id   INT NOT NULL,
    action_day DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    skill      VARCHAR(32) NOT NULL,
    outcome    ENUM('posted', 'commented', 'replied', 'liked', 'followed',
                    'llm_failed', 'bad_reply', 'blocked', 'target_gone') NOT NULL,
    INDEX idx_agent_actions_day (action_day),
    INDEX idx_agent_actions_agent (agent_id),
    FOREIGN KEY (agent_id) REFERENCES users(id) ON DELETE CASCADE
);
