import { useCallback, useContext, useEffect, useState } from 'react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardActions from '@mui/material/CardActions';
import CardContent from '@mui/material/CardContent';
import Checkbox from '@mui/material/Checkbox';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import FormControlLabel from '@mui/material/FormControlLabel';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Typography from '@mui/material/Typography';
import {
  REPORT_REASONS, banUser, deleteArticle, deleteComment, fetchAdminUsers, fetchReports,
  resolveReport, unbanUser,
} from '../api/api';
import { UserContext } from '../context/UserContext';
import { timeAgo } from '../utils/timeAgo';

const reasonLabel = (value) => REPORT_REASONS.find(r => r.value === value)?.label ?? value;

const profileLink = (username) => (
  <Link component={RouterLink} to={`/profile/${encodeURIComponent(username)}`}>@{username}</Link>
);

// One report: what was reported, by whom, why, and (while open) the three ways to
// handle it. `details` and the excerpt are plain text: React escapes them.
function ReportCard({ report, busy, onAction }) {
  const { target, author } = report;
  const isPost = target.type === 'post';
  const open = report.status === 'open';
  return (
    <Card variant="outlined" data-testid="admin-report" sx={{ overflowWrap: 'anywhere' }}>
      <CardContent sx={{ pb: 1 }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 1, mb: 1 }}>
          <Chip size="small" label={isPost ? 'Post' : 'Comment'} />
          <Chip size="small" color="warning" variant="outlined" label={reasonLabel(report.reason)} />
          <Typography variant="caption" color="text.secondary">{timeAgo(report.created_at)}</Typography>
        </Box>
        <Typography variant="subtitle2">
          {isPost ? target.post_title : <>Comment on &ldquo;{target.post_title}&rdquo;</>}
        </Typography>
        <Typography variant="body2" color="text.secondary" data-testid="admin-report-excerpt" sx={{ mt: 0.5 }}>
          {target.excerpt || '(empty)'}
        </Typography>
        <Typography variant="body2" sx={{ mt: 1 }}>
          By {profileLink(author.username)}
          {author.is_banned && <Chip size="small" color="error" label="banned" sx={{ ml: 1 }} data-testid="admin-report-banned" />}
          {' · reported by '}{profileLink(report.reporter.username)}
        </Typography>
        {report.details && (
          <Typography variant="body2" data-testid="admin-report-details" sx={{ mt: 0.5, fontStyle: 'italic' }}>
            Note: {report.details}
          </Typography>
        )}
        {!open && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
            Dismissed{report.resolved_by ? ` by @${report.resolved_by}` : ''} {timeAgo(report.resolved_at)}
          </Typography>
        )}
      </CardContent>
      {open && (
        <CardActions sx={{ flexWrap: 'wrap', gap: 1, px: 2, pb: 2 }}>
          <Button size="small" variant="outlined" disabled={busy} onClick={() => onAction('dismiss', report)} data-testid="report-dismiss">
            Dismiss
          </Button>
          <Button size="small" variant="outlined" color="error" disabled={busy} onClick={() => onAction('delete', report)} data-testid="report-delete">
            Delete {isPost ? 'post' : 'comment'}
          </Button>
          {author.is_banned ? (
            <Button size="small" disabled={busy} onClick={() => onAction('unban', report)} data-testid="report-unban">
              Unban @{author.username}
            </Button>
          ) : (
            <Button size="small" color="error" disabled={busy} onClick={() => onAction('ban', report)} data-testid="report-ban">
              Ban @{author.username}
            </Button>
          )}
        </CardActions>
      )}
    </Card>
  );
}

// Reports: open (to handle) or resolved (dismissed). Deleting the content removes
// its reports; banning the author leaves the report open until it is handled.
function ReportsTab({ confirm }) {
  const [status, setStatus] = useState('open');
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError('');
    try {
      setReports(await fetchReports(status));
    } catch (err) {
      setError(err.message || 'Could not load the reports.');
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => { load(); }, [load]);

  const run = async (action) => {
    setBusy(true);
    setError('');
    try {
      await action();
      await load();
    } catch (err) {
      setError(err.message || 'That did not work.');
    } finally {
      setBusy(false);
    }
  };

  const handle = (kind, report) => {
    const { target, author } = report;
    if (kind === 'dismiss') {
      run(() => resolveReport(report.id));
    } else if (kind === 'delete') {
      const what = target.type === 'post' ? 'post' : 'comment';
      confirm({
        title: `Delete this ${what}?`,
        text: `The ${what} by @${author.username} will be permanently removed, with its reports`
          + (what === 'post' ? ', likes and comments.' : ' and replies.'),
        label: 'Delete',
        run: () => run(() => (what === 'post' ? deleteArticle(target.id) : deleteComment(target.id))),
      });
    } else if (kind === 'ban') {
      confirm({
        title: `Ban @${author.username}?`,
        text: 'They are logged out everywhere and cannot log in until unbanned. Their posts and '
          + 'comments stay, and this report stays open.',
        label: 'Ban',
        run: () => run(() => banUser(author.id)),
      });
    } else {
      run(() => unbanUser(author.id));
    }
  };

  return (
    <Box>
      <ToggleButtonGroup
        exclusive
        size="small"
        value={status}
        onChange={(_, v) => { if (v) { setLoading(true); setStatus(v); } }}
        sx={{ mb: 2 }}
      >
        <ToggleButton value="open" data-testid="reports-open">Open</ToggleButton>
        <ToggleButton value="resolved" data-testid="reports-resolved">Dismissed</ToggleButton>
      </ToggleButtonGroup>
      {error && <Alert severity="error" sx={{ mb: 2 }} data-testid="admin-error">{error}</Alert>}
      {loading ? (
        <Typography color="text.secondary">Loading reports...</Typography>
      ) : reports.length === 0 ? (
        <Typography color="text.secondary" data-testid="reports-empty">
          {status === 'open' ? 'No open reports.' : 'No dismissed reports.'}
        </Typography>
      ) : (
        <Stack spacing={2}>
          {reports.map(r => <ReportCard key={r.id} report={r} busy={busy} onAction={handle} />)}
        </Stack>
      )}
    </Box>
  );
}

