import { BACKEND_URL } from './config.js';
const BASE = BACKEND_URL;

// credentials: 'include' makes the browser send/receive the session_id cookie
// cross-origin (Vite :5173 → Flask :5000). Backend CORS allows this.
const CREDS = { credentials: 'include' };

export const fetchArticles = (page = 1, perPage = 10) =>
  fetch(`${BASE}/articles?page=${page}&per_page=${perPage}`, CREDS).then(r => r.json());

export const fetchArticlesByUser = (username, page = 1, perPage = 10) =>
  fetch(`${BASE}/articles?username=${encodeURIComponent(username)}&page=${page}&per_page=${perPage}`, CREDS)
    .then(r => r.json());

export const fetchArticlesByTag = (tag, page = 1, perPage = 10) =>
  fetch(`${BASE}/articles?tag=${encodeURIComponent(tag)}&page=${page}&per_page=${perPage}`, CREDS)
    .then(r => r.json());

// Following feed: only posts from users the logged-in user follows. Requires a
// valid session cookie (backend returns 401 otherwise).
export const fetchFollowingArticles = async (page = 1, perPage = 10) => {
  const res = await fetch(`${BASE}/articles?feed=following&page=${page}&per_page=${perPage}`, CREDS);
  if (!res.ok) {
    const err = new Error(`Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return res.json();
};

export const fetchArticleById = (id) =>
  fetch(`${BASE}/articles/${id}`, CREDS).then(r => r.json());

// Owner-only: delete a post (backend verifies ownership and cleans up posts_tags).
export const deleteArticle = async (id) => {
  const res = await fetch(`${BASE}/articles/${id}`, { method: 'DELETE', ...CREDS });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

// Owner-only: remove a single hashtag from a post (the tag itself is kept
// globally). Returns { tag_list } with the post's remaining tags.
export const removePostTag = async (postId, tagName) => {
  const res = await fetch(
    `${BASE}/articles/${postId}/tags?name=${encodeURIComponent(tagName)}`,
    { method: 'DELETE', ...CREDS },
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

// Like / unlike a post. The liker is derived from the session cookie on the
// backend. Both return { liked, like_count } with the post's fresh total.
const setLike = async (postId, liked) => {
  const res = await fetch(`${BASE}/articles/${postId}/like`, {
    method: liked ? 'POST' : 'DELETE',
    ...CREDS,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

export const likeArticle = (postId) => setLike(postId, true);

export const unlikeArticle = (postId) => setLike(postId, false);

// A post's comments as a tree: top-level comments oldest first, each with its
// `replies`. Throws on 404 / 503, so the dialog can tell "no comments" from an outage.
export const fetchComments = async (postId) => {
  const res = await fetch(`${BASE}/articles/${postId}/comments`, CREDS);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

// Comment on a post, or reply to a top-level comment with `parentId`. The writer
// comes from the session cookie; the backend sanitizes `bodyHtml`. Returns
// { comment, comment_count }.
export const createComment = async (postId, bodyHtml, parentId = null) => {
  const res = await fetch(`${BASE}/articles/${postId}/comments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    ...CREDS,
    body: JSON.stringify({ body_html: bodyHtml, parent_id: parentId }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

// Writer-only: delete a comment (its replies go with it). Returns
// { deleted, id, comment_count }.
export const deleteComment = async (commentId) => {
  const res = await fetch(`${BASE}/comments/${commentId}`, { method: 'DELETE', ...CREDS });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

// Paged user list for the Users page. `q` filters by username or name on the
// backend; limit/offset drive the "first 10 + Load More" flow.
export const fetchUsers = (q = '', limit = 10, offset = 0) =>
  fetch(`${BASE}/users?q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}`, CREDS)
    .then(r => r.json());

export const fetchUserProfile = async (username) => {
  const res = await fetch(`${BASE}/users/${encodeURIComponent(username)}`, CREDS);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return res.json();
};

export const searchTags = (q) =>
  fetch(`${BASE}/tags/search?q=${encodeURIComponent(q)}`, CREDS).then(r => r.json());

// Follow / unfollow. The follower is derived from the session cookie on the
// backend; we only pass the target user's id. Both return { following: bool }.
export const followUser = async (userId) => {
  const res = await fetch(`${BASE}/users/${userId}/follow`, { method: 'POST', ...CREDS });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

export const unfollowUser = async (userId) => {
  const res = await fetch(`${BASE}/users/${userId}/follow`, { method: 'DELETE', ...CREDS });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

// Public lists: `side` is 'followers' (who follows <username>) or 'following'
// (who <username> follows). Throws on 404 / 503 so the profile can show an error.
const fetchFollowList = async (username, side) => {
  const res = await fetch(`${BASE}/users/${encodeURIComponent(username)}/${side}`, CREDS);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

export const fetchFollowers = (username) => fetchFollowList(username, 'followers');

export const fetchFollowing = (username) => fetchFollowList(username, 'following');

// Author is derived from the session cookie on the backend — no email arg.
// `bodyHtml` is the WYSIWYG editor's HTML; the backend sanitizes it server-side.
export const createArticle = async (title, bodyHtml, tags = [], mainImage = '') => {
  const res = await fetch(`${BASE}/articles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    ...CREDS,
    body: JSON.stringify({
      article: { title, body_html: bodyHtml, tags, main_image: mainImage || undefined },
    }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
};

// POST `body` as JSON; resolves to the JSON reply. A failure throws an Error with
// the backend's message and the HTTP `status`.
const postJson = async (route, body) => {
  const res = await fetch(`${BASE}${route}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    ...CREDS,
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

// AI assistance: suggestions only, nothing is stored. Each one throws on 401, 429
// (the user's or the site's daily AI limit, or a busy AI service) and 503 (AI off
// or failing), with a message meant for the user.

// Correct a draft's spelling and grammar: `format` 'html' for the post editor,
// 'text' for a comment. Resolves to the corrected draft (HTML is sanitized).
export const aiCorrect = (text, format = 'text') =>
  postJson('/ai/correct', { text, format }).then((data) => data.text);

// Draft a post body from its title and tags. Resolves to sanitized HTML.
export const aiSuggestPost = (title, tags = []) =>
  postJson('/ai/suggest-post', { title, tags }).then((data) => data.body_html);

// Propose a comment on a post, or a reply to its comment `parentId`, from what
// they say (the backend reads them). Resolves to plain text.
export const aiSuggestComment = (postId, parentId = null) =>
  postJson('/ai/suggest-comment', { post_id: postId, parent_id: parentId }).then((data) => data.text);

// Fetch `route` (GET unless `init` says otherwise) and resolve to its JSON reply;
// a failure throws like postJson, with the backend's message and the HTTP `status`.
const requestJson = async (route, init = {}) => {
  const res = await fetch(`${BASE}${route}`, { ...CREDS, ...init });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

// The reasons a report can give, as the backend accepts them.
export const REPORT_REASONS = [
  { value: 'spam', label: 'Spam' },
  { value: 'harassment', label: 'Harassment' },
  { value: 'hate', label: 'Hate' },
  { value: 'misinformation', label: 'Misinformation' },
  { value: 'other', label: 'Something else' },
];

// Report a post ({ postId }) or a comment ({ commentId }) to the admins, with a
// reason and an optional note. Resolves to { reported, already }: `already` is
// true when this user had reported it before.
export const reportContent = ({ postId = null, commentId = null }, reason, details = '') =>
  postJson('/reports', { post_id: postId, comment_id: commentId, reason, details });

// Admin only (the backend answers 403 to anyone else).

// The newest reports with `status` 'open' or 'resolved', each with its target,
// the target's author and the reporter.
export const fetchReports = (status = 'open') =>
  requestJson(`/admin/reports?status=${encodeURIComponent(status)}`);

// Dismiss a report: the content stays. (Deleting the content removes its reports.)
export const resolveReport = (reportId) => postJson(`/admin/reports/${reportId}/resolve`, {});

// Up to 20 users matching `q` (username or name), or only the banned ones.
export const fetchAdminUsers = (q = '', bannedOnly = false) =>
  requestJson(`/admin/users?q=${encodeURIComponent(q)}${bannedOnly ? '&banned=1' : ''}`);

// Ban (logs the user out everywhere and blocks login) or unban. Resolves to the user.
export const banUser = (userId) => postJson(`/admin/users/${userId}/ban`, {});

export const unbanUser = (userId) => requestJson(`/admin/users/${userId}/ban`, { method: 'DELETE' });

// Upload an image file to local backend storage; returns { url }, a relative
// /uploads/<file> path (same origin as the page). Used by the
// post editor (cover image) and the Edit Profile page (avatar).
export const uploadImage = async (file) => {
  const form = new FormData();
  form.append('file', file);
  // No Content-Type header — the browser sets the multipart boundary itself.
  const res = await fetch(`${BASE}/upload`, { method: 'POST', ...CREDS, body: form });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Upload failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

// Update the logged-in user's profile (name / bio / profile_image).
export const updateMe = async (patch) => {
  const res = await fetch(`${BASE}/me`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    ...CREDS,
    body: JSON.stringify(patch),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

// Signup. Backend hashes the password with bcrypt and auto-creates a session
// (the Set-Cookie comes back on the same response).
export const createUser = async (name, username, email, bio = '', password = '') => {
  const res = await fetch(`${BASE}/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    ...CREDS,
    body: JSON.stringify({ name, username, email, bio, password }),
  });
  const data = await res.json();
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

export const loginUser = async (email, password) => {
  const res = await fetch(`${BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    ...CREDS,
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};

// Ask for a password-reset link by email. Resolves to the same { message } whether
// or not the address has an account; throws with status 503 when mail is off.
export const requestPasswordReset = (email) => postJson('/password/forgot', { email });

// Set a new password with the token from the emailed link. Resolves to { message };
// throws with status 400 for a bad, used or expired link. It does not log in, and
// every session of the account is ended.
export const resetPassword = (token, password) => postJson('/password/reset', { token, password });

// The home page's sidebar. Who to follow: friends of friends, then people on the
// same tags, then the most followed (a guest gets those). Each user has is_agent
// and a `reason`: {kind: 'friends', count} | {kind: 'tags', tags} | {kind: 'popular', count}.
export const fetchSuggestedUsers = (limit = 5) => requestJson(`/users/suggested?limit=${limit}`);

// The tags on the most posts of the last `hours` hours: [{name, post_count}].
export const fetchTrendingTags = (hours = 24, limit = 10) =>
  requestJson(`/tags/trending?hours=${hours}&limit=${limit}`);

// allDevices=true logs out every session for the user; default = this device only.
export const logoutUser = (allDevices = false) =>
  fetch(`${BASE}/logout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    ...CREDS,
    body: JSON.stringify({ allDevices }),
  }).then(r => r.json().catch(() => ({})));

// Returns the current user if a valid session cookie is present, otherwise null.
export const fetchMe = async () => {
  const res = await fetch(`${BASE}/me`, CREDS);
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
};
