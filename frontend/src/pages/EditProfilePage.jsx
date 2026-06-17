import { useState, useContext, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import Alert from '@mui/material/Alert';
import Avatar from '@mui/material/Avatar';
import CircularProgress from '@mui/material/CircularProgress';
import { UserContext } from '../context/UserContext';
import { updateMe, uploadImage } from '../api/api';

export default function EditProfilePage() {
  const { currentUser, authReady, login } = useContext(UserContext);
  const navigate = useNavigate();

  const [name, setName] = useState('');
  const [bio, setBio] = useState('');
  const [profileImage, setProfileImage] = useState('');
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);

  // Redirect to login once auth state is known and there's no user.
  useEffect(() => {
    if (authReady && !currentUser) navigate('/login');
  }, [authReady, currentUser]);

  // Pre-fill the form from the current user.
  useEffect(() => {
    if (currentUser) {
      setName(currentUser.name || '');
      setBio(currentUser.bio || '');
      setProfileImage(currentUser.profile_image || currentUser.avatar || '');
    }
  }, [currentUser]);

  const handleFileSelect = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setError('');
    setUploading(true);
    try {
      const { url } = await uploadImage(file);
      setProfileImage(url);
    } catch (err) {
      setError(err.message || 'Image upload failed.');
    } finally {
      setUploading(false);
    }
  };

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Name cannot be empty.');
      return;
    }
    setError('');
    setSaving(true);
    try {
      const updated = await updateMe({
        name: name.trim(),
        bio: bio.trim(),
        profile_image: profileImage.trim(),
      });
      login(updated);              // refresh context so the app sees new values
      setSuccess(true);
    } catch (err) {
      setError(err.message || 'Could not save profile.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', mt: 6, px: 2 }}>
      <Card sx={{ width: '100%', maxWidth: 520 }}>
        <CardContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, p: 4 }}>
          <Typography variant="h5" fontWeight={700}>Edit Profile</Typography>

          {success && (
            <Alert
              severity="success"
              action={
                <Button
                  color="inherit"
                  size="small"
                  onClick={() => navigate(`/profile/${currentUser.username}`)}
                >
                  View Profile
                </Button>
              }
            >
              Profile updated.
            </Alert>
          )}
          {error && (
            <Alert severity="error" onClose={() => setError('')}>{error}</Alert>
          )}

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Avatar src={profileImage} sx={{ width: 64, height: 64 }}>
              {name?.[0] ?? '?'}
            </Avatar>
            <Button
              variant="outlined"
              component="label"
              disabled={uploading}
              startIcon={uploading ? <CircularProgress size={16} /> : null}
            >
              {uploading ? 'Uploading...' : 'Upload Picture'}
              <input type="file" accept="image/*" hidden onChange={handleFileSelect} />
            </Button>
          </Box>

          <TextField
            label="Name"
            value={name}
            onChange={e => setName(e.target.value)}
            fullWidth
          />
          <TextField
            label="Bio"
            value={bio}
            onChange={e => setBio(e.target.value)}
            multiline
            rows={3}
            fullWidth
          />
          <TextField
            label="Profile Picture URL"
            placeholder="https://… — or use Upload Picture above"
            value={profileImage}
            onChange={e => setProfileImage(e.target.value)}
            fullWidth
          />

          <Button variant="contained" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save Changes'}
          </Button>
        </CardContent>
      </Card>
    </Box>
  );
}
