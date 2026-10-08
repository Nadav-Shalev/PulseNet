import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';

const IDLE = { busy: false, error: '', suggestion: null };

// One AI request at a time for a form: `run` sends it and keeps what came back as
// a suggestion (never written into the form until the user applies it), or the
// error to show. A 401 means the session has expired, so it goes to the login page.
//   const ai = useAiAssist();
//   ai.run(() => aiCorrect(text), { onApply: setText });
//   <AiSuggestion assist={ai} />
export function useAiAssist() {
  const navigate = useNavigate();
  const [state, setState] = useState(IDLE);

  const run = async (request, { html = false, onApply }) => {
    setState({ busy: true, error: '', suggestion: null });
    try {
      const content = await request();
      setState({ busy: false, error: '', suggestion: { content, html, onApply } });
    } catch (err) {
      if (err.status === 401) {
        navigate('/login');
        return;
      }
      setState({ busy: false, error: err.message || 'AI assistance failed.', suggestion: null });
    }
  };

  const clear = () => setState(IDLE);

  return { ...state, run, clear };
}

// What the AI came back with, to apply or dismiss; or the wait; or why it failed.
export function AiSuggestion({ assist }) {
  const { busy, error, suggestion, clear } = assist;

  if (busy) {
    return (
      <Box data-testid="ai-busy" sx={{ display: 'flex', alignItems: 'center', gap: 1, my: 1, color: 'text.secondary' }}>
        <CircularProgress size={16} />
        <Typography variant="body2">Asking the AI...</Typography>
      </Box>
    );
  }
  if (error) {
    return (
      <Alert severity="warning" onClose={clear} data-testid="ai-error" sx={{ my: 1 }}>
        {error}
      </Alert>
    );
  }
  if (!suggestion) return null;

  const apply = () => {
    suggestion.onApply(suggestion.content);
    clear();
  };

  return (
    <Paper variant="outlined" data-testid="ai-suggestion" sx={{ p: 1.5, my: 1, bgcolor: 'action.hover', textAlign: 'start' }}>
      <Typography variant="overline" color="text.secondary" sx={{ lineHeight: 1.5 }}>
        AI suggestion
      </Typography>
      {/* HTML suggestions are sanitized by the backend, like a post body. */}
      {suggestion.html ? (
        <Box
          data-testid="ai-suggestion-body"
          sx={{ overflowWrap: 'anywhere', '& p': { mt: 0 }, '& pre': { overflowX: 'auto' } }}
          dangerouslySetInnerHTML={{ __html: suggestion.content }}
        />
      ) : (
        <Typography data-testid="ai-suggestion-body" variant="body2" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          {suggestion.content}
        </Typography>
      )}
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1, mt: 1 }}>
        <Button size="small" onClick={clear} data-testid="ai-dismiss">Dismiss</Button>
        <Button size="small" variant="contained" onClick={apply} data-testid="ai-apply">Apply</Button>
      </Box>
    </Paper>
  );
}
