import React, { useEffect, useRef } from 'react';
import styles from '../styles/ChatHistory.module.css';

const DAY = 24 * 60 * 60 * 1000;

function groupChats(chats, now = Date.now()) {
  const startOfToday = new Date(now).setHours(0, 0, 0, 0);
  const groups = [
    { label: 'Today', items: [] },
    { label: 'Previous 7 days', items: [] },
    { label: 'Older', items: [] },
  ];
  for (const c of chats) {
    if (c.updatedAt >= startOfToday) groups[0].items.push(c);
    else if (c.updatedAt >= startOfToday - 7 * DAY) groups[1].items.push(c);
    else groups[2].items.push(c);
  }
  return groups.filter(g => g.items.length);
}

/**
 * Past chats in a panel that slides in from the left. A modal dialog:
 * focus moves into it, Escape or the backdrop closes it, and focus returns
 * to the button that opened it.
 */
export default function ChatHistory({ open, chats, currentId, busy, onOpen, onDelete, onNewChat, onClose }) {
  const panelRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const opener = document.activeElement;
    panelRef.current?.querySelector('button')?.focus();
    const onKey = e => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'Tab') {
        // Keep Tab inside the panel while it's open.
        const items = [...panelRef.current.querySelectorAll('button:not(:disabled)')];
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      opener?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className={styles.overlay}>
      <div className={styles.backdrop} onClick={onClose} aria-hidden="true" />
      <aside
        className={styles.panel}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="chat-history-title"
      >
        <div className={styles.header}>
          <h2 id="chat-history-title" className={styles.title}>Chats</h2>
          <button type="button" className={styles.close} onClick={onClose}>
            Close
          </button>
        </div>
        <button type="button" className={styles.newChat} onClick={onNewChat} disabled={busy}>
          New chat
        </button>

        {chats.length === 0 ? (
          <p className={styles.empty}>Chats you start are saved here, on this device.</p>
        ) : (
          groupChats(chats).map(group => (
            <section key={group.label} className={styles.group}>
              <h3 className={styles.groupLabel}>{group.label}</h3>
              <ul className={styles.list}>
                {group.items.map(chat => (
                  <li key={chat.id} className={styles.item} data-current={chat.id === currentId ? 'true' : undefined}>
                    <button
                      type="button"
                      className={styles.open}
                      onClick={() => onOpen(chat.id)}
                      disabled={busy}
                      aria-current={chat.id === currentId ? 'true' : undefined}
                    >
                      {chat.title}
                    </button>
                    <button
                      type="button"
                      className={styles.delete}
                      onClick={() => onDelete(chat.id)}
                      disabled={busy}
                    >
                      Delete<span className="sr-only"> chat: {chat.title}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))
        )}
        <p className={styles.note}>Saved in this browser only. Clearing site data removes them.</p>
      </aside>
    </div>
  );
}
