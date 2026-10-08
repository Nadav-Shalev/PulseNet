import { useContext, useEffect, useState } from 'react';
import { Link as RouterLink, useLocation, useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import Alert from '@mui/material/Alert';
import Link from '@mui/material/Link';
import { UserContext } from '../context/UserContext';
import { fetchMe, resetPassword } from '../api/api';

// The page the emailed link opens: /reset-password#token=...
// The token is in the fragment, which the browser never sends to a server. It is
// read once, then removed from the address bar so it does not stay in the history.
export default function ResetPasswordPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { login, logout } = useContext(UserContext);
  const [token] = useState(() => new URLSearchParams(location.hash.slice(1)).get('token') || '');
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(token ? '' : 'This link is incomplete. Request a new one.');

  useEffect(() => {
    if (location.hash) {
      navigate({ pathname: location.pathname, search: location.search }, { replace: true });
    }
  }, [location.hash, location.pathname, location.search, navigate]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    if (!password) {
      setError('Choose a new password.');
      return;
    }
    if (password !== repeat) {
      setError('Passwords do not match');
      return;
    }
    setSubmitting(true);
    try {
      await resetPassword(token, password);
      // The reset ended every session of the account: if this browser was logged
      // in as it, it no longer is.
      const me = await fetchMe().catch(() => null);
      if (me) login(me); else logout();
      navigate('/login', { replace: true, state: { passwordReset: true } });
    } catch (err) {
      setError(err.message || 'Could not change the password. Try again.');
      setSubmitting(false);
    }
  };

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', mt: { xs: 3, sm: 6 }, px: 2 }}>
      <Card sx={{ maxWidth: 420, width: '100%' }}>
        <CardContent
          component="form"
          noValidate
          onSubmit={handleSubmit}
          sx={{ display: 'flex', flexDirection: 'column', gap: 2, p: { xs: 2.5, sm: 4 } }}
        >
          <Typography variant="h5" fontWeight={700}>Choose a new password</Typography>
          <Typography variant="body2" color="text.secondary">
            You will be logged out everywhere, then log in with the new password.
          </Typography>

          {error && <Alert severity="error" data-testid="reset-error">{error}</Alert>}

          {token && (
            <>
              <TextField
                label="New password"
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                slotProps={{ htmlInput: { 'data-testid': 'reset-password' } }}
                fullWidth
              />
              <TextField
                label="Repeat new password"
                type="password"
                value={repeat}
                onChange={e => setRepeat(e.target.value)}
                slotProps={{ htmlInput: { 'data-testid': 'reset-repeat-password' } }}
                fullWidth
              />
              <Button type="submit" data-testid="reset-submit" variant="contained" fullWidth disabled={submitting}>
                {submitting ? 'Saving...' : 'Change password'}
              </Button>
            </>
          )}
          <Link component={RouterLink} to="/forgot-password" variant="body2" sx={{ alignSelf: 'center' }}
            data-testid="reset-new-link">
            Request a new link
          </Link>
        </CardContent>
      </Card>
    </Box>
  );
}
