import { useContext } from 'react';
import AppBar from '@mui/material/AppBar';
import Box from '@mui/material/Box';
import Toolbar from '@mui/material/Toolbar';
import IconButton from '@mui/material/IconButton';
import Typography from '@mui/material/Typography';
import Menu from '@mui/material/Menu';
import MenuIcon from '@mui/icons-material/Menu';
import Container from '@mui/material/Container';
import Button from '@mui/material/Button';
import MenuItem from '@mui/material/MenuItem';
import Avatar from '@mui/material/Avatar';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogActions from '@mui/material/DialogActions';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { UserContext } from '../../context/UserContext';
import { logoutUser } from '../../api/api';
import SettingsMenu from './SettingsMenu';
import brandMark from '../../assets/pulsenet-mark.svg?no-inline';

const navSx = {
  color: 'inherit', minWidth: 0, px: 1.25,
  '&.active': { bgcolor: 'rgba(255,255,255,0.16)' },
  '&:focus-visible': { outlineColor: 'white' },
};

const pages = [
  { label: 'Home', to: '/' },
  { label: 'Users', to: '/users' },
  { label: 'About', to: '/about' },
];

export default function TopBar() {
  const [anchorElNav, setAnchorElNav] = useState(null);
  const [logoutOpen, setLogoutOpen] = useState(false);
  const [logoutBusy, setLogoutBusy] = useState(false);
  const { currentUser, logout } = useContext(UserContext);
  // Only decides whether the link shows: the admin page and API check the role again.
  const isAdmin = currentUser?.role === 'admin';
  const navigate = useNavigate();

  const handleOpenNavMenu = (e) => setAnchorElNav(e.currentTarget);
  const handleCloseNavMenu = () => setAnchorElNav(null);

  const handleLogout = async (allDevices = false) => {
    if (logoutBusy) return;
    setLogoutBusy(true);
    // Tell the backend to drop the session row(s) + clear the cookie first;
    // even if the request fails, drop the local state so the UI reflects logout.
    setLogoutOpen(false);
    try { await logoutUser(allDevices); } catch { /* ignore */ }
    setLogoutBusy(false);
    logout();
    navigate('/');
  };

  return (
    <AppBar position="static" component="header">
      <Container maxWidth={false} sx={{ maxWidth: 1200, px: { xs: 2, sm: 3 } }}>
        <Toolbar component="nav" aria-label="Main navigation" disableGutters>
          {/* Left side: App name + Profile + New Post button */}
          <Typography
            variant="h6"
            noWrap
            component={Link}
            to="/"
            sx={{
              mr: 2,
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              flexShrink: 0,
              flexGrow: { xs: 1, md: 0 },
              fontFamily: 'monospace',
              fontWeight: 700,
              letterSpacing: '.04rem',
              color: 'inherit',
              textDecoration: 'none',
            }}
          >
            <Box component="img" src={brandMark} alt="" sx={{ width: 32, height: 32 }} />
            PulseNet
          </Typography>

          {currentUser && (
            <Button
              data-testid="nav-profile"
              component={NavLink}
              to={`/profile/${currentUser.username}`}
              startIcon={
                <Avatar
                  src={currentUser.profile_image || currentUser.avatar}
                  alt={currentUser.name}
                  sx={{ width: 28, height: 28 }}
                >
                  {currentUser.name?.[0] ?? '?'}
                </Avatar>
              }
              sx={{
                ...navSx,
                mr: 1,
                display: { xs: 'none', md: 'flex' },
                color: 'white',
              }}
            >
              Profile
            </Button>
          )}

          {currentUser && (
            <Button
              component={Link}
              to="/new-post"
              sx={{
                mr: 2,
                display: { xs: 'none', md: 'flex' },
                backgroundColor: 'secondary.main',
                color: 'secondary.contrastText',
                '&:hover': { backgroundColor: 'secondary.dark' },
              }}
            >
              + New Post
            </Button>
          )}

          {/* Desktop nav - right side */}
          <Box sx={{ flexGrow: 1, display: { xs: 'none', md: 'flex' }, justifyContent: 'flex-end', alignItems: 'center' }}>
            {pages.map(page => (
              <Button
                key={page.label}
                component={NavLink}
                end
                to={page.to}
                sx={{ ...navSx, my: 1 }}
              >
                {page.label}
              </Button>
            ))}

            {isAdmin && (
              <Button
                component={NavLink}
                to="/admin"
                data-testid="nav-admin"
                sx={{ ...navSx, my: 1 }}
              >
                Admin
              </Button>
            )}

            {!currentUser && (
              <Button component={Link} to="/login" sx={{ ...navSx, my: 1 }}>
                Login
              </Button>
            )}
          </Box>
          <SettingsMenu canLogout={Boolean(currentUser)} logoutBusy={logoutBusy} onLogout={() => setLogoutOpen(true)} />

          {/* Mobile menu */}
          <Box sx={{ display: { xs: 'flex', md: 'none' } }}>
            <IconButton size="large" onClick={handleOpenNavMenu} color="inherit"
              aria-label="Open navigation menu" aria-controls={anchorElNav ? 'mobile-navigation' : undefined}
              aria-expanded={Boolean(anchorElNav)} aria-haspopup="true">
              <MenuIcon />
            </IconButton>
            <Menu
              id="mobile-navigation"
              anchorEl={anchorElNav}
              anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
              keepMounted
              transformOrigin={{ vertical: 'top', horizontal: 'left' }}
              open={Boolean(anchorElNav)}
              onClose={handleCloseNavMenu}
              sx={{ display: { xs: 'block', md: 'none' } }}
            >
              {pages.map(page => (
                <MenuItem key={page.label} component={NavLink} end to={page.to} onClick={handleCloseNavMenu}>
                  <Typography sx={{ textAlign: 'center' }}>{page.label}</Typography>
                </MenuItem>
              ))}
              {isAdmin && (
                <MenuItem component={Link} to="/admin" onClick={handleCloseNavMenu} data-testid="nav-admin-mobile">
                  <Typography sx={{ textAlign: 'center' }}>Admin</Typography>
                </MenuItem>
              )}
              {currentUser && (
                <MenuItem component={Link} to="/new-post" onClick={handleCloseNavMenu}>
                  <Typography sx={{ textAlign: 'center' }}>+ New Post</Typography>
                </MenuItem>
              )}
              {currentUser && (
                <MenuItem component={Link} to={`/profile/${currentUser.username}`} onClick={handleCloseNavMenu}>
                  <Avatar
                    src={currentUser.profile_image || currentUser.avatar}
                    alt={currentUser.name}
                    sx={{ width: 24, height: 24, mr: 1 }}
                  >
                    {currentUser.name?.[0] ?? '?'}
                  </Avatar>
                  <Typography sx={{ textAlign: 'center' }}>Profile</Typography>
                </MenuItem>
              )}
              {!currentUser && (
                <MenuItem component={Link} to="/login" onClick={handleCloseNavMenu}>
                  <Typography sx={{ textAlign: 'center' }}>Login</Typography>
                </MenuItem>
              )}
            </Menu>
          </Box>
        </Toolbar>
      </Container>

      {/* Logout confirmation: choose this device only vs. all devices. */}
      <Dialog open={logoutOpen} onClose={() => setLogoutOpen(false)} aria-labelledby="logout-title">
        <DialogTitle id="logout-title">Log out</DialogTitle>
        <DialogContent>
          <DialogContentText>Choose how you want to log out.</DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setLogoutOpen(false)}>Cancel</Button>
          <Button data-testid="logout-current-device" onClick={() => handleLogout(false)}>Logout from this device</Button>
          <Button color="error" onClick={() => handleLogout(true)}>
            Logout from all devices
          </Button>
        </DialogActions>
      </Dialog>
    </AppBar>
  );
}
