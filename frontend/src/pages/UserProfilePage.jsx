import { useEffect, useState, useContext } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Avatar from '@mui/material/Avatar';
import Typography from '@mui/material/Typography';
import Divider from '@mui/material/Divider';
import CircularProgress from '@mui/material/CircularProgress';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemAvatar from '@mui/material/ListItemAvatar';
import ListItemText from '@mui/material/ListItemText';
import IconButton from '@mui/material/IconButton';
import CloseIcon from '@mui/icons-material/Close';
import Feed from '../features/feed/Feed';
import { fetchUserProfile, followUser, unfollowUser, fetchFollowing } from '../api/api';
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
  const [followingOpen, setFollowingOpen] = useState(false);
  const [followingList, setFollowingList] = useState([]);
  const [followingLoading, setFollowingLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
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

  const handleOpenFollowing = async () => {
    setFollowingOpen(true);
    setFollowingLoading(true);
    try {
      const rows = await fetchFollowing(username);   // reuses the Phase 1 endpoint
      setFollowingList(Array.isArray(rows) ? rows : []);
    } catch {
      setFollowingList([]);
    } finally {
      setFollowingLoading(false);
    }
  };

  const goToProfile = (uname) => {
    setFollowingOpen(false);                          // close cleanly before navigating
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

  return (
    <Box sx={{ p: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
        <Avatar
          src={user.profile_image || user.avatar}
          alt={user.name}
          sx={{ width: 96, height: 96 }}
        >
          {user.name?.[0] ?? '?'}
        </Avatar>
        <Box>
          <Typography data-testid="profile-name" variant="h5" fontWeight={700}>{user.name}</Typography>
          <Typography data-testid="profile-username" variant="body2" color="text.secondary">@{user.username}</Typography>
          {user.bio && (
            <Typography data-testid="profile-bio" variant="body2" sx={{ mt: 1, maxWidth: 600 }}>
              {user.bio}
            </Typography>
          )}
          <Box sx={{ display: 'flex', gap: 2, mt: 1, flexWrap: 'wrap' }}>
            <Typography variant="body2" color="text.secondary">
              <strong>{followersCount}</strong> {followersCount === 1 ? 'follower' : 'followers'}
            </Typography>
            <Typography
              variant="body2"
              color="text.secondary"
              onClick={isOwnProfile ? handleOpenFollowing : undefined}
              sx={{
                cursor: isOwnProfile ? 'pointer' : 'default',
                '&:hover': isOwnProfile ? { textDecoration: 'underline' } : undefined,
              }}
            >
              <strong>{user.following_count ?? 0}</strong> following
            </Typography>
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

      <Divider sx={{ mb: 2 }} />

      <Feed username={username} manage={!!isOwnProfile} />

      {/* Own-profile only: list of users this person follows */}
      <Dialog open={followingOpen} onClose={() => setFollowingOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ pr: 6 }}>
          Following
          <IconButton
            onClick={() => setFollowingOpen(false)}
            sx={{ position: 'absolute', right: 8, top: 8 }}
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          {followingLoading ? (
            <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
              Loading following...
            </Typography>
          ) : followingList.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
              You are not following anyone yet.
            </Typography>
          ) : (
            <List disablePadding>
              {followingList.map(u => (
                <ListItemButton key={u.id} onClick={() => goToProfile(u.username)}>
                  <ListItemAvatar>
                    <Avatar src={u.profile_image || u.avatar} alt={u.name}>
                      {u.name?.[0] ?? '?'}
                    </Avatar>
                  </ListItemAvatar>
                  <ListItemText primary={u.name || `@${u.username}`} secondary={`@${u.username}`} />
                </ListItemButton>
              ))}
            </List>
          )}
        </DialogContent>
      </Dialog>
    </Box>
  );
}
