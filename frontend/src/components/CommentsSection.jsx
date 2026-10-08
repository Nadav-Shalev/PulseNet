import { useContext, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import Avatar from '@mui/material/Avatar';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import IconButton from '@mui/material/IconButton';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined';
import SpellcheckIcon from '@mui/icons-material/Spellcheck';
import { aiCorrect, aiSuggestComment, createComment, deleteComment, fetchComments } from '../api/api';
import { UserContext } from '../context/UserContext';
import { AiSuggestion, useAiAssist } from './AiSuggestion';
import { textToHtml } from '../utils/textToHtml';
import { timeAgo } from '../utils/timeAgo';

// The backend's limit on a comment's visible text.
const MAX_COMMENT_CHARS = 2000;

// Every comment in the tree, replies included (what the card's count shows).
const countAll = (tree) => tree.reduce((n, c) => n + 1 + (c.replies?.length ?? 0), 0);

// A comment box: plain text, counted against the limit, sent as escaped HTML. Its
// AI buttons propose a comment on the post (or a reply to `parentId`) and fix the
// grammar of what is typed; either way the result waits as a suggestion to apply.
function CommentForm({ value, onChange, onSubmit, onCancel, busy, label, placeholder, testid, postId, parentId = null }) {
  const ai = useAiAssist();
  const working = busy || ai.busy;
  const fill = (text) => onChange(text.slice(0, MAX_COMMENT_CHARS));
  return (
    <Box component="form" onSubmit={onSubmit} sx={{ mt: 1 }}>
      <TextField
        fullWidth
        multiline
        minRows={2}
        size="small"
        placeholder={placeholder}
        value={value}
        onChange={e => onChange(e.target.value)}
        disabled={working}
        helperText={`${value.length}/${MAX_COMMENT_CHARS}`}
        slotProps={{ htmlInput: { maxLength: MAX_COMMENT_CHARS, 'data-testid': `${testid}-input` } }}
      />
      <AiSuggestion assist={ai} />
      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 1 }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mr: 'auto' }}>
          <Button
            size="small"
            startIcon={<AutoAwesomeIcon />}
            onClick={() => ai.run(() => aiSuggestComment(postId, parentId), { onApply: fill })}
            disabled={working}
            data-testid={`${testid}-ai-suggest`}
          >
            Suggest
          </Button>
          <Button
            size="small"
            startIcon={<SpellcheckIcon />}
            onClick={() => ai.run(() => aiCorrect(value.trim(), 'text'), { onApply: fill })}
            disabled={working || !value.trim()}
            data-testid={`${testid}-ai-correct`}
          >
            Fix grammar
          </Button>
        </Box>
        {/* On a phone this group wraps under the AI buttons, still on the right. */}
        <Box sx={{ display: 'flex', gap: 1, ml: 'auto' }}>
          {onCancel && <Button size="small" onClick={onCancel} disabled={busy}>Cancel</Button>}
          <Button
            type="submit"
            size="small"
            variant="contained"
            disabled={working || !value.trim()}
            data-testid={`${testid}-submit`}
          >
            {label}
          </Button>
        </Box>
      </Box>
    </Box>
  );
}

