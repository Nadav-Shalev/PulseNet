import { useState, useEffect, useRef } from 'react';
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

export default function Feed({ username, tag, feed, manage = false, emptyMessage = 'No posts yet.' }) {
  const [posts, setPosts] = useState([]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const sentinelRef = useRef(null);

  // Reset when the filter (username, tag, or feed mode) changes
  useEffect(() => {
    setPosts([]);
    setPage(1);
    setHasMore(true);
  }, [username, tag, feed]);

  // Fetch whenever page or the filter changes. Page 1 replaces; later pages append.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
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
        const list = Array.isArray(data) ? data : [];
        if (list.length < 10) setHasMore(false);
        setPosts(prev => page === 1 ? list : [...prev, ...list]);
      })
      .catch(() => {
        // e.g. 401 on the following feed when the session has expired — stop paging.
        if (!cancelled) setHasMore(false);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [page, username, tag, feed]);

  // Infinite scroll: when the sentinel scrolls into view, load the next page.
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || loading || !hasMore) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) setPage(p => p + 1); },
      { rootMargin: '300px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loading, hasMore]);

  // Owner-management callbacks (only used when `manage` is true) keep the list in
  // sync without a full refetch.
  const handleDeleted = (id) => setPosts(prev => prev.filter(p => p.id !== id));
  const handleTagsChanged = (id, tagList) =>
    setPosts(prev => prev.map(p => (p.id === id ? { ...p, tag_list: tagList } : p)));

  return (
    <Box sx={{ px: 2 }}>
      <Grid container spacing={2}>
        {posts.map(post => (
          <Grid key={post.id} size={6}>
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
          <CircularProgress />
        </Box>
      )}

      {!loading && posts.length === 0 && (
        <Typography align="center" color="text.secondary" sx={{ mt: 4, mb: 2 }}>
          {emptyMessage}
        </Typography>
      )}

      {!hasMore && posts.length > 0 && (
        <Typography align="center" color="text.secondary" sx={{ mt: 3, mb: 2 }}>
          No more posts
        </Typography>
      )}

      {/* Sentinel — when it enters the viewport, the next page auto-loads */}
      {hasMore && <div ref={sentinelRef} style={{ height: 20 }} />}
    </Box>
  );
}
