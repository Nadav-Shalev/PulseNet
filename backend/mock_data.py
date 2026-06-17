MOCK_USERS = [
    {
        "id": 1,
        "name": "Alice Dev",
        "username": "alicedev",
        "email": "alicedev@dev.to",
        "bio": "Full-stack developer passionate about React and Python.",
        "avatar": "https://api.dicebear.com/7.x/avataaars/svg?seed=alicedev",
        "profile_image": "https://api.dicebear.com/7.x/avataaars/svg?seed=alicedev",
    },
    {
        "id": 2,
        "name": "Bob Coder",
        "username": "bobcoder",
        "email": "bobcoder@dev.to",
        "bio": "Backend engineer who loves databases and clean APIs.",
        "avatar": "https://api.dicebear.com/7.x/avataaars/svg?seed=bobcoder",
        "profile_image": "https://api.dicebear.com/7.x/avataaars/svg?seed=bobcoder",
    },
    {
        "id": 3,
        "name": "Carol Script",
        "username": "carolscript",
        "email": "carolscript@dev.to",
        "bio": "JavaScript enthusiast and open-source contributor.",
        "avatar": "https://api.dicebear.com/7.x/avataaars/svg?seed=carolscript",
        "profile_image": "https://api.dicebear.com/7.x/avataaars/svg?seed=carolscript",
    },
]

MOCK_POSTS = [
    {
        "id": 1,
        "author_id": 1,
        "title": "Getting Started with React Hooks",
        "body": "React Hooks changed how we write components. useState and useEffect are the two most common hooks you will reach for every day.",
        "description": "React Hooks changed how we write components. useState and useEffect are the two most common hooks you will reach for every day.",
        "cover_image": None,
        "devto_url": None,
        "readable_publish_date": "May 1",
        "created_at": "2025-05-01 10:00:00",
        "tags": ["react", "javascript", "hooks"],
    },
    {
        "id": 2,
        "author_id": 2,
        "title": "MySQL vs PostgreSQL: Which Should You Choose?",
        "body": "Both databases are excellent choices for production. MySQL is simpler to set up; PostgreSQL offers richer features like JSON columns and window functions.",
        "description": "Both databases are excellent choices for production. MySQL is simpler to set up; PostgreSQL offers richer features.",
        "cover_image": None,
        "devto_url": None,
        "readable_publish_date": "May 2",
        "created_at": "2025-05-02 09:00:00",
        "tags": ["database", "mysql", "postgresql"],
    },
    {
        "id": 3,
        "author_id": 3,
        "title": "10 Tips to Write Cleaner JavaScript",
        "body": "Clean code is readable code. Use const over let, prefer arrow functions, and always handle your promise rejections.",
        "description": "Clean code is readable code. Use const over let, prefer arrow functions, and always handle your promise rejections.",
        "cover_image": None,
        "devto_url": None,
        "readable_publish_date": "May 3",
        "created_at": "2025-05-03 08:00:00",
        "tags": ["javascript", "cleancode", "tips"],
    },
    {
        "id": 4,
        "author_id": 1,
        "title": "Building a REST API with Flask",
        "body": "Flask is a micro-framework that makes it easy to build REST APIs in Python. In this post we set up routes, connect to MySQL, and return JSON responses.",
        "description": "Flask is a micro-framework that makes it easy to build REST APIs in Python.",
        "cover_image": None,
        "devto_url": None,
        "readable_publish_date": "May 4",
        "created_at": "2025-05-04 11:00:00",
        "tags": ["python", "flask", "api"],
    },
]


def _user_obj(user):
    return {
        "username": user["username"],
        "name": user["name"],
        "email": user["email"],
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
        "readable_publish_date": post["readable_publish_date"],
        "url": post["devto_url"],
        "tag_list": list(post["tags"]),
        "user": _user_obj(user),
    }


def mock_get_articles(page=1, per_page=10, username=None):
    posts = MOCK_POSTS
    if username:
        user = next((u for u in MOCK_USERS if u["username"] == username), None)
        if user:
            posts = [p for p in MOCK_POSTS if p["author_id"] == user["id"]]
        else:
            posts = []
    result = [r for r in (_post_shape(p) for p in posts) if r]
    result.sort(key=lambda p: p.get("readable_publish_date", ""), reverse=True)
    offset = (page - 1) * per_page
    return result[offset: offset + per_page]


def mock_get_article_by_id(article_id):
    post = next((p for p in MOCK_POSTS if p["id"] == article_id), None)
    if post is None:
        return None
    shaped = _post_shape(post)
    if shaped:
        shaped["body_html"] = f"<p>{post['body']}</p>"
    return shaped


def mock_search_users(q, limit=10, offset=0):
    q_lower = q.lower()
    results = [
        {"id": u["id"], "name": u["name"], "username": u["username"],
         "email": u["email"], "avatar": u["avatar"]}
        for u in MOCK_USERS
        if q_lower in u["name"].lower()
        or q_lower in u["username"].lower()
        or q_lower in u["email"].lower()
    ]
    return results[offset: offset + limit]