// Users: find someone by username or name (or list the banned ones) to ban or unban.
function UsersTab({ confirm, me }) {
  const [q, setQ] = useState('');
  const [bannedOnly, setBannedOnly] = useState(false);
  const [users, setUsers] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError('');
    try {
      setUsers(await fetchAdminUsers(q.trim(), bannedOnly));
    } catch (err) {
      setError(err.message || 'Could not load users.');
    }
  }, [q, bannedOnly]);

  // Typing waits a moment, so a search is not sent for every key.
  useEffect(() => {
    const timer = setTimeout(load, 250);
    return () => clearTimeout(timer);
  }, [load]);

  const toggle = async (user) => {
    const act = async () => {
      setBusy(true);
      setError('');
      try {
        await (user.is_banned ? unbanUser(user.id) : banUser(user.id));
        await load();
      } catch (err) {
        setError(err.message || 'That did not work.');
      } finally {
        setBusy(false);
      }
    };
    if (user.is_banned) act();
    else confirm({
      title: `Ban @${user.username}?`,
      text: 'They are logged out everywhere and cannot log in until unbanned. Their posts and comments stay.',
      label: 'Ban',
      run: act,
    });
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 1, mb: 2 }}>
        <TextField
          size="small"
          placeholder="Search by username or name"
          value={q}
          onChange={e => setQ(e.target.value)}
          slotProps={{ htmlInput: { 'data-testid': 'admin-user-search' } }}
          sx={{ flex: '1 1 220px' }}
        />
        <FormControlLabel
          control={<Checkbox checked={bannedOnly} onChange={e => setBannedOnly(e.target.checked)} data-testid="admin-banned-only" />}
          label="Banned only"
        />
      </Box>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {users.length === 0 ? (
        <Typography color="text.secondary">No users found.</Typography>
      ) : (
        <Stack spacing={1}>
          {users.map(u => (
            <Card key={u.id} variant="outlined" data-testid="admin-user-row">
              <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 1, p: 1.5 }}>
                <Box sx={{ flex: '1 1 160px', minWidth: 0, overflowWrap: 'anywhere' }}>
                  {profileLink(u.username)}
                  {u.name && <Typography component="span" variant="body2" color="text.secondary"> {u.name}</Typography>}
                </Box>
                {u.role === 'admin' && <Chip size="small" color="primary" label="admin" />}
                {u.is_banned && <Chip size="small" color="error" label="banned" />}
                {/* An admin cannot be banned (nor ban themselves): the server says the same. */}
                {u.role !== 'admin' && u.id !== me.id && (
                  <Button
                    size="small"
                    color={u.is_banned ? 'primary' : 'error'}
                    disabled={busy}
                    onClick={() => toggle(u)}
                    data-testid="admin-user-ban"
                  >
                    {u.is_banned ? 'Unban' : 'Ban'}
                  </Button>
                )}
              </Box>
            </Card>
          ))}
        </Stack>
      )}
    </Box>
  );
}

// /admin: only for admins. The role here comes from /api/me and only decides what
// to show; every admin request is checked again by the server (403 otherwise).
export default function AdminPage() {
  const { currentUser, authReady } = useContext(UserContext);
  const navigate = useNavigate();
  const [tab, setTab] = useState('reports');
  const [pending, setPending] = useState(null);   // the action awaiting confirmation

  if (!authReady) return null;
  if (currentUser?.role !== 'admin') {
    return (
      <Box sx={{ maxWidth: 600, mx: 'auto', px: 2 }}>
        <Alert
          severity="warning"
          data-testid="admin-forbidden"
          action={!currentUser && <Button color="inherit" size="small" onClick={() => navigate('/login')}>Log in</Button>}
        >
          Admins only.
        </Alert>
      </Box>
    );
  }

  const confirmPending = async () => {
    const action = pending;
    setPending(null);
    await action.run();
  };

  return (
    <Box sx={{ maxWidth: 800, mx: 'auto', px: 2, pb: 4, textAlign: 'start' }} data-testid="admin-page">
      {/* An explicit color: index.css gives h1/h2 a near-white color in dark mode. */}
      <Typography variant="h5" component="h1" gutterBottom sx={{ color: 'text.primary' }}>Admin</Typography>
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab label="Reports" value="reports" data-testid="admin-tab-reports" />
          <Tab label="Users" value="users" data-testid="admin-tab-users" />
        </Tabs>
      </Box>
      {tab === 'reports'
        ? <ReportsTab confirm={setPending} />
        : <UsersTab confirm={setPending} me={currentUser} />}

      <Dialog open={!!pending} onClose={() => setPending(null)}>
        <DialogTitle>{pending?.title}</DialogTitle>
        <DialogContent>
          <Typography variant="body2">{pending?.text}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPending(null)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={confirmPending} data-testid="admin-confirm">
            {pending?.label}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
