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
import { Link, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { UserContext } from '../../context/UserContext';
import { logoutUser } from '../../api/api';

const pages = [
  { label: 'Home', to: '/' },
  { label: 'Users', to: '/users' },
  { label: 'About', to: '/about' },
];

export default function TopBar() {
  const [anchorElNav, setAnchorElNav] = useState(null);
  const [logoutOpen, setLogoutOpen] = useState(false);
  const { currentUser, logout } = useContext(UserContext);
  const navigate = useNavigate();

  const handleOpenNavMenu = (e) => setAnchorElNav(e.currentTarget);
  const handleCloseNavMenu = () => setAnchorElNav(null);

  const handleLogout = async (allDevices = false) => {
    // Tell the backend to drop the session row(s) + clear the cookie first;
    // even if the request fails, drop the local state so the UI reflects logout.
    setLogoutOpen(false);
    try { await logoutUser(allDevices); } catch { /* ignore */ }
    logout();
    navigate('/');
  };

  return (
    <AppBar position="static">
      <Container maxWidth="xl">
        <Toolbar disableGutters>
          {/* Left side: App name + Profile + New Post button */}
          <Typography
            variant="h6"
            noWrap
            component={Link}
            to="/"
            sx={{
              mr: 2,
              display: { xs: 'none', md: 'flex' },
              fontFamily: 'monospace',
              fontWeight: 700,
              letterSpacing: '.1rem',
              color: 'inherit',
              textDecoration: 'none',
            }}
          >
            PulseNet
          </Typography>

          {currentUser && (
            <Button
              data-testid="nav-profile"
              component={Link}
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
                mr: 2,
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
                color: 'white',
                backgroundColor: 'orange',
                '&:hover': { backgroundColor: '#e65c00' },
              }}
            >
              + New Post
            </Button>
          )}

          {/* Mobile menu */}
          <Box sx={{ flexGrow: 1, display: { xs: 'flex', md: 'none' } }}>
            <IconButton size="large" onClick={handleOpenNavMenu} color="inherit">
              <MenuIcon />
            </IconButton>
            <Menu
              anchorEl={anchorElNav}
              anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
              keepMounted
              transformOrigin={{ vertical: 'top', horizontal: 'left' }}
              open={Boolean(anchorElNav)}
              onClose={handleCloseNavMenu}
              sx={{ display: { xs: 'block', md: 'none' } }}
            >
              {pages.map(page => (
                <MenuItem key={page.label} component={Link} to={page.to} onClick={handleCloseNavMenu}>
                  <Typography textAlign="center">{page.label}</Typography>
                </MenuItem>
              ))}
              {currentUser && (
                <MenuItem component={Link} to="/new-post" onClick={handleCloseNavMenu}>
                  <Typography textAlign="center">+ New Post</Typography>
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
                  <Typography textAlign="center">Profile</Typography>
                </MenuItem>
              )}
              {currentUser ? (
                <MenuItem onClick={() => { handleCloseNavMenu(); setLogoutOpen(true); }}>
                  <Typography textAlign="center">Logout</Typography>
                </MenuItem>
              ) : (
                <MenuItem component={Link} to="/login" onClick={handleCloseNavMenu}>
                  <Typography textAlign="center">Login</Typography>
                </MenuItem>
              )}
            </Menu>
          </Box>

          {/* Desktop nav - right side */}
          <Box sx={{ flexGrow: 1, display: { xs: 'none', md: 'flex' }, justifyContent: 'flex-end', alignItems: 'center' }}>
            {pages.map(page => (
              <Button
                key={page.label}
                component={Link}
                to={page.to}
                sx={{ my: 2, color: 'white', display: 'block' }}
              >
                {page.label}
              </Button>
            ))}

            {currentUser ? (
              <Button data-testid="nav-logout" sx={{ my: 2, color: 'orange' }} onClick={() => setLogoutOpen(true)}>
                Logout
              </Button>
            ) : (
              <Button component={Link} to="/login" sx={{ my: 2, color: 'white', display: 'block' }}>
                Login
              </Button>
            )}
          </Box>
        </Toolbar>
      </Container>

      {/* Logout confirmation: choose this device only vs. all devices. */}
      <Dialog open={logoutOpen} onClose={() => setLogoutOpen(false)}>
        <DialogTitle>Log out</DialogTitle>
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
