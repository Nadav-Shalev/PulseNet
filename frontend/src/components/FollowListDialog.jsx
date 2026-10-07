import { useEffect, useState } from 'react';
import Alert from '@mui/material/Alert';
import Avatar from '@mui/material/Avatar';
import Dialog from '@mui/material/Dialog';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItemAvatar from '@mui/material/ListItemAvatar';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemText from '@mui/material/ListItemText';
import Typography from '@mui/material/Typography';
import CloseIcon from '@mui/icons-material/Close';
import { fetchFollowers, fetchFollowing } from '../api/api';

const LOADERS = { followers: fetchFollowers, following: fetchFollowing };
const TITLES = { followers: 'Followers', following: 'Following' };

const emptyText = (kind, username, isOwnProfile) => {
  if (kind === 'followers') {
    return isOwnProfile ? 'You have no followers yet.' : `@${username} has no followers yet.`;
  }
  return isOwnProfile ? 'You are not following anyone yet.' : `@${username} is not following anyone yet.`;
};

// The followers or following list of any profile. The list is fetched each time
// the dialog opens, so it reflects a follow/unfollow made a moment ago.
export default function FollowListDialog({ open, kind, username, isOwnProfile, onClose, onSelectUser }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;                 // ignore a reply that arrives after a switch
    setRows([]);
    setError('');
    setLoading(true);
    LOADERS[kind](username)
      .then(data => { if (!cancelled) setRows(Array.isArray(data) ? data : []); })
      .catch(err => { if (!cancelled) setError(err.message || 'Could not load this list.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, kind, username]);

  let body;
  if (loading) {
    body = (
      <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
        Loading...
      </Typography>
    );
  } else if (error) {
    body = <Alert severity="error">{error}</Alert>;
  } else if (rows.length === 0) {
    body = (
      <Typography data-testid="follow-list-empty" variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
        {emptyText(kind, username, isOwnProfile)}
      </Typography>
    );
  } else {
    body = (
      <List disablePadding>
        {rows.map(u => (
          <ListItemButton key={u.id} data-testid="follow-list-item" onClick={() => onSelectUser(u.username)}>
            <ListItemAvatar>
              <Avatar src={u.profile_image || u.avatar} alt={u.name}>
                {u.name?.[0] ?? '?'}
              </Avatar>
            </ListItemAvatar>
            <ListItemText primary={u.name || `@${u.username}`} secondary={`@${u.username}`} />
          </ListItemButton>
        ))}
      </List>
    );
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth data-testid="follow-list-dialog">
      <DialogTitle sx={{ pr: 6 }}>
        {TITLES[kind]}
        <IconButton aria-label="Close" onClick={onClose} sx={{ position: 'absolute', right: 8, top: 8 }}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>{body}</DialogContent>
    </Dialog>
  );
}
