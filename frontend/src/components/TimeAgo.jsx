import { useClockTick } from '../utils/clock';
import { postTimeAgo, timeAgo } from '../utils/timeAgo';

// "5 minutes ago" that keeps itself current: the shared minute clock re-renders just
// this text, not the card around it. The wording is timeAgo's / postTimeAgo's.
//   <TimeAgo post={post} />   <TimeAgo value={comment.created_at} />
export default function TimeAgo({ value, post }) {
  useClockTick();
  return post ? postTimeAgo(post) : timeAgo(value);
}
