import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Card from '@mui/material/Card';
import CardActions from '@mui/material/CardActions';
import CardContent from '@mui/material/CardContent';
import CardMedia from '@mui/material/CardMedia';
import CardHeader from '@mui/material/CardHeader';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import Avatar from '@mui/material/Avatar';
import Chip from '@mui/material/Chip';
import Box from '@mui/material/Box';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import CircularProgress from '@mui/material/CircularProgress';
import IconButton from '@mui/material/IconButton';
import CloseIcon from '@mui/icons-material/Close';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import { fetchArticleById, deleteArticle, removePostTag } from '../api/api';
import { postTimeAgo } from '../utils/timeAgo';

// `manage` enables owner-only controls (delete post, remove a hashtag). It is only
// passed when the current user views their OWN profile, so it never appears in feeds
// or on other users' profiles. onDeleted / onTagsChanged let the parent list update.
export default function SinglePost({ post, manage = false, onDeleted, onTagsChanged }) {
  const [open, setOpen] = useState(false);
  const [fullHtml, setFullHtml] = useState(null);
  const [loading, setLoading] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [tagBusy, setTagBusy] = useState(null);
  const [manageError, setManageError] = useState('');
  // Per-card toggle: the card looks normal until the owner clicks the pencil.
  const [managing, setManaging] = useState(false);
  const navigate = useNavigate();

  const handleOpen = async () => {
    setOpen(true);
    if (!fullHtml) {
      setLoading(true);
      const article = await fetchArticleById(post.id);
      setFullHtml(article.body_html);
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    setManageError('');
    try {
      await deleteArticle(post.id);
      setConfirmOpen(false);
      onDeleted?.(post.id);          // parent removes it from the list
    } catch (err) {
      setManageError(err.message || 'Could not delete post.');
      setDeleting(false);
    }
  };

  const handleRemoveTag = async (tag) => {
    setTagBusy(tag);
    setManageError('');
    try {
      const res = await removePostTag(post.id, tag);
      onTagsChanged?.(post.id, res.tag_list || []);
    } catch (err) {
      setManageError(err.message || 'Could not remove tag.');
    } finally {
      setTagBusy(null);
    }
  };

  const authorUsername = post?.user?.username;
  const authorName = post?.user?.name?.trim();
  // Show the name when present, otherwise @username (never the raw email).
  const displayName = authorName || (authorUsername ? `@${authorUsername}` : 'Unknown');
  // Secondary line: @username (only if we already showed a name) + time ago.
  const metaLine = authorName && authorUsername
    ? `@${authorUsername} · ${postTimeAgo(post)}`
    : postTimeAgo(post);
  const goToAuthor = () => {
    if (authorUsername) navigate(`/profile/${encodeURIComponent(authorUsername)}`);
  };
  const goToTag = (tag) => navigate(`/tag/${encodeURIComponent(tag)}`);

  return (
    <>
      <Card
        sx={{
          minWidth: 275,
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          ...(managing ? { outline: '2px solid', outlineColor: 'primary.main' } : {}),
        }}
      >
        {post?.cover_image && (
          <CardMedia
            component="img"
            height="160"
            image={post.cover_image}
            alt={post.title}
            sx={{ objectFit: 'cover' }}
          />
        )}
        <CardHeader
          avatar={
            <Avatar
              src={post?.user?.profile_image}
              alt={post?.user?.name}
              onClick={goToAuthor}
              sx={{ cursor: authorUsername ? 'pointer' : 'default' }}
            >
              {post?.user?.name?.[0] ?? '?'}
            </Avatar>
          }
          title={
            <Box
              component="span"
              onClick={goToAuthor}
              sx={{
                cursor: authorUsername ? 'pointer' : 'default',
                '&:hover': authorUsername ? { textDecoration: 'underline' } : undefined,
              }}
            >
              {displayName}
            </Box>
          }
          subheader={metaLine}
          action={
            manage ? (
              managing ? (
                <IconButton
                  aria-label="done managing"
                  title="Done"
                  onClick={() => { setManaging(false); setManageError(''); }}
                >
                  <CloseIcon fontSize="small" />
                </IconButton>
              ) : (
                <IconButton
                  aria-label="manage post"
                  title="Manage post"
                  onClick={() => setManaging(true)}
                >
                  <EditIcon fontSize="small" />
                </IconButton>
              )
            ) : undefined
          }
        />
        <CardContent sx={{ flexGrow: 1 }}>
          <Typography variant="h6" component="div" gutterBottom>
            {post?.title || 'Untitled'}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {post?.description || post?.content || ''}
          </Typography>
          {post?.tag_list?.length > 0 && (
            <Box sx={{ mt: 1, display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
              {post.tag_list.map(tag => (
                <Chip
                  key={tag}
                  label={`#${tag}`}
                  size="small"
                  clickable
                  onClick={() => goToTag(tag)}
                  // Owner-only, and only while managing: the X removes just this hashtag.
                  onDelete={manage && managing ? () => handleRemoveTag(tag) : undefined}
                  disabled={tagBusy === tag}
                />
              ))}
            </Box>
          )}
        </CardContent>
        {manage && managing && (
          <Typography
            variant="caption"
            color={manageError ? 'error' : 'text.secondary'}
            sx={{ px: 2 }}
          >
            {manageError || 'Managing post — remove tags with ✕, or delete the post.'}
          </Typography>
        )}
        <CardActions sx={{ justifyContent: 'center', gap: 1 }}>
          <Button variant="contained" size="small" onClick={handleOpen}>
            Read More
          </Button>
          {manage && managing && (
            <Button
              variant="outlined"
              color="error"
              size="small"
              startIcon={<DeleteIcon />}
              onClick={() => { setManageError(''); setConfirmOpen(true); }}
            >
              Delete
            </Button>
          )}
        </CardActions>
      </Card>

      {/* Owner-only delete confirmation */}
      <Dialog open={confirmOpen} onClose={() => !deleting && setConfirmOpen(false)}>
        <DialogTitle>Delete this post?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            "{post?.title || 'Untitled'}" will be permanently removed. This can't be undone.
          </Typography>
          {manageError && (
            <Typography variant="caption" color="error" sx={{ mt: 1, display: 'block' }}>
              {manageError}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)} disabled={deleting}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            onClick={handleDelete}
            disabled={deleting}
            startIcon={deleting ? <CircularProgress size={16} color="inherit" /> : null}
          >
            {deleting ? 'Deleting...' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="md" fullWidth scroll="paper">
        <DialogTitle sx={{ pr: 6 }}>
          {post?.title}
          <IconButton
            onClick={() => setOpen(false)}
            sx={{ position: 'absolute', right: 8, top: 8 }}
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>

        <DialogContent dividers>
          {loading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <Box
              sx={{
                '& img': { maxWidth: '100%', height: 'auto', display: 'block', my: 1 },
                '& pre': { overflowX: 'auto', p: 2, bgcolor: '#f5f5f5', borderRadius: 1 },
                '& code': { fontSize: '0.85em' },
                '& h1,& h2,& h3': { mt: 2, mb: 1 },
                lineHeight: 1.7,
              }}
              dangerouslySetInnerHTML={{ __html: fullHtml || '' }}
            />
          )}
        </DialogContent>

        <DialogActions>
          <Button onClick={() => setOpen(false)} variant="contained">
            Close
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
