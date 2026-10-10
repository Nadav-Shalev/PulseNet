import { useContext, useEffect, useState } from 'react';
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
const PHONE_PEOPLE = 3;   // on a phone the sidebar sits above the feed: keep it short

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

// The home page's sidebar: trending tags and who to follow. A section whose
// request fails is left out, so the feed is never blocked by it.
export default function HomeSidebar() {
  const { currentUser, authReady } = useContext(UserContext);
  const [tags, setTags] = useState(null);       // null: loading, or failed (hidden)
  const [people, setPeople] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [followError, setFollowError] = useState('');
  const viewerId = currentUser?.id ?? null;

  useEffect(() => {
    let cancelled = false;
    fetchTrendingTags(TRENDING_HOURS)
      .then((list) => { if (!cancelled) setTags(list); })
      .catch(() => { if (!cancelled) setTags(null); });
    return () => { cancelled = true; };
  }, []);

  // Suggestions depend on the viewer: wait for the session check, and load them
  // again after a login or a logout.
  useEffect(() => {
    if (!authReady) return undefined;
    let cancelled = false;
    setFollowError('');
    fetchSuggestedUsers()
      .then((list) => { if (!cancelled) setPeople(list); })
      .catch(() => { if (!cancelled) setPeople(null); });
    return () => { cancelled = true; };
  }, [authReady, viewerId]);

  const handleFollow = async (user) => {
    setBusyId(user.id);
    setFollowError('');
    try {
      await followUser(user.id);
      setPeople((list) => list.filter((u) => u.id !== user.id));
    } catch (err) {
      setFollowError(err.message || 'Could not follow. Try again.');
    } finally {
      setBusyId(null);
    }
  };

  const showPeople = Array.isArray(people) && people.length > 0;
  if (!tags && !showPeople) return null;

  return (
    <Box
      data-testid="home-sidebar"
      sx={{
        display: 'grid',
        gap: 2,
        // Side by side above the feed on a tablet, stacked in the side column.
        gridTemplateColumns: { xs: '1fr', sm: tags && showPeople ? '1fr 1fr' : '1fr', lg: '1fr' },
        alignItems: 'start',
      }}
    >
      {tags && (
        <Paper variant="outlined" data-testid="trending-tags" sx={sectionSx}>
          <Typography variant="subtitle1" component="h2" sx={titleSx}>
            Trending ({TRENDING_HOURS}h)
          </Typography>
          {tags.length === 0 ? (
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
      )}

      {showPeople && (
        <Paper variant="outlined" data-testid="who-to-follow" sx={sectionSx}>
          <Typography variant="subtitle1" component="h2" sx={titleSx}>Who to follow</Typography>
          {followError && <Alert severity="error" sx={{ mb: 1 }}>{followError}</Alert>}
          <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0, display: 'grid', gap: 1.5 }}>
            {people.map((user, index) => (
              <Box
                component="li"
                key={user.id}
                data-testid="suggested-user"
                data-username={user.username}
                sx={{ display: { xs: index < PHONE_PEOPLE ? 'flex' : 'none', sm: 'flex' }, alignItems: 'center', gap: 1.5 }}
              >
                <Avatar src={user.profile_image || user.avatar || undefined} alt={user.name} sx={{ width: 40, height: 40 }}>
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
                    disabled={busyId === user.id}
                    onClick={() => handleFollow(user)}
                  >
                    Follow
                  </Button>
                )}
              </Box>
            ))}
          </Box>
        </Paper>
      )}
    </Box>
  );
}
