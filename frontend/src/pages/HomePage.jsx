import { useState, useContext } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';
import useMediaQuery from '@mui/material/useMediaQuery';
import { useTheme } from '@mui/material/styles';
import MobileDiscoverDrawer from '../components/MobileDiscoverDrawer';
import Feed from '../features/feed/Feed';
import HomeSidebar from '../components/HomeSidebar';
import { UserContext } from '../context/UserContext';

function HomePage() {
  const theme = useTheme();
  const desktop = useMediaQuery(theme.breakpoints.up('lg'));
  const { currentUser } = useContext(UserContext);
  const [tab, setTab] = useState('global');

  // The Following tab only exists when logged in; if the user logs out while it's
  // selected, fall back to Global so the Tabs value always matches a rendered tab.
  const activeTab = (!currentUser && tab === 'following') ? 'global' : tab;

  return (
    <Box
      className="App-feed"
      sx={{
        display: 'grid',
        // Discovery lives beside the feed on desktop and in a drawer below lg.
        gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'minmax(0, 1fr) 300px' },
        gridTemplateAreas: { xs: '"tabs" "feed"', lg: '"tabs side" "feed side"' },
        gridTemplateRows: { lg: 'auto 1fr' },
        columnGap: 3,
        alignItems: 'start',
      }}
    >
      <Box sx={{ gridArea: 'tabs', borderBottom: 1, borderColor: 'divider', mb: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 1 }}>
          <Typography component="h1" variant="h5">Your feed</Typography>
          {!desktop && <MobileDiscoverDrawer />}
        </Box>
        <Tabs aria-label="Feed source" value={activeTab} onChange={(_, v) => setTab(v)}>
          <Tab id="feed-global-tab" aria-controls="feed-panel" label="Global" value="global" />
          {currentUser && <Tab id="feed-following-tab" aria-controls="feed-panel" label="Following" value="following" />}
        </Tabs>
      </Box>

      <Box id="feed-panel" role="tabpanel" aria-labelledby={`feed-${activeTab}-tab`} sx={{ gridArea: 'feed', minWidth: 0 }}>
        {activeTab === 'following' ? (
          <Feed
            feed="following"
            emptyMessage="No posts yet — follow some users to see their posts here."
          />
        ) : (
          <Feed />
        )}
      </Box>

      {desktop && <Box
        component="aside"
        sx={{
          gridArea: 'side',
          minWidth: 0,
          mt: { xs: 2, lg: 0 },
          position: { lg: 'sticky' },
          top: { lg: 16 },
        }}
      >
        <HomeSidebar />
      </Box>}
    </Box>
  );
}

export default HomePage;
