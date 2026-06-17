// Relative "time ago" formatting (requirement c.iii) — no external deps.

// Convert a date-ish value into "2 hours ago". Returns the original string
// unchanged if it isn't a parseable date (lets callers pass through pre-formatted
// labels like DEV.to's "Just now").
export function timeAgo(value) {
  if (!value) return '';
  const then = new Date(value);
  if (Number.isNaN(then.getTime())) return String(value);

  const seconds = Math.floor((Date.now() - then.getTime()) / 1000);
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds} seconds ago`;

  const units = [
    ['minute', 60],
    ['hour',   60],
    ['day',    24],
    ['week',    7],
    ['month',  4.345],   // weeks per month (approx)
    ['year',   12],      // months per year
  ];

  let amount = seconds / 60;          // start in minutes
  let label = 'minute';
  for (let i = 0; i < units.length; i++) {
    label = units[i][0];
    const next = units[i + 1];
    if (!next || amount < next[1]) break;
    amount = amount / next[1];
  }
  const n = Math.floor(amount);
  return `${n} ${label}${n === 1 ? '' : 's'} ago`;
}

// Prefer the precise created_at timestamp; fall back to the legacy display date
// string for any post that lacks one.
export function postTimeAgo(post) {
  if (post?.created_at) {
    const t = timeAgo(post.created_at);
    if (t) return t;
  }
  return post?.readable_publish_date || '';
}
