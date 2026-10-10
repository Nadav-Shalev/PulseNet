import { useState, useEffect, useRef, useContext } from 'react';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import { UserContext } from '../../context/UserContext';
import Grid from '@mui/material/Grid';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import Typography from '@mui/material/Typography';
import SinglePost from '../../components/SinglePost';
import {
  fetchArticles,
  fetchArticlesByUser,
  fetchArticlesByTag,
  fetchFollowingArticles,
} from '../../api/api';

// A different feed/viewer starts at page one before any request can run.
export default function Feed(props) {
  const { currentUser } = useContext(UserContext);
  return <FeedContent key={JSON.stringify([props.username, props.tag, props.feed, currentUser?.id])} {...props} />;
}

function FeedContent({ username, tag, feed, manage = false, emptyMessage = 'No posts yet.' }) {
  const [posts, setPosts] = useState([]);
  const [page, setPage] = useState(1);
  // Starts true: the infinite-scroll observer below attaches only once page 1 is
  // in. Starting false let it see the (still empty) feed's sentinel and request
  // page 2 at once, which dropped page 1 as stale and showed "No posts yet."
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(true);
  const sentinelRef = useRef(null);

  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const inFlight = useRef(true);

  // Fetch whenever page or the filter changes. Page 1 replaces; later pages append.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    inFlight.current = true;
    const loader = feed === 'following'
      ? fetchFollowingArticles(page)
      : tag
      ? fetchArticlesByTag(tag, page)
      : username
      ? fetchArticlesByUser(username, page)
      : fetchArticles(page);
    loader
      .then(data => {
        if (cancelled) return;
        if (!Array.isArray(data)) throw new Error('Could not read the posts. Please retry.');
        const list = data;
        setHasMore(list.length === 10);
        setPosts(prev => page === 1 ? list : [...prev, ...list]);
      })
      .catch(err => {
        if (!cancelled) setError(err.status === 401 ? 'Your session expired. Log in to see your following feed.' : err.message || 'Could not load posts.');
      })
      .finally(() => { if (!cancelled) { inFlight.current = false; setLoading(false); } });
    return () => { cancelled = true; };
  }, [page, username, tag, feed, retry]);

  // Infinite scroll: when the sentinel scrolls into view, load the next page.
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || loading || error || !hasMore) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !inFlight.current) {
          inFlight.current = true;
          setPage(p => p + 1);
        }
      },
      { rootMargin: '300px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loading, hasMore, error]);

  // Owner-management callbacks (`manage`) and an admin's delete keep the list in
  // sync without a full refetch.
  const handleDeleted = (id) => setPosts(prev => prev.filter(p => p.id !== id));
  const handleTagsChanged = (id, tagList) =>
    setPosts(prev => prev.map(p => (p.id === id ? { ...p, tag_list: tagList } : p)));

  return (
    <Box>
      {/* One column on phones and tablets, two from md (900px) up. */}
      <Grid container spacing={2}>
        {posts.map(post => (
          <Grid key={post.id} size={{ xs: 12, md: 6 }}>
            <SinglePost
              post={post}
              manage={manage}
              onDeleted={handleDeleted}
              onTagsChanged={handleTagsChanged}
            />
          </Grid>
        ))}
      </Grid>

      {/* Spinner while a page is loading (brief 6c) */}
      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 3 }}>
          <CircularProgress aria-label="Loading posts" />
        </Box>
      )}

      {!loading && !error && posts.length === 0 && (
        <Typography align="center" color="text.secondary" sx={{ mt: 4, mb: 2 }}>
          {emptyMessage}
        </Typography>
      )}

      {!loading && !error && !hasMore && posts.length > 0 && (
        <Typography align="center" color="text.secondary" sx={{ mt: 3, mb: 2 }}>
          No more posts
        </Typography>
      )}

      {error && (
        <Alert severity="error" sx={{ mt: 2 }} action={
          <Button color="inherit" onClick={() => setRetry(n => n + 1)} disabled={loading}>Retry</Button>
        }>{error}</Alert>
      )}

      {/* Sentinel — when it enters the viewport, the next page auto-loads */}
      {hasMore && !error && <div ref={sentinelRef} style={{ height: 20 }} />}
    </Box>
  );
}
