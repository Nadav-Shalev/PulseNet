import { useState, useContext } from 'react';
import { Link as RouterLink, useLocation, useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import Divider from '@mui/material/Divider';
import Alert from '@mui/material/Alert';
import Link from '@mui/material/Link';
import { UserContext } from '../context/UserContext';
import { loginUser, fetchMe } from '../api/api';

// Only the address's shape, checked before asking the server. Whether an account
// exists is never told: every wrong email or password gets the same 401 message.
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [emailError, setEmailError] = useState('');
  const [authError, setAuthError] = useState(false);
  const { login } = useContext(UserContext);
  const navigate = useNavigate();
  // Set by the reset page after a new password was saved.
  const passwordReset = Boolean(useLocation().state?.passwordReset);

  const handleLogin = async (event) => {
    event.preventDefault();
    if (submitting) return;
    setError('');
    setEmailError('');
    setAuthError(false);
    if (!email || !password) {
      setError('Email and password are required.');
      return;
    }
    if (!EMAIL_SHAPE.test(email.trim())) {
      setEmailError('Enter a valid email address, like you@example.com.');
      return;
    }
    setSubmitting(true);
    try {
      await loginUser(email.trim(), password);
      // Backend has set the cookie; ask /api/me for the canonical user shape.
      const me = await fetchMe();
      if (me) login(me);
      navigate('/');
    } catch (err) {
      if (err.status === 401) {
        setAuthError(true);
      } else {
        setError(err.message || 'Login failed.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', mt: { xs: 0, sm: 3 } }}>
      <Card sx={{ maxWidth: 420, width: '100%' }}>
        <CardContent component="form" noValidate onSubmit={handleLogin} sx={{ display: 'flex', flexDirection: 'column', gap: 2, p: { xs: 2.5, sm: 4 } }}>
          <Typography variant="h5" component="h1" fontWeight={700}>Welcome Back</Typography>
          <Typography variant="body2" color="text.secondary">
            Sign in to your account
          </Typography>

          {passwordReset && (
            <Alert severity="success" data-testid="login-reset-done">
              Your password was changed. Log in with the new one.
            </Alert>
          )}
          {authError && (
            // The same words for an unknown email and a wrong password (no account
            // enumeration). The reset page gets the address the user typed.
            <Alert
              severity="error"
              data-testid="login-auth-error"
              action={
                <Button color="inherit" size="small" component={RouterLink} to="/forgot-password"
                  state={{ email: email.trim() }} data-testid="login-auth-reset" sx={{ whiteSpace: 'nowrap' }}>
                  Reset password
                </Button>
              }
            >
              Invalid email or password. Check your details or reset your password.
            </Alert>
          )}
          {error && (
            // e.g. a banned account's 403: "This account has been suspended"
            <Alert severity="error" onClose={() => setError('')} data-testid="login-error">
              {error}
            </Alert>
          )}

          <TextField
            label="Email"
            type="email"
            autoComplete="username"
            required
            disabled={submitting}
            placeholder="you@example.com"
            value={email}
            onChange={e => { setEmail(e.target.value); setEmailError(''); }}
            error={Boolean(emailError)}
            helperText={emailError || undefined}
            slotProps={{
              htmlInput: { 'data-testid': 'login-email' },
              formHelperText: { 'data-testid': 'login-email-error' },
            }}
            fullWidth
          />
          <TextField
            label="Password"
            autoComplete="current-password"
            required
            disabled={submitting}
            type="password"
            placeholder="••••••••"
            value={password}
            onChange={e => setPassword(e.target.value)}
            slotProps={{ htmlInput: { 'data-testid': 'login-password' } }}
            fullWidth
          />
          <Link component={RouterLink} to="/forgot-password" variant="body2" data-testid="login-forgot"
            sx={{ alignSelf: 'flex-end', mt: -1 }}>
            Forgot password?
          </Link>
          <Button data-testid="login-submit" variant="contained" fullWidth type="submit" disabled={submitting}>
            {submitting ? 'Logging in...' : 'Login'}
          </Button>
          <Divider>OR</Divider>
          <Button variant="outlined" fullWidth onClick={() => navigate('/signup')}>
            Sign Up
          </Button>
        </CardContent>
      </Card>
    </Box>
  );
}
