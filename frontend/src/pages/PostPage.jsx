import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Typography from '@mui/material/Typography';
import { fetchArticleById } from '../api/api';
import SinglePost from '../components/SinglePost';

// /post/:postId: one post, as the feed shows it. SinglePost does the rest exactly as
// in a feed: Read More, the like, the comments dialog, report, and delete for its
// author or an admin (which then leaves for the home page).
export default function PostPage() {
  const { postId } = useParams();
  const navigate = useNavigate();
  const valid = /^\d+$/.test(postId ?? '');
  const [post, setPost] = useState(null);
  const [loading, setLoading] = useState(valid);
  const [error, setError] = useState(null);   // { notFound, message }
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const request = ++requestId.current;
    setLoading(true);
    setError(null);
    setPost(null);
    try {
      const article = await fetchArticleById(postId);
      if (request === requestId.current) setPost(article);
    } catch (err) {
      if (request === requestId.current) {
        setError({ notFound: err.status === 404, message: err.message || 'Could not load the post.' });
      }
    } finally {
      if (request === requestId.current) setLoading(false);
    }
  }, [postId]);

  useEffect(() => {
    if (!valid) return undefined;
    load();
    // A newer id (or leaving the page) makes this request's answer stale.
    const request = requestId.current;
    return () => { requestId.current = request + 1; };
  }, [load, valid]);

  let content;
  if (!valid || error?.notFound) {
    content = (
      <Alert severity="info" data-testid="post-page-not-found">
        This post does not exist or was deleted.
      </Alert>
    );
  } else if (loading) {
    content = (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress aria-label="Loading post" />
      </Box>
    );
  } else if (error) {
    content = (
      <Alert
        severity="error"
        data-testid="post-page-error"
        action={<Button color="inherit" onClick={load}>Retry</Button>}
      >
        {error.message}
      </Alert>
    );
  } else if (post) {
    content = <SinglePost key={post.id} post={post} onDeleted={() => navigate('/')} />;
  }

  return (
    <Box sx={{ maxWidth: 800, mx: 'auto', textAlign: 'start' }} data-testid="post-page">
      {/* An explicit color: index.css gives h1/h2 a near-white color in dark mode. */}
      <Typography variant="h5" component="h1" gutterBottom sx={{ color: 'text.primary' }}>
        {post?.user?.username ? `Post by @${post.user.username}` : 'Post'}
      </Typography>
      {content}
    </Box>
  );
}
