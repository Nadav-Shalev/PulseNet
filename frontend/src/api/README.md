# PulseNet — API Layer

`frontend/src/api/api.js` is the single place where the React frontend talks to the backend.
All `fetch` calls go through this file, so switching between DEV.to and the local Flask server
only requires changing `VITE_API_BASE_URL`.

---

## Base URL

```js
const BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000/api').replace(/\/$/, '');
```

Start the Flask server before running the frontend:

```bash
cd backend
python app.py
```

---

## Functions

### `fetchArticles(page, perPage)`

Returns a page of articles for the main feed.

**Request**
```
GET /api/articles?page=1&per_page=10
```

**Response** — array of article objects:
```json
[
  {
    "id": 42,
    "title": "Getting Started with React",
    "description": "A short intro to React hooks...",
    "cover_image": "https://example.com/image.jpg",
    "readable_publish_date": "May 7",
    "url": "https://dev.to/...",
    "tag_list": ["react", "javascript"],
    "like_count": 3,
    "liked_by_me": false,
    "comment_count": 2,
    "user": {
      "username": "alicedev",
      "name": "Alice Dev",
      "profile_image": "https://..."
    }
  }
]
```

`like_count` is the post's total likes. `liked_by_me` is `true` only when the
session cookie belongs to a user who liked the post (always `false` when logged out).
`comment_count` counts all of the post's comments, replies included. Every feed
(`username`, `tag`, `feed=following`) and a single article carry all three.

---

### `fetchArticlesByUser(username, page, perPage)`

Same as `fetchArticles` but filters by author username.

**Request**
```
GET /api/articles?username=alicedev&page=1&per_page=10
```

---

### `fetchArticleById(id)`

Returns a single article with full HTML content for the "Read More" modal.

**Request**
```
GET /api/articles/42
```

**Response** — same shape as list item, plus:
```json
{
  "body_html": "<h1>Getting Started...</h1><p>...</p>"
}
```

The backend fetches `body_html` from DEV.to on first access (using the stored `devto_id`)
and caches it in the database for subsequent requests.

---

### `createArticle(title, body, tags, mainImage)`

Creates a new article authored by the logged-in user. Requires a valid session
cookie — the backend derives the author from the session, not from the body.

**Request**
```
POST /api/articles
Content-Type: application/json
Cookie: session_id=...

{
  "article": {
    "title": "My Post",
    "body_markdown": "# Hello\n\nThis is my post.",
    "tags": ["react", "tutorial"],
    "main_image": "https://example.com/cover.jpg"
  }
}
```

Returns `401` if the session cookie is missing or expired.

**Response** `201` (a new post also has `"like_count": 0, "liked_by_me": false, "comment_count": 0`)
```json
{
  "id": 99,
  "title": "My Post",
  "body_html": "<h1>Hello</h1><p>This is my post.</p>",
  "tag_list": ["react", "tutorial"],
  "user": { "username": "...", "name": "...", "profile_image": "..." }
}
```

---

### `likeArticle(id)` / `unlikeArticle(id)`

Like or unlike a post as the logged-in user. The liker comes from the session
cookie, never from the request. Liking twice is a no-op (one like per user per post).

**Request**
```
POST   /api/articles/42/like
DELETE /api/articles/42/like
Cookie: session_id=...
```

**Response** `200`, with the post's fresh total:
```json
{ "liked": true, "like_count": 4 }
```

Returns `401` without a valid session, `404` if the post does not exist, and `503`
when the database is unavailable.

---

### `fetchComments(postId)`

A post's comments as a thread: top-level comments oldest first, each with its
`replies` (oldest first). Public: no session needed.

**Request**
```
GET /api/articles/42/comments
```

**Response** `200`
```json
[
  {
    "id": 7,
    "post_id": 42,
    "parent_id": null,
    "body_html": "<p>Great post</p>",
    "created_at": "2026-10-08T09:30:00+00:00",
    "user": { "username": "alicedev", "name": "Alice Dev", "profile_image": "https://..." },
    "replies": [
      { "id": 8, "post_id": 42, "parent_id": 7, "body_html": "<p>Thanks!</p>", "created_at": "...", "user": { "...": "..." } }
    ]
  }
]
```

`body_html` is sanitized by the backend, so it can be rendered as HTML. There is
no email in a comment. Returns `404` if the post does not exist and `503` when the
database is unavailable (never an empty list, which would mean "no comments").

---

### `createComment(postId, bodyHtml, parentId)`

Comment on a post as the logged-in user, or reply to a top-level comment with
`parentId`. The writer comes from the session cookie, never from the request.
The comment box sends plain text as escaped HTML (`utils/textToHtml.js`); the
backend sanitizes whatever HTML it gets before storing it.

**Request**
```
POST /api/articles/42/comments
Content-Type: application/json
Cookie: session_id=...

{ "body_html": "<p>Thanks!</p>", "parent_id": 7 }
```

**Response** `201`, with the post's fresh total:
```json
{ "comment": { "id": 8, "parent_id": 7, "...": "..." }, "comment_count": 2 }
```

Returns `400` for an empty comment, more than 2000 characters of text, or a
`parent_id` that is not a top-level comment on this post (replies are one level
deep); `401` without a valid session; `404` if the post does not exist; `503` when
the database is unavailable.

---

### `deleteComment(commentId)`

Delete one of your own comments. Deleting a top-level comment deletes its replies.

**Request**
```
DELETE /api/comments/8
Cookie: session_id=...
```

**Response** `200`
```json
{ "deleted": true, "id": 8, "comment_count": 1 }
```

Returns `401` without a valid session, `403` for someone else's comment, `404` if
the comment does not exist, and `503` when the database is unavailable.

---

## Error Responses

All endpoints return JSON errors in this shape:
```json
{ "error": "Human-readable message" }
```

Common status codes:
- `400` — validation error (missing fields, value too long, etc.)
- `401` — no valid session cookie
- `403` — not allowed (e.g. someone else's comment)
- `404` — resource not found
- `503` — database unavailable (mock mode active for reads; writes blocked)
