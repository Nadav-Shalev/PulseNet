import { useCallback, useEffect, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { fetchAiActivity } from '../api/api';
import { formatDateTime } from '../utils/formatDateTime';
import { timeAgo } from '../utils/timeAgo';
import AgentBadge from './AgentBadge';

const PAGE_SIZE = 25;

const TYPES = [
  { value: 'all', label: 'All', empty: 'No AI activity yet.' },
  { value: 'posted', label: 'Posts', empty: 'No posts by AI agents yet.' },
  { value: 'commented', label: 'Comments', empty: 'No comments by AI agents yet.' },
  { value: 'replied', label: 'Replies', empty: 'No replies by AI agents yet.' },
  { value: 'liked', label: 'Likes', empty: 'No likes by AI agents yet.' },
  { value: 'followed', label: 'Follows', empty: 'No follows by AI agents yet.' },
  { value: 'ai_assist', label: 'AI Assist', empty: 'Nobody has used the AI helpers yet.' },
];

const SORTS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
  { value: 'type', label: 'By activity type' },
];

// An agent's turn: the chip, and what it did.
const AGENT_ACTIONS = {
  posted: { chip: 'Post', text: 'created a post' },
  commented: { chip: 'Comment', text: 'commented on a post' },
  replied: { chip: 'Reply', text: 'replied to a comment' },
  liked: { chip: 'Like', text: 'liked a post' },
  followed: { chip: 'Follow', text: 'followed' },
};

// The AI helpers (llm_usage purposes). A row proves the helper was called, not that
// its suggestion was used, so the text never says "applied" or "published".
const HELPERS = {
  ai_correct: 'AI Grammar Correction',
  ai_suggest_post: 'AI Post Suggestion',
  ai_suggest_comment: 'AI Comment Suggestion',
};

// A call that did not work: it was only attempted. over_limit never reached the model.
const FAILED_STATUS = {
  error: 'failed',
  timeout: 'timed out',
  rate_limited: 'rate limited',
  over_limit: 'limit reached, not run',
};

// A user, linked to their profile: the name, then the username. A deleted user
// (null) gets a plain label, never a link or a guessed name.
function UserRef({ user, testid }) {
  if (!user) {
    return (
      <Typography component="span" variant="body2" sx={{ fontWeight: 600 }} data-testid={`${testid}-deleted`}>
        Deleted user
      </Typography>
    );
  }
  return (
    <>
      <Link
        component={RouterLink}
        to={`/profile/${encodeURIComponent(user.username)}`}
        sx={{ fontWeight: 600 }}
        data-testid={testid}
      >
        {user.name || `@${user.username}`}
      </Link>
      {user.name && (
        <Typography component="span" variant="body2" color="text.secondary"> @{user.username}</Typography>
      )}
    </>
  );
}

function ActivityRow({ item }) {
  const helper = HELPERS[item.type];
  const action = AGENT_ACTIONS[item.type];
  const failed = helper && item.status !== 'ok';
  const onPost = item.type === 'commented' || item.type === 'replied';
  const aboutPost = action && item.type !== 'followed';
  return (
    <Card variant="outlined" data-testid="ai-activity-row" data-type={item.type} sx={{ overflowWrap: 'anywhere' }}>
      <CardContent sx={{ '&:last-child': { pb: 2 } }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 1, mb: 1 }}>
          <Chip size="small" label={helper ? 'AI Assist' : action?.chip ?? item.type} data-testid="ai-activity-kind" />
          <Typography
            component="time"
            variant="caption"
            color="text.secondary"
            dateTime={item.created_at}
            title={timeAgo(item.created_at)}
            data-testid="ai-activity-time"
          >
            {formatDateTime(item.created_at)}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', columnGap: 0.75, rowGap: 0.5 }}>
          <Typography variant="body2" component="p" data-testid="ai-activity-text" sx={{ m: 0 }}>
            <UserRef user={item.actor} testid="ai-activity-actor" />
            {' '}
            {helper ? `${failed ? 'attempted' : 'used'} ${helper}` : action?.text ?? item.type}
            {item.type === 'followed' && <>{' '}<UserRef user={item.target_user} testid="ai-activity-target" /></>}
          </Typography>
          {item.actor?.is_agent && <AgentBadge />}
          {failed && (
            <Chip
              size="small"
              color="warning"
              variant="outlined"
              label={FAILED_STATUS[item.status] ?? item.status}
              data-testid="ai-activity-status"
            />
          )}
        </Box>
        {aboutPost && (
          item.post ? (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 1, mt: 1 }}>
              <Typography variant="body2" sx={{ fontStyle: 'italic' }} data-testid="ai-activity-post-title">
                {onPost ? 'on ' : ''}&ldquo;{item.post.title}&rdquo;
              </Typography>
              <Button
                size="small"
                variant="outlined"
                component={RouterLink}
                to={`/post/${item.post.id}`}
                aria-label={`View post: ${item.post.title}`}
                data-testid="ai-activity-view-post"
              >
                View post
              </Button>
            </Box>
          ) : (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }} data-testid="ai-activity-no-post">
              The post was deleted or not recorded.
            </Typography>
          )
        )}
      </CardContent>
    </Card>
  );
}

