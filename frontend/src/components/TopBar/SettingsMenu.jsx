import { useContext, useRef, useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Divider from '@mui/material/Divider';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import ListSubheader from '@mui/material/ListSubheader';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Tooltip from '@mui/material/Tooltip';
import CheckIcon from '@mui/icons-material/Check';
import LogoutIcon from '@mui/icons-material/Logout';
import SettingsIcon from '@mui/icons-material/Settings';
import { ThemePreferenceContext } from '../../theme';

const themes = [['light', 'Light'], ['dark', 'Dark'], ['system', 'System']];

// Settings changes the browser theme and opens the existing logout confirmation.
export default function SettingsMenu({ canLogout, logoutBusy, onLogout }) {
  const { preference, setPreference } = useContext(ThemePreferenceContext);
  const [anchor, setAnchor] = useState(null);
  const logoutAfterClose = useRef(false);
  const currentLabel = themes.find(([value]) => value === preference)[1];

  return (
    <>
      <Tooltip title={`Settings · Theme: ${currentLabel}`}>
        <Button
          id="settings-button"
          data-testid="nav-settings"
          color="inherit"
          aria-label="Open settings"
          aria-haspopup="menu"
          aria-controls={anchor ? 'settings-menu' : undefined}
          aria-expanded={Boolean(anchor)}
          onClick={event => setAnchor(event.currentTarget)}
          sx={{ minWidth: 44, minHeight: 44, px: 1, gap: 0.75, '&:focus-visible': { outlineColor: 'white' } }}
        >
          <SettingsIcon />
          <Box component="span" sx={{ display: { xs: 'none', md: 'inline' } }}>Settings</Box>
        </Button>
      </Tooltip>
      <Menu
        id="settings-menu"
        anchorEl={anchor}
        open={Boolean(anchor)}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{
          list: { 'aria-label': 'Settings' },
          paper: { sx: { minWidth: 220, maxWidth: 'calc(100vw - 32px)' } },
          transition: { onExited: () => {
            if (logoutAfterClose.current) {
              logoutAfterClose.current = false;
              onLogout();
            }
          } },
        }}
      >
        <ListSubheader disableSticky>Theme</ListSubheader>
        {themes.map(([value, label]) => (
          <MenuItem
            key={value}
            role="menuitemradio"
            aria-checked={preference === value}
            selected={preference === value}
            data-testid={`theme-${value}`}
            onClick={() => { setPreference(value); setAnchor(null); }}
          >
            <ListItemIcon>{preference === value && <CheckIcon fontSize="small" />}</ListItemIcon>
            <ListItemText primary={label} secondary={value === 'system' ? 'Follow your device' : undefined} />
          </MenuItem>
        ))}
        {canLogout && <Divider />}
        {canLogout && (
          <MenuItem data-testid="nav-logout" disabled={logoutBusy} onClick={() => {
            logoutAfterClose.current = true;
            setAnchor(null);
          }}>
            <ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>
            <ListItemText data-testid="settings-logout">Logout</ListItemText>
          </MenuItem>
        )}
      </Menu>
    </>
  );
}
