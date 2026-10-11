import { useContext, useEffect, useState, useRef } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import Avatar from '@mui/material/Avatar';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Link from '@mui/material/Link';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import AgentBadge from './AgentBadge';
import { fetchSuggestedUsers, fetchTrendingTags, followUser } from '../api/api';
import { UserContext } from '../context/UserContext';

const TRENDING_HOURS = 24;
const MAX_PEOPLE = 3;   // Keep discovery compact at every width.

// Why someone is suggested, from the API's `reason`.
function reasonText(reason) {
  if (reason.kind === 'friends') {
    return `Followed by ${reason.count} ${reason.count === 1 ? 'person' : 'people'} you follow`;
  }
  if (reason.kind === 'tags') {
    return `Also writes about ${reason.tags.map((tag) => `#${tag}`).join(', ')}`;
  }
  return `${reason.count} ${reason.count === 1 ? 'follower' : 'followers'}`;
}

const sectionSx = { p: 2, textAlign: 'start' };
const titleSx = { color: 'text.primary', fontWeight: 700, mb: 1 };

// Each discovery section loads independently, without blocking the feed.
export default function HomeSidebar() {
  const { currentUser, authReady } = useContext(UserContext);
  const [tags, setTags] = useState(null);
  const [people, setPeople] = useState(null);
  const [busyIds, setBusyIds] = useState(new Set());
  const pendingFollows = useRef(new Set());
  const peopleRequest = useRef(0);
  const [tagsError, setTagsError] = useState('');
  const [peopleError, setPeopleError] = useState('');
  const [tagsRetry, setTagsRetry] = useState(0);
  const [peopleRetry, setPeopleRetry] = useState(0);
  const [followError, setFollowError] = useState('');
  const viewerId = currentUser?.id ?? null;

  useEffect(() => {
    let cancelled = false;
    setTags(null);
    setTagsError('');
    fetchTrendingTags(TRENDING_HOURS)
      .then((list) => { if (!cancelled) setTags(list); })
      .catch(() => { if (!cancelled) setTagsError('Trending tags are unavailable.'); });
    return () => { cancelled = true; };
  }, [tagsRetry]);

  // Suggestions depend on the viewer: wait for the session check, and load them
  // again after a login or a logout.
  useEffect(() => {
    if (!authReady) return undefined;
    let cancelled = false;
    const request = ++peopleRequest.current;
    setPeople(null);
    setPeopleError('');
    setFollowError('');
    pendingFollows.current.clear();
    setBusyIds(new Set());
    fetchSuggestedUsers()
      .then((list) => { if (!cancelled) setPeople(list); })
      .catch(() => { if (!cancelled) setPeopleError('Suggestions are unavailable.'); });
    return () => { cancelled = true; peopleRequest.current = request + 1; };
  }, [authReady, viewerId, peopleRetry]);

  const handleFollow = async (user) => {
    if (pendingFollows.current.has(user.id)) return;
    const request = peopleRequest.current;
    pendingFollows.current.add(user.id);
    setBusyIds(new Set(pendingFollows.current));
    setFollowError('');
    try {
      await followUser(user.id);
      if (request === peopleRequest.current) setPeople((list) => list.filter((u) => u.id !== user.id));
    } catch (err) {
      if (request === peopleRequest.current) setFollowError(err.message || 'Could not follow. Try again.');
    } finally {
      if (request === peopleRequest.current) {
        pendingFollows.current.delete(user.id);
        setBusyIds(new Set(pendingFollows.current));
      }
    }
  };


  return (
    <Box
      data-testid="home-sidebar"
      sx={{
        display: 'grid',
        gap: 2,
        // Side by side below the feed on a tablet, stacked in the side column.
        gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', lg: '1fr' },
        alignItems: 'start',
      }}
    >
      <Paper variant="outlined" data-testid="trending-tags" sx={sectionSx}>
        <Typography variant="subtitle1" component="h2" sx={titleSx}>
          Trending ({TRENDING_HOURS}h)
        </Typography>
        {tagsError ? (
          <Alert severity="warning" action={<Button color="inherit" onClick={() => setTagsRetry(n => n + 1)}>Retry</Button>}>{tagsError}</Alert>
        ) : tags === null ? (
          <Typography role="status" variant="body2" color="text.secondary">Loading trending tags...</Typography>
        ) : tags.length === 0 ? (
          <Typography variant="body2" color="text.secondary" data-testid="trending-empty">
            No new posts in the last {TRENDING_HOURS} hours.
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
            {tags.map((tag) => (
              <Chip
                key={tag.name}
                data-testid="trending-tag"
                component={RouterLink}
                to={`/tag/${encodeURIComponent(tag.name)}`}
                clickable
                size="small"
                label={`#${tag.name}`}
                title={`${tag.post_count} ${tag.post_count === 1 ? 'post' : 'posts'} in the last ${TRENDING_HOURS} hours`}
                sx={{ maxWidth: '100%' }}
              />
            ))}
          </Box>
        )}
      </Paper>

      <Paper variant="outlined" data-testid="who-to-follow" sx={{ ...sectionSx, p: { xs: 1.5, sm: 2 } }}>
        <Typography variant="subtitle1" component="h2" sx={titleSx}>Who to follow</Typography>
        {followError && <Alert severity="error" sx={{ mb: 1 }}>{followError}</Alert>}
        {peopleError && <Alert severity="warning" action={<Button color="inherit" onClick={() => setPeopleRetry(n => n + 1)}>Retry</Button>}>{peopleError}</Alert>}
        {!peopleError && people === null && <Typography role="status" variant="body2" color="text.secondary">Loading suggestions...</Typography>}
        {people?.length === 0 && <Typography variant="body2" color="text.secondary">You're all caught up. Discover more people on the Users page.</Typography>}
        <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0, display: 'grid', gap: { xs: 1, sm: 1.5 } }}>
          {people?.slice(0, MAX_PEOPLE).map((user) => (
            <Box
              component="li"
              key={user.id}
              data-testid="suggested-user"
              data-username={user.username}
              sx={{ display: 'flex', alignItems: 'center', gap: { xs: 1, sm: 1.5 } }}
            >
              <Avatar src={user.profile_image || user.avatar || undefined} alt={user.name} sx={{ width: { xs: 32, sm: 40 }, height: { xs: 32, sm: 40 } }}>
                {user.name?.[0] ?? '?'}
              </Avatar>
              <Box sx={{ minWidth: 0, flex: 1, overflowWrap: 'anywhere' }}>
                <Link
                  component={RouterLink}
                  to={`/profile/${encodeURIComponent(user.username)}`}
                  underline="hover"
                  sx={{ color: 'text.primary', fontWeight: 600 }}
                >
                  {user.name}
                </Link>
                <Typography variant="body2" color="text.secondary">@{user.username}</Typography>
                {user.is_agent && <AgentBadge sx={{ mt: 0.5 }} />}
                <Typography variant="caption" color="text.secondary" component="p" data-testid="suggested-reason">
                  {reasonText(user.reason)}
                </Typography>
              </Box>
              {currentUser && (
                <Button
                  size="small"
                  variant="outlined"
                  data-testid="suggested-follow"
                  disabled={busyIds.has(user.id)}
                  onClick={() => handleFollow(user)}
                >
                  Follow
                </Button>
              )}
            </Box>
          ))}
        </Box>
      </Paper>
    </Box>
  );
}
