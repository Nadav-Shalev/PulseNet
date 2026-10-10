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
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import SpellcheckIcon from '@mui/icons-material/Spellcheck';
import ReactQuill from 'react-quill-new';
import 'react-quill-new/dist/quill.snow.css';
import { UserContext } from '../context/UserContext';
import { aiCorrect, aiSuggestPost, createArticle, searchTags, uploadImage } from '../api/api';
import { AiSuggestion, useAiAssist } from '../components/AiSuggestion';

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
  const tagRequest = useRef(0);
  const [tagError, setTagError] = useState('');
  const [tagLoading, setTagLoading] = useState(false);
  const ai = useAiAssist();
  const editorRef = useRef(null);

  // Quill creates these DOM controls outside React; name them once it mounts.
  useEffect(() => {
    const editor = editorRef.current?.getEditor();
    if (!editor) return;
    editor.root.setAttribute('role', 'textbox');
    editor.root.setAttribute('aria-label', 'Post body');
    editor.root.setAttribute('aria-multiline', 'true');
    const toolbar = editor.getModule('toolbar').container;
    const labels = { bold: 'Bold', italic: 'Italic', underline: 'Underline', link: 'Insert link', clean: 'Clear formatting' };
    toolbar.querySelectorAll('button').forEach(button => {
      const format = [...button.classList].find(name => name.startsWith('ql-'))?.slice(3);
      button.setAttribute('aria-label', format === 'list' ? (button.value === 'ordered' ? 'Numbered list' : 'Bullet list') : labels[format] || format);
    });
  }, []);

  useEffect(() => {
    if (authReady && !currentUser) navigate('/login');
  }, [authReady, currentUser, navigate]);

  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => navigate('/'), 2000);
    return () => clearTimeout(timer);
  }, [success, navigate]);

  // Debounced tag search — case-insensitive on the backend.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const request = ++tagRequest.current;
    setTagError('');
    const q = tagInput.trim();
    if (!q) {
      setTagOptions([]);
      setTagLoading(false);
      return;
    }
    setTagOptions([]);
    setTagLoading(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const rows = await searchTags(q);
        if (request === tagRequest.current) setTagOptions(rows.map(r => r.name));
      } catch {
        if (request === tagRequest.current) setTagError('Tag suggestions are unavailable. You can still type a tag and press Enter.');
      } finally {
        if (request === tagRequest.current) setTagLoading(false);
      }
    }, 250);
    return () => { tagRequest.current = request + 1; clearTimeout(debounceRef.current); };
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
    if (loading || uploading || ai.busy || success || !authReady || !currentUser) return;
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
    <Box sx={{ display: 'flex', justifyContent: 'center', mt: { xs: 0, sm: 3 } }}>
      <Card sx={{ width: '100%', maxWidth: 600 }}>
        <CardContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, p: { xs: 2.5, sm: 4 } }}>
          <Typography variant="h5" component="h1" fontWeight={700}>Create New Post</Typography>

          {success && (
            <Alert severity="success">
              Post published successfully! Redirecting to home...
            </Alert>
          )}
          {error && (
            <Alert severity="error" onClose={() => setError('')} data-testid="post-error">
              {error}
            </Alert>
          )}

          <TextField
            label="Title"
            placeholder="Enter post title..."
            value={title}
            onChange={e => setTitle(e.target.value)}
            disabled={success || loading || uploading || ai.busy}
            fullWidth
            slotProps={{ htmlInput: { 'data-testid': 'post-title-input' } }}
          />

          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Body
            </Typography>
            {/* WYSIWYG editor — bold, italic, link, lists. Output is HTML. */}
            <Box sx={{ '& .ql-container': { minHeight: 180, fontSize: '1rem' } }}>
              <ReactQuill
                ref={editorRef}
                theme="snow"
                value={body}
                onChange={setBody}
                modules={QUILL_MODULES}
                readOnly={success || loading || ai.busy}
                placeholder="Write your post content here..."
              />
            </Box>
            {/* AI help: the result is a suggestion to apply or dismiss, never written in directly. */}
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 1 }}>
              <Button
                size="small"
                variant="outlined"
                startIcon={<SpellcheckIcon />}
                onClick={() => ai.run(() => aiCorrect(body, 'html'), { html: true, onApply: setBody })}
                disabled={success || loading || uploading || ai.busy || isEmptyHtml(body)}
                data-testid="ai-correct-post"
              >
                Fix grammar
              </Button>
              <Button
                size="small"
                variant="outlined"
                startIcon={<AutoAwesomeIcon />}
                onClick={() => ai.run(() => aiSuggestPost(title.trim(), tags), { html: true, onApply: setBody })}
                disabled={success || loading || uploading || ai.busy || !title.trim()}
                data-testid="ai-suggest-post"
              >
                Draft from title
              </Button>
            </Box>
            <AiSuggestion assist={ai} disabled={loading || uploading || success} />
          </Box>

          <Autocomplete
            multiple
            freeSolo
            disabled={success || loading || uploading || ai.busy}
            options={tagOptions}
            loading={tagLoading}
            value={tags}
            inputValue={tagInput}
            onInputChange={(_, value, reason) => {
              tagRequest.current++;
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

          {tagError && <Alert severity="warning">{tagError}</Alert>}

          {/* Cover image: upload a file (local storage) or paste a URL. */}
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
            <Button
              variant="outlined"
              component="label"
              tabIndex={-1}
              disabled={success || loading || uploading || ai.busy}
              startIcon={uploading ? <CircularProgress size={16} /> : null}
            >
              {uploading ? 'Uploading...' : 'Upload Image'}
              <input type="file" aria-label="Upload cover image" accept="image/*" disabled={success || loading || uploading || ai.busy} style={{ position: 'absolute', width: 1, height: 1, clipPath: 'inset(50%)' }} onChange={handleFileSelect} />
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
            disabled={success || loading || uploading || ai.busy}
            fullWidth
          />

          <Button
            variant="contained"
            onClick={handlePublish}
            disabled={loading || uploading || ai.busy || success || !authReady || !currentUser}
            data-testid="post-publish"
            startIcon={loading ? <CircularProgress size={18} color="inherit" /> : null}
          >
            {loading ? 'Publishing...' : 'Publish'}
          </Button>
        </CardContent>
      </Card>
    </Box>
  );
}
