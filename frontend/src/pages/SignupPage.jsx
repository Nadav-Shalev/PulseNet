import { useState, useContext } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import Alert from '@mui/material/Alert';
import { UserContext } from '../context/UserContext';
import { createUser } from '../api/api';

export default function SignupPage() {
  const [name, setName] = useState('');
  const [bio, setBio] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const { login } = useContext(UserContext);
  const navigate = useNavigate();

  const handleSignup = async () => {
    if (!email || !password) {
      setError('Email and password are required.');
      return;
    }
    if (password !== repeat) {
      setError('Passwords do not match');
      return;
    }
    const username = email.split('@')[0];
    const finalName = name.trim() || username;   // fall back to the email prefix
    setSubmitting(true);
    try {
      // Backend hashes the password with bcrypt, creates the user, and sets the
      // session cookie on this same response (auto-login).
      const user = await createUser(finalName, username, email, bio.trim(), password);
      login(user);
      navigate('/');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', mt: 6 }}>
      <Card sx={{ minWidth: 340, maxWidth: 420, width: '100%' }}>
        <CardContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, p: 4 }}>
          <Typography variant="h5" fontWeight={700}>Create Account</Typography>
          <Typography variant="body2" color="text.secondary">
            Sign up for a new account
          </Typography>

          {error && (
            <Alert severity="error" onClose={() => setError('')}>
              {error}
            </Alert>
          )}

          <TextField
            label="Name"
            placeholder="Your display name"
            value={name}
            onChange={e => setName(e.target.value)}
            helperText="Optional — defaults to the part before @ in your email."
            slotProps={{ htmlInput: { 'data-testid': 'signup-name' } }}
            fullWidth
          />
          <TextField
            label="Bio"
            placeholder="A short bio (optional)"
            value={bio}
            onChange={e => setBio(e.target.value)}
            slotProps={{ htmlInput: { 'data-testid': 'signup-bio' } }}
            multiline
            rows={2}
            fullWidth
          />
          <TextField
            label="Email"
            placeholder="you@example.com"
            value={email}
            onChange={e => setEmail(e.target.value)}
            slotProps={{ htmlInput: { 'data-testid': 'signup-email' } }}
            fullWidth
          />
          <TextField
            label="Password"
            type="password"
            placeholder="••••••••"
            value={password}
            onChange={e => setPassword(e.target.value)}
            slotProps={{ htmlInput: { 'data-testid': 'signup-password' } }}
            fullWidth
          />
          <TextField
            label="Repeat Password"
            type="password"
            placeholder="••••••••"
            value={repeat}
            onChange={e => setRepeat(e.target.value)}
            slotProps={{ htmlInput: { 'data-testid': 'signup-repeat-password' } }}
            fullWidth
          />
          <Button data-testid="signup-submit" variant="contained" fullWidth onClick={handleSignup} disabled={submitting}>
            {submitting ? 'Signing up...' : 'Sign Up'}
          </Button>
          <Typography variant="body2" align="center">
            Already have an account?{' '}
            <Button size="small" onClick={() => navigate('/login')}>Login</Button>
          </Typography>
        </CardContent>
      </Card>
    </Box>
  );
}
