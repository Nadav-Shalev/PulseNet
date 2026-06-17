import { Routes, Route } from 'react-router-dom';
import Box from '@mui/material/Box';
import TopBar from './components/TopBar';
import HomePage from './pages/HomePage';
import UserPage from './pages/UserPage';
import UserPostsPage from './pages/UserPostsPage';
import UserProfilePage from './pages/UserProfilePage';
import TagPostsPage from './pages/TagPostsPage';
import LoginPage from './pages/LoginPage';
import SignupPage from './pages/SignupPage';
import NewPostPage from './pages/NewPostPage';
import EditProfilePage from './pages/EditProfilePage';
import AboutPage from './pages/AboutPage';
import { UserProvider } from './context/UserContext';

export default function App() {
  return (
    <UserProvider>
      <main className="App-main">
        <TopBar />
        <Box sx={{ paddingTop: 2 }}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/users" element={<UserPage />} />
            <Route path="/user-posts/:username" element={<UserPostsPage />} />
            <Route path="/profile/:username" element={<UserProfilePage />} />
            <Route path="/tag/:tagName" element={<TagPostsPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/new-post" element={<NewPostPage />} />
            <Route path="/edit-profile" element={<EditProfilePage />} />
            <Route path="/about" element={<AboutPage />} />
            <Route path="*" element={<HomePage />} />
          </Routes>
        </Box>
      </main>
    </UserProvider>
  );
}
