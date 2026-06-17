import { useState, useContext, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import Alert from '@mui/material/Alert';
import CircularProgress from '@mui/material/CircularProgress';
import Autocomplete from '@mui/material/Autocomplete';
import Chip from '@mui/material/Chip';
import ReactQuill from 'react-quill-new';
import 'react-quill-new/dist/quill.snow.css';
import { UserContext } from '../context/UserContext';
import { createArticle, searchTags, uploadImage } from '../api/api';

// WYSIWYG toolbar — covers the required bold / italic / hyperlink plus a few extras.
const QUILL_MODULES = {
  toolbar: [
    ['bold', 'italic', 'underline'],
    ['link'],
    [{ list: 'ordered' }, { list: 'bullet' }],
    ['clean'],
  ],
};

// Quill's empty document is "<p><br></p>"; treat any tag-only content as empty.
const isEmptyHtml = (html) => !html || html.replace(/<[^>]*>/g, '').trim().length === 0;

export default function NewPostPage() {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');               // HTML from the editor
  const [tags, setTags] = useState([]);
  const [tagInput, setTagInput] = useState('');
  const [tagOptions, setTagOptions] = useState([]);
  const [imageUrl, setImageUrl] = useState('');
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState('');
  const { currentUser, authReady } = useContext(UserContext);
  const navigate = useNavigate();
  const debounceRef = useRef(null);

  useEffect(() => {
    if (authReady && !currentUser) navigate('/login');
  }, [authReady, currentUser]);

  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => navigate('/'), 2000);
    return () => clearTimeout(timer);
  }, [success]);

  // Debounced tag search — case-insensitive on the backend.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = tagInput.trim();
    if (!q) {
      setTagOptions([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const rows = await searchTags(q);
        setTagOptions(rows.map(r => r.name));
      } catch {
        setTagOptions([]);
      }
    }, 250);
    return () => debounceRef.current && clearTimeout(debounceRef.current);
  }, [tagInput]);

  const handleFileSelect = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';                 // allow re-selecting the same file
    if (!file) return;
    setError('');
    setUploading(true);
    try {
      const { url } = await uploadImage(file);
      setImageUrl(url);
    } catch (err) {
      setError(err.message || 'Image upload failed.');
    } finally {
      setUploading(false);
    }
  };

  const handlePublish = async () => {
    if (!title.trim() || isEmptyHtml(body)) {
      setError('Title and body are required.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      await createArticle(title.trim(), body, tags, imageUrl);
      setSuccess(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', mt: 6, px: 2 }}>
      <Card sx={{ width: '100%', maxWidth: 600 }}>
        <CardContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, p: 4 }}>
          <Typography variant="h5" fontWeight={700}>Create New Post</Typography>

          {success && (
            <Alert severity="success">
              Post published successfully! Redirecting to home...
            </Alert>
          )}
          {error && (
            <Alert severity="error" onClose={() => setError('')}>
              {error}
            </Alert>
          )}

          <TextField
            label="Title"
            placeholder="Enter post title..."
            value={title}
            onChange={e => setTitle(e.target.value)}
            disabled={success}
            fullWidth
          />

          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Body
            </Typography>
            {/* WYSIWYG editor — bold, italic, link, lists. Output is HTML. */}
            <Box sx={{ '& .ql-container': { minHeight: 180, fontSize: '1rem' } }}>
              <ReactQuill
                theme="snow"
                value={body}
                onChange={setBody}
                modules={QUILL_MODULES}
                readOnly={success}
                placeholder="Write your post content here..."
              />
            </Box>
          </Box>

          <Autocomplete
            multiple
            freeSolo
            disabled={success}
            options={tagOptions}
            value={tags}
            inputValue={tagInput}
            onInputChange={(_, value, reason) => {
              if (reason !== 'reset') setTagInput(value);
              else setTagInput('');
            }}
            onChange={(_, newValue) => {
              const trimmed = newValue.map(t => (typeof t === 'string' ? t.trim() : t)).filter(Boolean);
              const seen = new Set();
              const deduped = [];
              for (const t of trimmed) {
                if (!seen.has(t)) { seen.add(t); deduped.push(t); }
              }
              setTags(deduped);
            }}
            filterOptions={(opts) => opts}
            renderTags={(value, getTagProps) =>
              value.map((tag, i) => (
                <Chip key={`${tag}-${i}`} label={tag} {...getTagProps({ index: i })} />
              ))
            }
            renderInput={(params) => (
              <TextField
                {...params}
                label="Tags"
                placeholder="Type to search; press Enter to add"
                helperText="Existing matches appear in the dropdown (case-insensitive). Press Enter to add a new tag — exact casing is preserved."
              />
            )}
          />

          {/* Cover image: upload a file (local storage) or paste a URL. */}
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
            <Button
              variant="outlined"
              component="label"
              disabled={success || uploading}
              startIcon={uploading ? <CircularProgress size={16} /> : null}
            >
              {uploading ? 'Uploading...' : 'Upload Image'}
              <input type="file" accept="image/*" hidden onChange={handleFileSelect} />
            </Button>
            {imageUrl && (
              <Box
                component="img"
                src={imageUrl}
                alt="cover preview"
                sx={{ height: 48, borderRadius: 1, objectFit: 'cover' }}
              />
            )}
          </Box>
          <TextField
            label="Cover Image URL (optional)"
            placeholder="https://example.com/image.jpg — or use Upload Image above"
            value={imageUrl}
            onChange={e => setImageUrl(e.target.value)}
            disabled={success}
            fullWidth
          />

          <Button
            variant="contained"
            onClick={handlePublish}
            disabled={loading || success}
            startIcon={loading ? <CircularProgress size={18} color="inherit" /> : null}
          >
            {loading ? 'Publishing...' : 'Publish'}
          </Button>
        </CardContent>
      </Card>
    </Box>
  );
}
