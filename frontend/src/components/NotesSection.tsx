import { useState } from "react";
import { api } from "../api";
import type { Note } from "../api";

export function NotesSection() {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [fetchId, setFetchId] = useState("");
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [error, setError] = useState<string | null>(null);

  const wrap = async (fn: () => Promise<void>) => {
    setError(null);
    try {
      await fn();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section style={styles.section}>
      <h2>Notes <span style={styles.badge}>Python gRPC :50052</span></h2>

      <fieldset style={styles.fieldset}>
        <legend>Create note</legend>
        <input
          style={styles.input}
          placeholder="Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <input
          style={styles.input}
          placeholder="Body"
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        <button
          style={styles.btn}
          onClick={() => wrap(async () => {
            const res = await api.notes.create(title, body);
            setCreatedId(res.id);
            setTitle("");
            setBody("");
          })}
        >
          Create
        </button>
        {createdId && <p style={styles.success}>Created ID: {createdId}</p>}
      </fieldset>

      <fieldset style={styles.fieldset}>
        <legend>Fetch by ID</legend>
        <input
          style={styles.input}
          placeholder="Note ID"
          value={fetchId}
          onChange={(e) => setFetchId(e.target.value)}
        />
        <button
          style={styles.btn}
          onClick={() => wrap(async () => {
            setNote(await api.notes.get(fetchId));
          })}
        >
          Fetch
        </button>
        {note && (
          <table style={styles.table}>
            <tbody>
              <tr><td><b>ID</b></td><td>{note.id}</td></tr>
              <tr><td><b>Title</b></td><td>{note.title}</td></tr>
              <tr><td><b>Body</b></td><td>{note.body}</td></tr>
            </tbody>
          </table>
        )}
      </fieldset>

      <fieldset style={styles.fieldset}>
        <legend>All notes (streaming)</legend>
        <button
          style={styles.btn}
          onClick={() => wrap(async () => setNotes(await api.notes.list()))}
        >
          Load all
        </button>
        {notes.length > 0 && (
          <table style={styles.table}>
            <thead>
              <tr><th>ID</th><th>Title</th><th>Body</th></tr>
            </thead>
            <tbody>
              {notes.map((n) => (
                <tr key={n.id}>
                  <td style={styles.idCell}>{n.id}</td>
                  <td>{n.title}</td>
                  <td>{n.body}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </fieldset>

      {error && <p style={styles.error}>{error}</p>}
    </section>
  );
}

const styles: Record<string, React.CSSProperties> = {
  section: { background: "#f0f4ff", borderRadius: 8, padding: 20, marginBottom: 24 },
  badge: { fontSize: 12, background: "#3b82f6", color: "#fff", borderRadius: 4, padding: "2px 6px", marginLeft: 8 },
  fieldset: { border: "1px solid #c7d2fe", borderRadius: 6, padding: 12, marginBottom: 12 },
  input: { marginRight: 8, marginBottom: 6, padding: "6px 10px", borderRadius: 4, border: "1px solid #a5b4fc", width: 200 },
  btn: { padding: "6px 14px", borderRadius: 4, background: "#3b82f6", color: "#fff", border: "none", cursor: "pointer" },
  success: { color: "#16a34a", fontFamily: "monospace", fontSize: 13 },
  error: { color: "#dc2626", marginTop: 8 },
  table: { borderCollapse: "collapse", marginTop: 8, width: "100%", fontSize: 13 },
  idCell: { fontFamily: "monospace", fontSize: 11, color: "#6b7280" },
};
