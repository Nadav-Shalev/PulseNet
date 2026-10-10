import { useParams } from 'react-router-dom';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Feed from '../features/feed/Feed';

export default function TagPostsPage() {
  const { tagName } = useParams();

  return (
    <Box>
      <Typography variant="h5" component="h1" gutterBottom>
        Posts tagged with #{tagName}
      </Typography>
      <Feed tag={tagName} />
    </Box>
  );
}
