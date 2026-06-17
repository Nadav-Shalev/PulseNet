import { createContext, useState, useEffect } from 'react';
import { fetchMe } from '../api/api';

export const UserContext = createContext(null);

export function UserProvider({ children }) {
  const [currentUser, setCurrentUser] = useState(null);
  // authReady is false until the initial /api/me check finishes — useful for
  // gating "must be logged in" redirects so they don't fire before re-hydration.
  const [authReady, setAuthReady] = useState(false);

  // On mount, ask the backend whether the cookie still maps to a live session.
  useEffect(() => {
    let cancelled = false;
    fetchMe()
      .then(user => { if (!cancelled) setCurrentUser(user); })
      .catch(() => { /* network error → leave currentUser null */ })
      .finally(() => { if (!cancelled) setAuthReady(true); });
    return () => { cancelled = true; };
  }, []);

  return (
    <UserContext.Provider value={{
      currentUser,
      authReady,
      login: (user) => setCurrentUser(user),
      logout: () => setCurrentUser(null),
    }}>
      {children}
    </UserContext.Provider>
  );
}
