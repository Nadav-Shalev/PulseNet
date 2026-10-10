import { useParams } from 'react-router-dom';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Feed from '../features/feed/Feed';

export default function UserPostsPage() {
  const { username } = useParams();

  return (
    <Box>
      <Typography variant="h5" component="h1" gutterBottom>
        Posts by @{username}
      </Typography>
      <Feed username={username} />
    </Box>
  );
}