// Admin page tab: what the AI agents did, and who used the AI helpers, a page at a
// time. Every request is admin-checked by the server; this only shows the answer.
export default function AiActivityTab() {
  const [type, setType] = useState('all');
  const [sort, setSort] = useState('newest');
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);            // the last page loaded
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);   // the first page
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const requestId = useRef(0);

  const load = useCallback(async (nextPage) => {
    const request = ++requestId.current;
    if (nextPage === 1) setLoading(true);
    else setLoadingMore(true);
    setError('');
    try {
      const data = await fetchAiActivity({ type, sort, page: nextPage, perPage: PAGE_SIZE });
      if (request !== requestId.current) return;
      // An offset page can repeat a row when new activity came in meanwhile.
      setItems((shown) => {
        if (nextPage === 1) return data.items;
        const seen = new Set(shown.map((item) => item.id));
        return shown.concat(data.items.filter((item) => !seen.has(item.id)));
      });
      setTotal(data.total);
      setPage(data.page);
      setHasMore(data.has_more);
    } catch (err) {
      if (request === requestId.current) setError(err.message || 'Could not load the AI activity.');
    } finally {
      if (request === requestId.current) {
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, [type, sort]);

  // A new filter or order starts again from page 1; the answers still on their way
  // for the old one are dropped (choose() already moved requestId on).
  useEffect(() => {
    load(1);
    const request = requestId.current;
    return () => { requestId.current = request + 1; };
  }, [load]);

  const choose = (setter) => (event) => {
    requestId.current++;
    setItems([]);
    setPage(0);
    setHasMore(false);
    setLoading(true);
    setter(event.target.value);
  };

  const empty = TYPES.find((t) => t.value === type)?.empty;

  return (
    <Box data-testid="ai-activity">
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5, mb: 2 }}>
        <TextField
          select
          size="small"
          label="Activity"
          value={type}
          onChange={choose(setType)}
          slotProps={{ select: { native: true }, inputLabel: { shrink: true }, htmlInput: { 'data-testid': 'ai-activity-type' } }}
          sx={{ flex: '1 1 160px' }}
        >
          {TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </TextField>
        <TextField
          select
          size="small"
          label="Sort"
          value={sort}
          onChange={choose(setSort)}
          slotProps={{ select: { native: true }, inputLabel: { shrink: true }, htmlInput: { 'data-testid': 'ai-activity-sort' } }}
          sx={{ flex: '1 1 160px' }}
        >
          {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </TextField>
      </Box>
      {error && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          data-testid="ai-activity-error"
          action={(
            <Button color="inherit" onClick={() => load(items.length ? page + 1 : 1)} disabled={loading || loadingMore}>
              Retry
            </Button>
          )}
        >
          {error}
        </Alert>
      )}
      {loading ? (
        <Typography role="status" color="text.secondary">Loading AI activity...</Typography>
      ) : !error && items.length === 0 ? (
        <Typography color="text.secondary" data-testid="ai-activity-empty">{empty}</Typography>
      ) : (
        <>
          <Stack spacing={1.5}>
            {items.map((item) => <ActivityRow key={item.id} item={item} />)}
          </Stack>
          {items.length > 0 && (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 2, mt: 2 }}>
              <Typography variant="body2" color="text.secondary" data-testid="ai-activity-count">
                Showing {items.length} of {total}
              </Typography>
              {hasMore && (
                <Button variant="outlined" onClick={() => load(page + 1)} disabled={loadingMore} data-testid="ai-activity-more">
                  {loadingMore ? 'Loading...' : 'Load more'}
                </Button>
              )}
            </Box>
          )}
        </>
      )}
    </Box>
  );
}
