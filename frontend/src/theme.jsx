import { useMemo } from 'react';
import { createTheme, ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import useMediaQuery from '@mui/material/useMediaQuery';

// One palette owns both MUI surfaces and the rich text/editor inside them.
export default function AppTheme({ children }) {
  const dark = useMediaQuery('(prefers-color-scheme: dark)');
  const theme = useMemo(() => createTheme({
    palette: {
      mode: dark ? 'dark' : 'light',
      primary: { main: dark ? '#90c4ff' : '#1565c0' },
      secondary: { main: dark ? '#ffbd75' : '#a74400' },
      background: { default: dark ? '#101820' : '#f3f6fa', paper: dark ? '#192530' : '#ffffff' },
      text: { primary: dark ? '#edf3fa' : '#182b40', secondary: dark ? '#b6c5d5' : '#526477' },
      divider: dark ? '#354655' : '#dbe3ec',
    },
    typography: {
      fontFamily: "system-ui, 'Segoe UI', Roboto, sans-serif",
      h5: { fontWeight: 700, letterSpacing: '-0.02em' },
      h6: { fontWeight: 650, lineHeight: 1.4 },
      button: { textTransform: 'none', fontWeight: 600 },
      body2: { lineHeight: 1.6 },
    },
    shape: { borderRadius: 10 },
    components: {
      MuiCssBaseline: { styleOverrides: (t) => ({
        'a:focus-visible, button:focus-visible, [tabindex]:focus-visible, label.MuiButton-root:focus-within': {
          outline: `3px solid ${t.palette.primary.main}`, outlineOffset: 3,
        },
        '.rich-text': {
          overflowWrap: 'anywhere', lineHeight: 1.75,
          '& p': { margin: '0 0 0.75em' },
          '& img': { maxWidth: '100%', height: 'auto', display: 'block', margin: '8px 0' },
          '& a': { color: t.palette.primary.main },
          '& pre': { overflowX: 'auto', padding: 16, background: t.palette.action.hover, borderRadius: 8 },
          '& code': { fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '0.9em' },
          '& h1, & h2, & h3': { lineHeight: 1.3, margin: '1em 0 0.5em' },
        },
        '.ql-toolbar.ql-snow, .ql-container.ql-snow': { borderColor: t.palette.divider },
        '.ql-snow .ql-stroke': { stroke: t.palette.text.primary },
        '.ql-snow .ql-fill, .ql-snow .ql-stroke.ql-fill': { fill: t.palette.text.primary },
        '.ql-snow .ql-picker, .ql-editor': { color: t.palette.text.primary },
        '.ql-editor.ql-blank::before': { color: t.palette.text.secondary },
        '.ql-snow .ql-tooltip': { background: t.palette.background.paper, color: t.palette.text.primary },
        '.ql-snow .ql-tooltip input': { background: t.palette.background.paper, color: t.palette.text.primary },
        '.ql-editor a, .ql-snow .ql-tooltip a': { color: t.palette.primary.main },
        '.ql-snow.ql-toolbar button:hover .ql-stroke, .ql-snow.ql-toolbar button:focus .ql-stroke, .ql-snow.ql-toolbar button.ql-active .ql-stroke': { stroke: t.palette.primary.main },
        '.ql-snow.ql-toolbar button:hover .ql-fill, .ql-snow.ql-toolbar button:focus .ql-fill, .ql-snow.ql-toolbar button.ql-active .ql-fill': { fill: t.palette.primary.main },
        '.ql-toolbar button:focus-visible': { outline: `2px solid ${t.palette.primary.main}` },
      }) },
      MuiAppBar: { styleOverrides: { root: { backgroundColor: dark ? '#172e45' : '#155eaa', color: '#fff', boxShadow: 'none' } } },
      MuiCard: { styleOverrides: { root: ({ theme: t }) => ({
        border: `1px solid ${t.palette.divider}`, boxShadow: '0 2px 8px rgb(0 0 0 / 4%)',
      }) } },
      MuiPaper: { styleOverrides: { root: { backgroundImage: 'none' } } },
      MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { minHeight: 36 } } },
      MuiDialogActions: { styleOverrides: { root: { padding: 16, gap: 8, flexWrap: 'wrap' } } },
      MuiDialogTitle: { styleOverrides: { root: { overflowWrap: 'anywhere' } } },
    },
  }), [dark]);

  return <ThemeProvider theme={theme}><CssBaseline enableColorScheme />{children}</ThemeProvider>;
}
