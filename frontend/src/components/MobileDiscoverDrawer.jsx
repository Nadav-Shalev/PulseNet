import { useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import SwipeableDrawer from '@mui/material/SwipeableDrawer';
import Typography from '@mui/material/Typography';
import ExploreOutlined from '@mui/icons-material/ExploreOutlined';
import Close from '@mui/icons-material/Close';
import HomeSidebar from './HomeSidebar';

export default function MobileDiscoverDrawer() {
  const [open, setOpen] = useState(false);
  const [visited, setVisited] = useState(false);
  const show = () => { setVisited(true); setOpen(true); };
  const close = () => setOpen(false);

  return (
    <>
      <Button
        startIcon={<ExploreOutlined />}
        onClick={show}
        aria-label="Discover"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={visited ? 'mobile-discover-dialog' : undefined}
        data-testid="mobile-discover-open"
        size="small"
      >Discover</Button>
      {visited && <SwipeableDrawer
        anchor="right"
        open={open}
        onOpen={show}
        onClose={close}
        disableSwipeToOpen
        disableDiscovery
        ModalProps={{ keepMounted: true }}
        slotProps={{ paper: {
          id: 'mobile-discover-dialog',
          role: 'dialog',
          'aria-modal': true,
          'aria-labelledby': 'mobile-discover-title',
          'data-testid': 'mobile-discover-drawer',
          sx: {
            width: 360, maxWidth: 'calc(100vw - 24px)', boxSizing: 'border-box',
            p: 2, pt: 'max(16px, env(safe-area-inset-top))',
            pb: 'max(16px, env(safe-area-inset-bottom))',
            pr: 'max(16px, env(safe-area-inset-right))',
            bgcolor: 'background.default', overflowY: 'auto',
          },
        } }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Typography id="mobile-discover-title" component="h2" variant="h6">Discover</Typography>
          <IconButton aria-label="Close discovery" onClick={close}><Close /></IconButton>
        </Box>
        <HomeSidebar onNavigate={close} />
      </SwipeableDrawer>}
    </>
  );
}
