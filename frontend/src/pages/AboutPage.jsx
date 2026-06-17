import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Divider from '@mui/material/Divider';
import Chip from '@mui/material/Chip';

const features = [
  { emoji: '🔐', title: 'Authentication', desc: 'Sign up, log in, and log out. Passwords are hashed with bcrypt and your session is kept with a secure HttpOnly cookie.' },
  { emoji: '🧑', title: 'Profiles', desc: 'Each user has a profile with their name, bio, profile picture, and their own posts. Edit your profile any time.' },
  { emoji: '🤝', title: 'Follow / Unfollow', desc: 'Follow other users and see live followers / following counts. Open your following list to jump to anyone you follow.' },
  { emoji: '📰', title: 'Two Feeds', desc: 'A Global feed with posts from everyone, and a Following feed with posts only from the people you follow.' },
  { emoji: '♾️', title: 'Infinite Scroll', desc: 'Feeds and the user list load more as you scroll — no manual paging.' },
  { emoji: '🔍', title: 'User Search', desc: 'Find people by username and jump straight to their profile.' },
  { emoji: '✍️', title: 'Rich Text Posts', desc: 'Write posts in a WYSIWYG editor with bold, italics, links, and lists, and attach an uploaded image.' },
  { emoji: '🛠️', title: 'Manage Your Posts', desc: 'On your own profile you can delete a post or remove a hashtag from it.' },
];

const stack = ['React 19', 'React Router 7', 'Material UI 9', 'Vite', 'Flask', 'MySQL'];

export default function AboutPage() {
  return (
    <Box sx={{ maxWidth: 760, mx: 'auto', px: 3, py: 5 }}>
      <Typography variant="h3" fontWeight={800} gutterBottom>
        PulseNet
      </Typography>
      <Typography variant="h6" color="text.secondary" gutterBottom>
        A social feed where developers share posts and follow each other.
      </Typography>

      <Divider sx={{ my: 3 }} />

      <Typography variant="body1" sx={{ mb: 4, lineHeight: 1.8 }}>
        PulseNet is a full-stack social network: create an account, build your profile,
        follow other users, and share rich-text posts with images. Browse everything in
        the global feed, or narrow it to just the people you follow. All accounts, posts,
        follows, and tags are stored in a relational database.
      </Typography>

      <Typography variant="h5" fontWeight={700} gutterBottom>
        What you can do
      </Typography>

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2, mb: 4 }}>
        {features.map(f => (
          <Card key={f.title} variant="outlined">
            <CardContent>
              <Typography variant="h6">{f.emoji} {f.title}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {f.desc}
              </Typography>
            </CardContent>
          </Card>
        ))}
      </Box>

      <Divider sx={{ my: 3 }} />

      <Typography variant="h5" fontWeight={700} gutterBottom>
        Built with
      </Typography>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        {stack.map(s => <Chip key={s} label={s} />)}
      </Box>

      <Divider sx={{ my: 3 }} />

      <Typography variant="body2" color="text.secondary">
        A React + Vite single-page app talking to a Flask + MySQL REST API, with
        bcrypt password hashing and server-side sessions.
      </Typography>
    </Box>
  );
}
