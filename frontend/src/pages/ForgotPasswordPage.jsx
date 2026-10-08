import { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import Alert from '@mui/material/Alert';
import Link from '@mui/material/Link';
import { requestPasswordReset } from '../api/api';

// Ask for a reset link. The answer is the same whether or not the address has an
// account, so this page never says which it was.
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    setSent('');
    if (!email.trim()) {
      setError('Enter the email of your account.');
      return;
    }
    setSubmitting(true);
    try {
      const { message } = await requestPasswordReset(email.trim());
      setSent(message);
    } catch (err) {
      setError(err.message || 'Could not send the link. Try again later.');
    } finally {
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
          <Typography variant="h5" fontWeight={700}>Forgot your password?</Typography>
          <Typography variant="body2" color="text.secondary">
            Enter the email of your account and we will send you a link to choose a new password.
          </Typography>

          {sent && <Alert severity="success" data-testid="forgot-sent">{sent}</Alert>}
          {error && (
            <Alert severity="error" onClose={() => setError('')} data-testid="forgot-error">
              {error}
            </Alert>
          )}

          <TextField
            label="Email"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={e => setEmail(e.target.value)}
            slotProps={{ htmlInput: { 'data-testid': 'forgot-email' } }}
            fullWidth
          />
          <Button type="submit" data-testid="forgot-submit" variant="contained" fullWidth disabled={submitting}>
            {submitting ? 'Sending...' : 'Send reset link'}
          </Button>
          <Link component={RouterLink} to="/login" variant="body2" sx={{ alignSelf: 'center' }}>
            Back to login
          </Link>
        </CardContent>
      </Card>
    </Box>
  );
}
