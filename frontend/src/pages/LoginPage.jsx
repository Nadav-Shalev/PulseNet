import { useState, useContext } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import Divider from '@mui/material/Divider';
import Alert from '@mui/material/Alert';
import { UserContext } from '../context/UserContext';
import { loginUser, fetchMe } from '../api/api';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [authError, setAuthError] = useState(false);
  const { login } = useContext(UserContext);
  const navigate = useNavigate();

  const handleLogin = async () => {
    setError('');
    setAuthError(false);
    if (!email || !password) {
      setError('Email and password are required.');
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
    <Box sx={{ display: 'flex', justifyContent: 'center', mt: 6 }}>
      <Card sx={{ minWidth: 340, maxWidth: 420, width: '100%' }}>
        <CardContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, p: 4 }}>
          <Typography variant="h5" fontWeight={700}>Welcome Back</Typography>
          <Typography variant="body2" color="text.secondary">
            Sign in to your account
          </Typography>

          {authError && (
            <Alert
              severity="error"
              action={
                <Button color="inherit" size="small" onClick={() => navigate('/signup')}>
                  Sign Up
                </Button>
              }
            >
              Invalid email or password.
            </Alert>
          )}
          {error && (
            <Alert severity="error" onClose={() => setError('')}>
              {error}
            </Alert>
          )}

          <TextField
            label="Email"
            placeholder="you@example.com"
            value={email}
            onChange={e => setEmail(e.target.value)}
            slotProps={{ htmlInput: { 'data-testid': 'login-email' } }}
            fullWidth
          />
          <TextField
            label="Password"
            type="password"
            placeholder="••••••••"
            value={password}
            onChange={e => setPassword(e.target.value)}
            slotProps={{ htmlInput: { 'data-testid': 'login-password' } }}
            fullWidth
          />
          <Button data-testid="login-submit" variant="contained" fullWidth onClick={handleLogin} disabled={submitting}>
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
