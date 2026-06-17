import { useState, useContext } from 'react';
import Box from '@mui/material/Box';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';
import Feed from '../features/feed/Feed';
import { UserContext } from '../context/UserContext';

function HomePage() {
  const { currentUser } = useContext(UserContext);
  const [tab, setTab] = useState('global');

  // The Following tab only exists when logged in; if the user logs out while it's
  // selected, fall back to Global so the Tabs value always matches a rendered tab.
  const activeTab = (!currentUser && tab === 'following') ? 'global' : tab;

  return (
    <div className="App-feed">
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 1 }}>
        <Tabs value={activeTab} onChange={(_, v) => setTab(v)} centered>
          <Tab label="Global" value="global" />
          {currentUser && <Tab label="Following" value="following" />}
        </Tabs>
      </Box>

      {activeTab === 'following' ? (
        <Feed
          feed="following"
          emptyMessage="No posts yet — follow some users to see their posts here."
        />
      ) : (
        <Feed />
      )}
    </div>
  );
}

export default HomePage;
