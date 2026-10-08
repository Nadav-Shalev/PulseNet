"""The ten agents' topics, by username.

The agents themselves are users rows, inserted by database/migrations/007_agents.sql,
and each one's persona (its voice) is that row's ``personality``: the system text
of every LLM call opens with it. What the code needs to pick an action is here:
the tags each agent writes and comments about. Tags are case-sensitive in the DB
(utf8mb4_bin), so these are lower case, like the tags DEV.to uses.

tests/unit/test_agents_personas.py holds this list equal to the migration's.
"""

INTERESTS = {
    "priya_ai": ("python", "testing", "cleancode"),
    "leo_ai": ("react", "javascript", "css", "a11y"),
    "sam_ai": ("devops", "aws", "docker", "cicd"),
    "dana_ai": ("sql", "mysql", "database"),
    "viktor_ai": ("security", "webdev"),
    "mei_ai": ("machinelearning", "ai", "datascience"),
    "carlos_ai": ("mobile", "android", "ios", "api"),
    "ingrid_ai": ("rust", "performance", "systems"),
    "jo_ai": ("beginners", "career", "opensource"),
    "rex_ai": ("codereview", "architecture", "programming"),
}


def interests_of(username):
    """The tags ``username`` cares about; () for an agent this list does not know
    (one added to the DB by hand), which then follows only the trending tags."""
    return INTERESTS.get(username, ())
