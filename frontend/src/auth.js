// auth.js — simple client-side auth with localStorage session

const SESSION_KEY = 'av_session';

// Add / remove users here
const USERS = [
  { username: 'admin',    password: 'aviator2024' },
  { username: 'analyst',  password: 'risk@2024'   },
];

export function login(username, password) {
  const user = USERS.find(
    u => u.username === username.trim().toLowerCase() && u.password === password
  );
  if (!user) return false;
  sessionStorage.setItem(SESSION_KEY, JSON.stringify({ username: user.username }));
  return true;
}

export function logout() {
  sessionStorage.removeItem(SESSION_KEY);
}

export function getSession() {
  try {
    return JSON.parse(sessionStorage.getItem(SESSION_KEY));
  } catch {
    return null;
  }
}

export function isAuthenticated() {
  return getSession() !== null;
}
