// An exact date and time in the reader's own time zone, day first:
// "15/10/2026, 19:00". timeAgo says how long ago; this says exactly when.
const FORMAT = new Intl.DateTimeFormat('en-GB', { dateStyle: 'short', timeStyle: 'short' });

// '' for a missing value; the value itself when it is not a date.
export function formatDateTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return FORMAT.format(date);
}
