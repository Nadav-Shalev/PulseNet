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

export const fetchUserByEmail = async (email) => {
  const res = await fetch(`${BASE}/users/by-email?email=${encodeURIComponent(email)}`, CREDS);
  if (res.status === 404) {
    const err = new Error('User not found');
    err.status = 404;
    throw err;
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return res.json();
};

// Paged user list for the Users page. `q` filters by email on the backend;
// limit/offset drive the "first 10 + Load More" flow.
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

export const fetchFollowers = (username) =>
  fetch(`${BASE}/users/${encodeURIComponent(username)}/followers`, CREDS).then(r => r.json());

export const fetchFollowing = (username) =>
  fetch(`${BASE}/users/${encodeURIComponent(username)}/following`, CREDS).then(r => r.json());

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

// Upload an image file to local backend storage; returns { url }. Used by the
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
