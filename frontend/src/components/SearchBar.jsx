import { useState, useEffect, useRef } from 'react';
import SearchIcon from '@mui/icons-material/Search';
import InputBase from '@mui/material/InputBase';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import { styled, alpha } from '@mui/material/styles';
import Users from './Users';
import { fetchUsers } from '../api/api';

const PAGE_SIZE = 10;

const Search = styled('div')(({ theme }) => ({
  position: 'relative',
  borderRadius: theme.shape.borderRadius,
  backgroundColor: alpha(theme.palette.common.black, 0.07),
  '&:hover': { backgroundColor: alpha(theme.palette.common.black, 0.1) },
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

  // Debounced: when the search query changes, reset and fetch the first 10 from
  // the server (matches username/name/email). Brief item 7 — "fetch first 10
  // users accordingly to the search field".
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const handle = setTimeout(() => {
      fetchUsers(searchTerm.trim(), PAGE_SIZE, 0)
        .then(rows => {
          if (cancelled) return;
          const list = mapUsers(rows);
          setUsers(list);
          setOffset(list.length);
          setHasMore(list.length === PAGE_SIZE);
        })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 250);
    return () => { cancelled = true; clearTimeout(handle); };
  }, [searchTerm]);

  // Fetch and append the next 10 users (brief item 8).
  const handleLoadMore = () => {
    setLoading(true);
    fetchUsers(searchTerm.trim(), PAGE_SIZE, offset)
      .then(rows => {
        const list = mapUsers(rows);
        setUsers(prev => [...prev, ...list]);
        setOffset(prev => prev + list.length);
        setHasMore(list.length === PAGE_SIZE);
      })
      .finally(() => setLoading(false));
  };

  // Keep a ref to the latest loader so the observer never closes over a stale `offset`.
  const loadMoreRef = useRef(handleLoadMore);
  loadMoreRef.current = handleLoadMore;

  // Infinite scroll: when the sentinel scrolls into view, load the next 10 users.
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || loading || !hasMore) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) loadMoreRef.current(); },
      { rootMargin: '300px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loading, hasMore]);

  return (
    <Box sx={{ padding: 2 }}>
      <Search>
        <SearchIconWrapper>
          <SearchIcon />
        </SearchIconWrapper>
        <StyledInputBase
          placeholder="Search by username..."
          inputProps={{ 'aria-label': 'search' }}
          value={searchTerm}
          onChange={e => setSearchTerm(e.target.value)}
        />
      </Search>

      <Users users={users} />

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 3 }}>
          <CircularProgress />
        </Box>
      )}

      {/* Sentinel — when it enters the viewport, the next 10 users auto-load */}
      {hasMore && <div ref={sentinelRef} style={{ height: 20 }} />}
    </Box>
  );
}
