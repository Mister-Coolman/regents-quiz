// Past chats, kept in this browser. The server can't hold them: its session
// tables are wiped on every deploy. Each practice set carries a signed
// set_token, so a chat reopened here can still check answers.
//
//   regentsChats       [{ id, title, updatedAt }], newest first
//   regentsChat:<id>   that chat's messages

const INDEX = 'regentsChats';
const chatKey = id => `regentsChat:${id}`;
const MAX_CHATS = 100;
const TITLE_CHARS = 60;

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

export function listChats() {
  const list = read(INDEX, []);
  return Array.isArray(list) ? list : [];
}

export function loadChat(id) {
  const messages = read(chatKey(id), null);
  return Array.isArray(messages) ? messages : null;
}

function titleFor(messages) {
  const first = messages.find(m => m.sender === 'student')?.text || 'New chat';
  return first.length > TITLE_CHARS ? `${first.slice(0, TITLE_CHARS - 1).trimEnd()}…` : first;
}

/** Save a chat and move it to the top of the list. A chat with nothing asked
 *  yet isn't listed. Returns the updated list. */
export function saveChat(id, messages) {
  const kept = messages.filter(m => !m.typing && m.key !== 'greeting');
  if (!id || !kept.some(m => m.sender === 'student')) return listChats();
  const entry = { id, title: titleFor(kept), updatedAt: Date.now() };
  let list = [entry, ...listChats().filter(c => c.id !== id)];
  // Oldest chats go first when the list is long or storage is full
  // (passages make ELA chats tens of kilobytes each).
  for (const old of list.slice(MAX_CHATS)) {
    try { localStorage.removeItem(chatKey(old.id)); } catch { /* ignore */ }
  }
  list = list.slice(0, MAX_CHATS);
  for (;;) {
    try {
      localStorage.setItem(chatKey(id), JSON.stringify(kept));
      localStorage.setItem(INDEX, JSON.stringify(list));
      return list;
    } catch {
      const victim = list.length > 1 ? list[list.length - 1] : null;
      if (!victim || victim.id === id) return list;   // can't make room; keep what's there
      list = list.slice(0, -1);
      try { localStorage.removeItem(chatKey(victim.id)); } catch { /* ignore */ }
    }
  }
}

export function deleteChat(id) {
  const list = listChats().filter(c => c.id !== id);
  try {
    localStorage.removeItem(chatKey(id));
    localStorage.setItem(INDEX, JSON.stringify(list));
  } catch { /* ignore */ }
  return list;
}

/** Put a deleted chat back (undo). */
export function restoreChat(entry, messages) {
  try {
    localStorage.setItem(chatKey(entry.id), JSON.stringify(messages));
  } catch { /* ignore */ }
  const list = [entry, ...listChats().filter(c => c.id !== entry.id)]
    .sort((a, b) => b.updatedAt - a.updatedAt);
  try { localStorage.setItem(INDEX, JSON.stringify(list)); } catch { /* ignore */ }
  return list;
}
