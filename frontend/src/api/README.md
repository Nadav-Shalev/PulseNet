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
    "user": {
      "username": "alicedev",
      "name": "Alice Dev",
      "profile_image": "https://..."
    }
  }
]
```

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

**Response** `201`
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

## Error Responses

All endpoints return JSON errors in this shape:
```json
{ "error": "Human-readable message" }
```

Common status codes:
- `400` — validation error (missing fields, value too long, etc.)
- `404` — resource not found
- `503` — database unavailable (mock mode active for reads; writes blocked)
