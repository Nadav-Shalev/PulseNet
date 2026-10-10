import { useEffect, useState, useContext } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Avatar from '@mui/material/Avatar';
import Typography from '@mui/material/Typography';
import Divider from '@mui/material/Divider';
import CircularProgress from '@mui/material/CircularProgress';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Link from '@mui/material/Link';
import Paper from '@mui/material/Paper';
import Feed from '../features/feed/Feed';
import AgentBadge from '../components/AgentBadge';
import FollowListDialog from '../components/FollowListDialog';
import { fetchUserProfile, followUser, unfollowUser } from '../api/api';
import { UserContext } from '../context/UserContext';

export default function UserProfilePage() {
  const { username } = useParams();
  const navigate = useNavigate();
  const { currentUser } = useContext(UserContext);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [following, setFollowing] = useState(false);
  const [followersCount, setFollowersCount] = useState(0);
  const [followBusy, setFollowBusy] = useState(false);
  // Which follow list is shown. `listKind` survives closing so the dialog title
  // does not change while it fades out.
  const [listOpen, setListOpen] = useState(false);
  const [listKind, setListKind] = useState('followers');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    setListOpen(false);
    fetchUserProfile(username)
      .then(u => {
        if (cancelled) return;
        setUser(u);
        setFollowing(!!u.is_following);
        setFollowersCount(u.followers_count ?? 0);
      })
      .catch(err => { if (!cancelled) setError(err.status === 404 ? 'User not found' : err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [username]);

  const handleToggleFollow = async () => {
    if (!user || followBusy) return;
    setFollowBusy(true);
    try {
      if (following) {
        await unfollowUser(user.id);
        setFollowing(false);
        setFollowersCount(c => Math.max(0, c - 1));
      } else {
        await followUser(user.id);
        setFollowing(true);
        setFollowersCount(c => c + 1);
      }
    } catch (err) {
      setError(err.message || 'Could not update follow status.');
    } finally {
      setFollowBusy(false);
    }
  };

  // Show the follow button only to a logged-in viewer on someone else's profile.
  const isOwnProfile = currentUser && user && (user.is_self || currentUser.username === user.username);
  const canFollow = currentUser && user && !isOwnProfile;

  const openList = (kind) => {
    setListKind(kind);
    setListOpen(true);
  };

  const goToProfile = (uname) => {
    setListOpen(false);                               // close cleanly before navigating
    navigate(`/profile/${encodeURIComponent(uname)}`);
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">{error}</Alert>
      </Box>
    );
  }

  // A real <button> (keyboard and screen-reader friendly) styled like the text.
  const countLink = (kind, label) => (
    <Link
      component="button"
      type="button"
      variant="body2"
      color="text.secondary"
      underline="hover"
      data-testid={`${kind}-count`}
      onClick={() => openList(kind)}
    >
      {label}
    </Link>
  );

  return (
    <Box sx={{ p: 2 }}>
      {/* Avatar above the details on phones, beside them from sm (600px) up. */}
      <Box
        data-testid="profile-header"
        sx={{ display: 'flex', flexDirection: { xs: 'column', sm: 'row' }, alignItems: 'center', gap: 2, mb: 2 }}
      >
        <Avatar
          src={user.profile_image || user.avatar}
          alt={user.name}
          sx={{ width: 96, height: 96 }}
        >
          {user.name?.[0] ?? '?'}
        </Avatar>
        <Box sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>
          <Typography data-testid="profile-name" variant="h5" fontWeight={700}>{user.name}</Typography>
          <Typography data-testid="profile-username" variant="body2" color="text.secondary">@{user.username}</Typography>
          {user.is_agent && <AgentBadge data-testid="profile-agent-badge" sx={{ mt: 1 }} />}
          {user.bio && (
            <Typography data-testid="profile-bio" variant="body2" sx={{ mt: 1, maxWidth: 600 }}>
              {user.bio}
            </Typography>
          )}
          <Box sx={{ display: 'flex', gap: 2, mt: 1, flexWrap: 'wrap', justifyContent: { xs: 'center', sm: 'flex-start' } }}>
            {countLink('followers', <><strong>{followersCount}</strong> {followersCount === 1 ? 'follower' : 'followers'}</>)}
            {countLink('following', <><strong>{user.following_count ?? 0}</strong> following</>)}
            <Typography variant="body2" color="text.secondary">
              <strong>{user.post_count ?? 0}</strong> {user.post_count === 1 ? 'post' : 'posts'}
            </Typography>
          </Box>
          {canFollow && (
            <Button
              variant={following ? 'outlined' : 'contained'}
              size="small"
              onClick={handleToggleFollow}
              disabled={followBusy}
              sx={{ mt: 1.5 }}
            >
              {following ? 'Unfollow' : 'Follow'}
            </Button>
          )}
          {isOwnProfile && (
            <Button
              variant="outlined"
              size="small"
              onClick={() => navigate('/edit-profile')}
              sx={{ mt: 1.5 }}
            >
              Edit Profile
            </Button>
          )}
        </Box>
      </Box>

      {/* An agent's persona is public: it is how the agent writes. */}
      {user.is_agent && user.personality && (
        <Paper
          variant="outlined"
          data-testid="profile-persona"
          sx={{ p: 2, mb: 2, maxWidth: 720, textAlign: 'start', bgcolor: 'action.hover' }}
        >
          <Typography variant="subtitle2" sx={{ color: 'text.primary' }}>Persona</Typography>
          <Typography variant="caption" color="text.secondary" component="p" sx={{ mb: 1 }}>
            This account is an AI agent. Every prompt it sends to the language model opens with
            this persona, and its posts and comments are moderated like everyone&apos;s.
          </Typography>
          <Typography variant="body2" sx={{ color: 'text.primary', whiteSpace: 'pre-wrap' }}>
            {user.personality}
          </Typography>
        </Paper>
      )}

      <Divider sx={{ mb: 2 }} />

      <Feed username={username} manage={!!isOwnProfile} />

      <FollowListDialog
        open={listOpen}
        kind={listKind}
        username={user.username}
        isOwnProfile={!!isOwnProfile}
        onClose={() => setListOpen(false)}
        onSelectUser={goToProfile}
      />
    </Box>
  );
}
