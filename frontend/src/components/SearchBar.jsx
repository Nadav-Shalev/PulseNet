import { useState, useEffect, useRef } from 'react';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import SearchIcon from '@mui/icons-material/Search';
import InputBase from '@mui/material/InputBase';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import { styled } from '@mui/material/styles';
import Users from './Users';
import { fetchUsers } from '../api/api';

const PAGE_SIZE = 10;

const Search = styled('div')(({ theme }) => ({
  position: 'relative',
  borderRadius: theme.shape.borderRadius,
  backgroundColor: theme.palette.action.hover,
  '&:hover': { backgroundColor: theme.palette.action.selected },
  width: '100%',
  maxWidth: 400,
  margin: '0 auto',
}));

const SearchIconWrapper = styled('div')(({ theme }) => ({
  padding: theme.spacing(0, 2),
  height: '100%',
  position: 'absolute',
  pointerEvents: 'none',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
}));

const StyledInputBase = styled(InputBase)(({ theme }) => ({
  color: 'inherit',
  width: '100%',
  '& .MuiInputBase-input': {
    padding: theme.spacing(1, 1, 1, 0),
    paddingLeft: `calc(1em + ${theme.spacing(4)})`,
  },
}));

// Normalize the backend's `post_count` → `postCount` (User.jsx reads postCount).
const mapUsers = (rows) =>
  (Array.isArray(rows) ? rows : []).map(u => ({ ...u, postCount: u.post_count ?? 0 }));

export default function SearchBar() {
  const [searchTerm, setSearchTerm] = useState('');
  const [users, setUsers] = useState([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(true);
  const sentinelRef = useRef(null);
  const generation = useRef(0);
  const inFlight = useRef(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);

  // Debounced: when the search query changes, reset and fetch the first 10 from
  // the server (matches username/name). Brief item 7 — "fetch first 10
  // users accordingly to the search field".
  useEffect(() => {
    const request = ++generation.current;
    inFlight.current = true;
    setLoading(true);
    setError('');
    setUsers([]);
    setOffset(0);
    setHasMore(true);
    const handle = setTimeout(() => {
      fetchUsers(searchTerm.trim(), PAGE_SIZE, 0)
        .then(rows => {
          if (request !== generation.current) return;
          const list = mapUsers(rows);
          setUsers(list);
          setOffset(list.length);
          setHasMore(list.length === PAGE_SIZE);
        })
        .catch(err => { if (request === generation.current) setError(err.message || 'Could not load users.'); })
        .finally(() => { if (request === generation.current) { inFlight.current = false; setLoading(false); } });
    }, 250);
    return () => { generation.current = request + 1; clearTimeout(handle); };
  }, [searchTerm, retry]);

  // Fetch and append the next 10 users (brief item 8).
  const handleLoadMore = () => {
    if (inFlight.current) return;
    const request = generation.current;
    inFlight.current = true;
    setLoading(true);
    setError('');
    fetchUsers(searchTerm.trim(), PAGE_SIZE, offset)
      .then(rows => {
        if (request !== generation.current) return;
        const list = mapUsers(rows);
        setUsers(prev => [...prev, ...list]);
        setOffset(prev => prev + list.length);
        setHasMore(list.length === PAGE_SIZE);
      })
      .catch(err => { if (request === generation.current) setError(err.message || 'Could not load more users.'); })
      .finally(() => { if (request === generation.current) { inFlight.current = false; setLoading(false); } });
  };

  // Keep a ref to the latest loader so the observer never closes over a stale `offset`.
  const loadMoreRef = useRef(handleLoadMore);
  loadMoreRef.current = handleLoadMore;

  // Infinite scroll: when the sentinel scrolls into view, load the next 10 users.
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || loading || error || !hasMore) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) loadMoreRef.current(); },
      { rootMargin: '300px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loading, hasMore, error]);

  return (
    <Box>
      <Typography variant="h5" component="h1" gutterBottom>Discover people</Typography>
      <Search>
        <SearchIconWrapper>
          <SearchIcon />
        </SearchIconWrapper>
        <StyledInputBase
          placeholder="Search by username..."
          slotProps={{ input: { 'aria-label': 'Search users by username or name' } }}
          value={searchTerm}
          onChange={e => { generation.current++; inFlight.current = true; setSearchTerm(e.target.value); }}
        />
      </Search>

      <Users users={users} />

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 3 }}>
          <CircularProgress aria-label="Loading users" />
        </Box>
      )}

      {!loading && !error && users.length === 0 && (
        <Typography color="text.secondary" role="status" sx={{ py: 3 }}>No users found. Try another name.</Typography>
      )}
      {error && <Alert severity="error" sx={{ mt: 2 }} action={
        <Button color="inherit" disabled={loading} onClick={() => users.length ? handleLoadMore() : setRetry(n => n + 1)}>Retry</Button>
      }>{error}</Alert>}
      {/* Sentinel — when it enters the viewport, the next 10 users auto-load */}
      {hasMore && !error && <div ref={sentinelRef} style={{ height: 20 }} />}
    </Box>
  );
}
