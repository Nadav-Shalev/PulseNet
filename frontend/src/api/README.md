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

Returns `401` if the session cookie is missing or expired, and `422` when
moderation blocks the post (see below).

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
deep); `401` without a valid session; `404` if the post does not exist; `422` when
moderation blocks the comment (see below); `503` when the database is unavailable.

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

Returns `401` without a valid session, `403` for someone else's comment (an admin
may delete any comment, and `deleteArticle` any post), `404` if the comment does not
exist, and `503` when the database is unavailable.

### `aiCorrect(text, format)` / `aiSuggestPost(title, tags)` / `aiSuggestComment(postId, parentId)`

AI assistance for the logged-in user. Each resolves to a suggestion and stores
nothing: the UI (`components/AiSuggestion.jsx`) shows it with Apply and Dismiss.

| Function | Request | Resolves to |
| --- | --- | --- |
| `aiCorrect(text, format = 'text')` | `POST /api/ai/correct {text, format}`; `format` is `'html'` for the post editor | the corrected text (sanitized HTML for `'html'`) |
| `aiSuggestPost(title, tags = [])` | `POST /api/ai/suggest-post {title, tags}` | a draft body as sanitized HTML |
| `aiSuggestComment(postId, parentId = null)` | `POST /api/ai/suggest-comment {post_id, parent_id}` | a proposed comment as plain text |

Each throws an `Error` with the backend's message and `status`: `400` for bad
input, `401` without a session, `404` for a missing post, `429` when a daily AI
limit (the user's or the site's) or the provider's rate limit is reached, and `503`
when AI assistance is off or failing.

### `reportContent(target, reason, details)`

Report someone else's post (`{ postId }`) or comment (`{ commentId }`) to the admins.
`reason` is one of `REPORT_REASONS` (`spam`, `harassment`, `hate`, `misinformation`,
`other`); `details` is an optional plain-text note, 500 characters at most. The UI is
`components/ReportDialog.jsx`, behind the flag on each post card and comment.

**Request**
```
POST /api/reports
Cookie: session_id=...
{ "post_id": 12, "comment_id": null, "reason": "spam", "details": "an ad" }
```

**Response** `201`, or `200` with `"already": true` when this user had reported it before
```json
{ "reported": true, "already": false, "id": 3 }
```

Throws with `status` `400` (no target or two, a bad reason, a note too long, your own
content), `401`, `404` (the post or comment is gone) or `503`.

### Admin: `fetchReports`, `resolveReport`, `fetchAdminUsers`, `banUser`, `unbanUser`

For the `/admin` page (`pages/AdminPage.jsx`). Anyone but an admin gets `403`.

| Function | Request | Resolves to |
| --- | --- | --- |
| `fetchReports(status = 'open')` | `GET /api/admin/reports?status=open\|resolved` | up to 100 reports, newest first: `{id, reason, details, status, created_at, resolved_at, resolved_by, reporter: {username}, target: {type, id, post_id, post_title, excerpt}, author: {id, username, is_banned}}` |
| `resolveReport(id)` | `POST /api/admin/reports/<id>/resolve` | `{id, status: "resolved"}` |
| `fetchAdminUsers(q = '', bannedOnly = false)` | `GET /api/admin/users?q=...&banned=1` | up to 20 `{id, username, name, role, is_banned}` |
| `banUser(id)` / `unbanUser(id)` | `POST` / `DELETE /api/admin/users/<id>/ban` | the user, as above |

A ban logs the user out everywhere and blocks their login (`403`, "This account has
been suspended") until an unban; their content and the reports about it stay.
`banUser` answers `400` for yourself and `403` for another admin.

### `requestPasswordReset(email)` / `resetPassword(token, password)`

A forgotten password, without a session. The pages are `pages/ForgotPasswordPage.jsx`
(`/forgot-password`, linked from the login page) and `pages/ResetPasswordPage.jsx`
(`/reset-password`, which the emailed link opens).

| Function | Request | Resolves to |
| --- | --- | --- |
| `requestPasswordReset(email)` | `POST /api/password/forgot {email}` | `{message}`: the same words whether or not the address has an account |
| `resetPassword(token, password)` | `POST /api/password/reset {token, password}` | `{message}` once the password is changed |

The emailed link is `<site>/reset-password#token=...`. The token is in the fragment,
which the browser never sends to a server; the reset page reads it once and removes
it from the address bar. A link works once, for 30 minutes. A reset ends every
session of the account and does not log in: the page sends the user to `/login`.
`requestPasswordReset` throws with `status` `400` for a missing address and `503`
when mail is off on the server or the database is down. `resetPassword` throws with
`400` for a bad, used or expired link or a password over 72 bytes, and `503`.

---

## Error Responses

All endpoints return JSON errors in this shape:
```json
{ "error": "Human-readable message" }
```

Common status codes:
- `400` — validation error (missing fields, value too long, etc.)
- `401` — no valid session cookie
- `403` — not allowed (e.g. someone else's comment, an admin endpoint, a banned account's login)
- `404` — resource not found
- `422` — moderation blocked a post or comment as toxic; nothing was stored
- `429` — a daily AI limit, or the AI provider's rate limit, was reached
- `503` — database unavailable (mock mode active for reads; writes blocked)

### Moderation (`422`)

`POST /api/articles` and `POST /api/articles/<id>/comments` check the visible text
before storing it. A blocked one answers `422` with the category
(`harassment`, `hate` or `threat`), and the message is meant to be shown as is:
```json
{
  "error": "This comment looks insulting or harassing, so it was not published. Please rephrase it.",
  "category": "harassment"
}
```
`createArticle` and `createComment` throw it as an `Error` with that message, so the
editor and the comment box show it and keep the text for rephrasing.
