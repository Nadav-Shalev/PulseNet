import { useNavigate } from 'react-router-dom';
import TableRow from '@mui/material/TableRow';
import TableCell from '@mui/material/TableCell';
import Avatar from '@mui/material/Avatar';
import Button from '@mui/material/Button';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';

export default function User({ user }) {
  const navigate = useNavigate();
  const goToProfile = () => navigate('/profile/' + encodeURIComponent(user.username));

  return (
    <TableRow>
      <TableCell>
        <Box
          onClick={goToProfile}
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            cursor: 'pointer',
            '&:hover': { '& .username-text': { textDecoration: 'underline' } },
          }}
        >
          <Avatar src={user.profile_image || user.avatar} alt={user.name} sx={{ width: 32, height: 32 }}>
            {user.name?.[0] ?? '?'}
          </Avatar>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" className="username-text" noWrap>
              {user.name || user.username}
            </Typography>
            <Typography variant="caption" color="text.secondary" noWrap display="block">
              @{user.username}
            </Typography>
          </Box>
        </Box>
      </TableCell>
      <TableCell align="center">{user.postCount}</TableCell>
      <TableCell align="center">
        <Button
          variant="contained"
          size="small"
          onClick={() => navigate('/user-posts/' + user.username)}
        >
          See Posts
        </Button>
      </TableCell>
    </TableRow>
  );
}
