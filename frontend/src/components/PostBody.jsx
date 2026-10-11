import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';

// Displays one sanitized body, loading it near the viewport and measuring its preview.
export default function PostBody({ html, excerpt, loading, error, onLoad }) {
  const bodyId = useId();
  // Keep React from replacing unchanged HTML after our local focus adjustment.
  const markup = useMemo(() => ({ __html: html }), [html]);
  const rootRef = useRef(null);
  const clipRef = useRef(null);
  const contentRef = useRef(null);
  const toggleRef = useRef(null);
  const scrollAfterCollapse = useRef(false);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    if (html !== null || error) return undefined;
    if (!window.IntersectionObserver) {
      onLoad();
      return undefined;
    }
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        observer.disconnect();
        onLoad();
      }
    }, { rootMargin: '200px' });
    observer.observe(rootRef.current);
    return () => observer.disconnect();
  }, [html, error, onLoad]);

  useLayoutEffect(() => {
    const content = contentRef.current;
    const clip = clipRef.current;
    if (!content || !clip) return undefined;
    const links = [...content.querySelectorAll('a[href]')];
    const measure = () => {
      // Measure the browser's actual three-line layout, including rich-text
      // block spacing and heading sizes. Restore expansion before painting.
      const previousClamp = clip.style.webkitLineClamp;
      const previousExpanded = clip.dataset.expanded;
      clip.dataset.expanded = 'false';
      clip.style.webkitLineClamp = '3';
      const bottom = clip.getBoundingClientRect().bottom;
      setOverflows(clip.scrollHeight > clip.clientHeight + 1);
      clip.style.webkitLineClamp = previousClamp;
      clip.dataset.expanded = previousExpanded;
      // Sanitized anchors have no authored tabindex. Keep clipped links out of
      // the tab order without changing the HTML or rebuilding its structure.
      links.forEach(link => {
        const clipped = !expanded && [...link.getClientRects()].some(rect => rect.bottom > bottom + 1);
        if (clipped) link.setAttribute('tabindex', '-1');
        else link.removeAttribute('tabindex');
      });
    };
    measure();
    if (scrollAfterCollapse.current) {
      scrollAfterCollapse.current = false;
      const button = toggleRef.current;
      const rect = button?.getBoundingClientRect();
      if (rect && (rect.top < 0 || rect.bottom > window.innerHeight)) {
        button.scrollIntoView({ block: 'nearest' });
      }
    }
    const observer = window.ResizeObserver ? new ResizeObserver(measure) : null;
    if (observer) observer.observe(content);
    else window.addEventListener('resize', measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
      links.forEach(link => link.removeAttribute('tabindex'));
    };
  }, [html, expanded]);

  return (
    <Box ref={rootRef} data-testid="post-body" sx={{ typography: 'body2' }}>
      {html === null ? (
        <Typography variant="body2" color="text.secondary">{excerpt}</Typography>
      ) : (
        <Box ref={clipRef} id={bodyId} data-expanded={expanded} sx={{
          display: '-webkit-box',
          WebkitBoxOrient: 'vertical',
          WebkitLineClamp: expanded ? 'unset' : 3,
          overflow: expanded ? 'visible' : 'hidden',
          // A scrollable pre creates a separate formatting context in Chromium.
          // Let its lines join the preview; restore scrolling when expanded.
          '&[data-expanded="false"] pre': { overflow: 'visible', pb: 0 },
        }}>
          <Box
            ref={contentRef}
            className="rich-text"
            sx={{ '& > :first-child': { mt: 0 }, '& > :last-child': { mb: 0 } }}
            dangerouslySetInnerHTML={markup}
          />
        </Box>
      )}
      {loading && <Typography role="status" variant="caption" color="text.secondary">Loading post body...</Typography>}
      {error && <Alert severity="error" sx={{ mt: 1 }} action={
        <Button color="inherit" disabled={loading} onClick={() => onLoad(true)}>Retry</Button>
      }>{error}</Alert>}
      {html !== null && overflows && (
        <Button
          ref={toggleRef}
          size="small"
          data-testid="post-body-toggle"
          aria-expanded={expanded}
          aria-controls={bodyId}
          onClick={() => {
            scrollAfterCollapse.current = expanded;
            setExpanded(value => !value);
          }}
          sx={{ mt: 0.5 }}
        >{expanded ? 'Read Less' : 'Read More'}</Button>
      )}
    </Box>
  );
}
