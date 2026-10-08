import { useState } from 'react';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import FormControlLabel from '@mui/material/FormControlLabel';
import Radio from '@mui/material/Radio';
import RadioGroup from '@mui/material/RadioGroup';
import TextField from '@mui/material/TextField';
import { REPORT_REASONS, reportContent } from '../api/api';

// The backend's limit on the reporter's note.
const MAX_DETAILS = 500;

// Report a post or a comment to the admins: `target` is { postId } or { commentId },
// and null keeps the dialog closed. The parent mounts it per target (key), so each
// report starts from an empty form. A 401 goes to onUnauthorized (the session expired).
export default function ReportDialog({ target, kind, onClose, onUnauthorized }) {
  const [reason, setReason] = useState('');
  const [details, setDetails] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(null);     // the server's reply once it is sent

  const handleSubmit = async () => {
    setBusy(true);
    setError('');
    try {
      setDone(await reportContent(target, reason, details.trim()));
    } catch (err) {
      if (err.status === 401) onUnauthorized?.();
      else setError(err.message || 'Could not send the report.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={!!target} onClose={() => !busy && onClose()} fullWidth maxWidth="xs" data-testid="report-dialog">
      {/* An explicit color: index.css gives h2 a near-white color in dark mode. */}
      <DialogTitle sx={{ color: 'text.primary' }}>Report this {kind}</DialogTitle>
      <DialogContent>
        {done ? (
          <Alert severity="success" data-testid="report-done">
            {done.already
              ? `You have already reported this ${kind}. The admins will look at it.`
              : 'Thanks. The admins will look at it.'}
          </Alert>
        ) : (
          <>
            <RadioGroup value={reason} onChange={e => setReason(e.target.value)}>
              {REPORT_REASONS.map(r => (
                <FormControlLabel
                  key={r.value}
                  value={r.value}
                  control={<Radio size="small" />}
                  label={r.label}
                  disabled={busy}
                  data-testid={`report-reason-${r.value}`}
                />
              ))}
            </RadioGroup>
            <TextField
              fullWidth
              multiline
              minRows={2}
              size="small"
              placeholder="Anything the admins should know? (optional)"
              value={details}
              onChange={e => setDetails(e.target.value)}
              disabled={busy}
              helperText={`${details.length}/${MAX_DETAILS}`}
              slotProps={{ htmlInput: { maxLength: MAX_DETAILS, 'data-testid': 'report-details' } }}
              sx={{ mt: 1 }}
            />
            {error && <Alert severity="error" sx={{ mt: 1 }} data-testid="report-error">{error}</Alert>}
          </>
        )}
      </DialogContent>
      <DialogActions>
        {done ? (
          <Button onClick={onClose} variant="contained" data-testid="report-close">Close</Button>
        ) : (
          <>
            <Button onClick={onClose} disabled={busy}>Cancel</Button>
            <Button
              onClick={handleSubmit}
              variant="contained"
              color="error"
              disabled={busy || !reason}
              data-testid="report-submit"
            >
              Report
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
