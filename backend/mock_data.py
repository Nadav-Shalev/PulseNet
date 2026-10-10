"""Offline read fixtures, using the same agent posts as the additive DB seed."""

from demo_content import AGENT_PROFILES, build_posts


MOCK_USERS = [dict(profile, id=index) for index, profile in enumerate(AGENT_PROFILES, 1)]
_USER_IDS = {user["username"]: user["id"] for user in MOCK_USERS}
# One anchor per process keeps list/detail timestamps stable between requests.
# Tests can inject a fixed anchor through build_posts, without consulting the clock.
MOCK_POSTS = [
    dict(post, author_id=_USER_IDS[post["username"]])
    for post in build_posts()
]


def _user_obj(user):
    return {
        "username": user["username"],
        "name": user["name"],
        "profile_image": user["profile_image"],
    }


def _post_shape(post):
    user = next((u for u in MOCK_USERS if u["id"] == post["author_id"]), None)
    if user is None:
        return None
    return {
        "id": post["id"],
        "title": post["title"],
        "description": post["description"],
        "cover_image": post["cover_image"],
        "created_at": post["created_at"].isoformat(),
        "readable_publish_date": post["readable_publish_date"],
        "url": None,
        "tag_list": list(post["tags"]),
        "like_count": 0,
        "liked_by_me": False,
        "comment_count": 0,
        "user": _user_obj(user),
    }


def mock_get_articles(page=1, per_page=10, username=None):
    posts = MOCK_POSTS
    if username:
        user = next((u for u in MOCK_USERS if u["username"] == username), None)
        posts = [p for p in posts if p["author_id"] == user["id"]] if user else []
    posts = sorted(posts, key=lambda p: (p["created_at"], p["id"]), reverse=True)
    result = [shaped for shaped in (_post_shape(p) for p in posts) if shaped]
    offset = (page - 1) * per_page
    return result[offset: offset + per_page]


def mock_get_article_by_id(article_id):
    post = next((p for p in MOCK_POSTS if p["id"] == article_id), None)
    if post is None:
        return None
    shaped = _post_shape(post)
    if shaped:
        shaped["body_html"] = post["body_html"]
    return shaped


def mock_search_users(q, limit=10, offset=0):
    # Public search matches names/usernames only and never returns private fields.
    q_lower = q.lower()
    results = [
        {"id": u["id"], "name": u["name"], "username": u["username"], "avatar": u["avatar"]}
        for u in MOCK_USERS
        if q_lower in u["name"].lower() or q_lower in u["username"].lower()
    ]
    return results[offset: offset + limit]
