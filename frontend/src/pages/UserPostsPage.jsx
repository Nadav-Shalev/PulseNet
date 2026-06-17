import { useParams } from 'react-router-dom';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Feed from '../features/feed/Feed';

export default function UserPostsPage() {
  const { username } = useParams();

  return (
    <Box sx={{ padding: 2 }}>
      <Typography variant="h5" gutterBottom>
        Posts by @{username}
      </Typography>
      <Feed username={username} />
    </Box>
  );
}
