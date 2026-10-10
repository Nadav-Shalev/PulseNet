import { useState, useContext } from 'react';
import Box from '@mui/material/Box';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';
import Feed from '../features/feed/Feed';
import HomeSidebar from '../components/HomeSidebar';
import { UserContext } from '../context/UserContext';

function HomePage() {
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
        // From lg (1200px) the sidebar is a column beside the feed; below that it
        // sits between the tabs and the feed.
        gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'minmax(0, 1fr) 300px' },
        gridTemplateAreas: { xs: '"tabs" "side" "feed"', lg: '"tabs side" "feed side"' },
        gridTemplateRows: { lg: 'auto 1fr' },
        columnGap: 2,
        alignItems: 'start',
      }}
    >
      <Box sx={{ gridArea: 'tabs', borderBottom: 1, borderColor: 'divider', mb: 1 }}>
        <Tabs value={activeTab} onChange={(_, v) => setTab(v)} centered>
          <Tab label="Global" value="global" />
          {currentUser && <Tab label="Following" value="following" />}
        </Tabs>
      </Box>

      <Box
        component="aside"
        sx={{
          gridArea: 'side',
          px: { xs: 2, lg: 0 },
          pr: { lg: 2 },
          mb: { xs: 2, lg: 0 },
          position: { lg: 'sticky' },
          top: { lg: 16 },
        }}
      >
        <HomeSidebar />
      </Box>

      <Box sx={{ gridArea: 'feed', minWidth: 0 }}>
        {activeTab === 'following' ? (
          <Feed
            feed="following"
            emptyMessage="No posts yet — follow some users to see their posts here."
          />
        ) : (
          <Feed />
        )}
      </Box>
    </Box>
  );
}

export default HomePage;