// The thread under a post in its Read More dialog. The dialog mounts it each time
// it opens, and it reloads after every comment or delete, so it always shows the
// server's thread; onCountChange keeps the card's comment count in step.
export default function CommentsSection({ postId, onCountChange }) {
  const { currentUser, authReady } = useContext(UserContext);
  const navigate = useNavigate();
  const [comments, setComments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [text, setText] = useState('');
  const [replyTo, setReplyTo] = useState(null);       // id of the comment being replied to
  const [replyText, setReplyText] = useState('');
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [toDelete, setToDelete] = useState(null);     // the comment awaiting confirmation

  useEffect(() => {
    let cancelled = false;                 // the dialog closed before the reply came
    fetchComments(postId)
      .then(tree => {
        if (cancelled) return;
        setComments(tree);
        onCountChange?.(countAll(tree));
      })
      // A failed load is an error, never "No comments yet": the post may have some.
      .catch(err => { if (!cancelled) setLoadError(err.message || 'Could not load comments.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [postId, onCountChange]);

  const reload = async () => {
    try {
      const tree = await fetchComments(postId);
      setComments(tree);
      onCountChange?.(countAll(tree));
    } catch (err) {
      setLoadError(err.message || 'Could not load comments.');
    }
  };

  // Shared by the comment and reply boxes. Resolves to true when it was posted.
  const post = async (body, parentId) => {
    setBusy(true);
    setActionError('');
    try {
      await createComment(postId, textToHtml(body.trim()), parentId);
      await reload();
      return true;
    } catch (err) {
      if (err.status === 401) navigate('/login');      // the session has expired
      else setActionError(err.message || 'Could not post your comment.');
      return false;
    } finally {
      setBusy(false);
    }
  };

  const handleComment = async (e) => {
    e.preventDefault();
    if (await post(text, null)) setText('');
  };

  const handleReply = async (e) => {
    e.preventDefault();
    if (await post(replyText, replyTo)) {
      setReplyTo(null);
      setReplyText('');
    }
  };

  const handleDelete = async () => {
    setBusy(true);
    setActionError('');
    try {
      await deleteComment(toDelete.id);
      await reload();
    } catch (err) {
      if (err.status === 401) navigate('/login');
      else setActionError(err.message || 'Could not delete the comment.');
    } finally {
      setToDelete(null);
      setBusy(false);
    }
  };

  const startReply = (commentId) => {
    setReplyTo(commentId);
    setReplyText('');
    setActionError('');
  };

  const renderComment = (c, isReply) => {
    const username = c.user?.username;
    const mine = !!currentUser && currentUser.username === username;
    return (
      <Box data-testid="comment" sx={{ display: 'flex', gap: 1, mt: 1.5 }}>
        <Avatar
          src={c.user?.profile_image}
          alt={c.user?.name}
          onClick={() => username && navigate(`/profile/${encodeURIComponent(username)}`)}
          sx={{ width: 32, height: 32, cursor: username ? 'pointer' : 'default' }}
        >
          {c.user?.name?.[0] ?? '?'}
        </Avatar>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {/* The delete button keeps its own column, so a wrapped name line on a phone
              does not push it onto a line of its own. */}
          <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
            <Box sx={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'baseline', flexWrap: 'wrap', columnGap: 1 }}>
              <Typography variant="subtitle2" component="span">
                {c.user?.name?.trim() || `@${username}`}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                @{username} · {timeAgo(c.created_at)}
              </Typography>
            </Box>
            {mine && (
              <IconButton
                size="small"
                aria-label="Delete comment"
                title="Delete"
                onClick={() => setToDelete(c)}
                disabled={busy}
                data-testid="comment-delete"
                sx={{ mt: -0.5 }}
              >
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            )}
          </Box>
          {/* body_html is sanitized by the backend, like a post body. */}
          <Typography
            component="div"
            variant="body2"
            data-testid="comment-body"
            sx={{ overflowWrap: 'anywhere', '& p': { m: 0 }, '& pre': { overflowX: 'auto' } }}
            dangerouslySetInnerHTML={{ __html: c.body_html }}
          />
          {/* Replies are one level deep, so only a top-level comment can be answered. */}
          {!isReply && currentUser && replyTo !== c.id && (
            <Button size="small" onClick={() => startReply(c.id)} disabled={busy} data-testid="reply-button" sx={{ minWidth: 0, px: 0.5 }}>
              Reply
            </Button>
          )}
        </Box>
      </Box>
    );
  };

  let thread;
  if (loading) {
    thread = (
      <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
        Loading comments...
      </Typography>
    );
  } else if (loadError) {
    thread = <Alert severity="error" data-testid="comments-error">{loadError}</Alert>;
  } else if (comments.length === 0) {
    thread = (
      <Typography variant="body2" color="text.secondary" data-testid="comments-empty" sx={{ py: 1 }}>
        No comments yet.
      </Typography>
    );
  } else {
    thread = comments.map(c => (
      <Box key={c.id}>
        {renderComment(c, false)}
        <Box data-testid="comment-replies" sx={{ pl: 5 }}>
          {c.replies.map(r => <Box key={r.id}>{renderComment(r, true)}</Box>)}
          {replyTo === c.id && (
            <CommentForm
              value={replyText}
              onChange={setReplyText}
              onSubmit={handleReply}
              onCancel={() => setReplyTo(null)}
              busy={busy}
              label="Reply"
              placeholder={`Reply to @${c.user?.username}...`}
              testid="reply"
              postId={postId}
              parentId={c.id}
            />
          )}
        </Box>
      </Box>
    ));
  }

  // Nothing to write on until the thread has loaded, and until /api/me has
  // answered, so a logged-in reader is never shown the log-in button.
  let form = null;
  if (!loading && !loadError && authReady) {
    form = currentUser ? (
      <CommentForm
        value={text}
        onChange={setText}
        onSubmit={handleComment}
        busy={busy}
        label="Comment"
        placeholder="Write a comment..."
        testid="comment"
        postId={postId}
      />
    ) : (
      <Button size="small" variant="outlined" onClick={() => navigate('/login')} data-testid="comment-login" sx={{ mt: 1 }}>
        Log in to comment
      </Button>
    );
  }

  return (
    <Box data-testid="comments-section">
      <Typography variant="h6" component="h3">
        Comments{!loading && !loadError ? ` (${countAll(comments)})` : ''}
      </Typography>
      {form}
      {actionError && (
        <Typography variant="caption" color="error" data-testid="comment-error" sx={{ display: 'block', mt: 1 }}>
          {actionError}
        </Typography>
      )}
      {thread}

      <Dialog open={!!toDelete} onClose={() => !busy && setToDelete(null)}>
        <DialogTitle>Delete this comment?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            {toDelete?.replies?.length ? 'Its replies will be deleted too. ' : ''}
            This can&apos;t be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setToDelete(null)} disabled={busy}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            onClick={handleDelete}
            disabled={busy}
            data-testid="comment-delete-confirm"
          >
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
