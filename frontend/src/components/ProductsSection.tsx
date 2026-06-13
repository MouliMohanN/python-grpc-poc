import { useState } from "react";
import { api } from "../api";
import type { Product } from "../api";

export function ProductsSection() {
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [price, setPrice] = useState("");
  const [fetchId, setFetchId] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [product, setProduct] = useState<Product | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
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
      <h2>Products <span style={styles.badge}>Go gRPC :50051</span></h2>

      <fieldset style={styles.fieldset}>
        <legend>Create product</legend>
        <input
          style={styles.input}
          placeholder="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          style={styles.input}
          placeholder="Category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        />
        <input
          style={{ ...styles.input, width: 100 }}
          placeholder="Price"
          type="number"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
        />
        <button
          style={styles.btn}
          onClick={() => wrap(async () => {
            const res = await api.products.create(name, category, parseFloat(price));
            setCreatedId(res.id);
            setName(""); setCategory(""); setPrice("");
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
          placeholder="Product ID"
          value={fetchId}
          onChange={(e) => setFetchId(e.target.value)}
        />
        <button
          style={styles.btn}
          onClick={() => wrap(async () => {
            setProduct(await api.products.get(fetchId));
          })}
        >
          Fetch
        </button>
        {product && (
          <table style={styles.table}>
            <tbody>
              <tr><td><b>ID</b></td><td>{product.id}</td></tr>
              <tr><td><b>Name</b></td><td>{product.name}</td></tr>
              <tr><td><b>Category</b></td><td>{product.category}</td></tr>
              <tr><td><b>Price</b></td><td>${product.price}</td></tr>
            </tbody>
          </table>
        )}
      </fieldset>

      <fieldset style={styles.fieldset}>
        <legend>All products (streaming)</legend>
        <input
          style={styles.input}
          placeholder="Filter by category (optional)"
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value)}
        />
        <button
          style={styles.btn}
          onClick={() => wrap(async () => setProducts(await api.products.list(filterCategory || undefined)))}
        >
          Load all
        </button>
        {products.length > 0 && (
          <table style={styles.table}>
            <thead>
              <tr><th>ID</th><th>Name</th><th>Category</th><th>Price</th></tr>
            </thead>
            <tbody>
              {products.map((p) => (
                <tr key={p.id}>
                  <td style={styles.idCell}>{p.id}</td>
                  <td>{p.name}</td>
                  <td>{p.category}</td>
                  <td>${p.price}</td>
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
  section: { background: "#f0fff4", borderRadius: 8, padding: 20, marginBottom: 24 },
  badge: { fontSize: 12, background: "#16a34a", color: "#fff", borderRadius: 4, padding: "2px 6px", marginLeft: 8 },
  fieldset: { border: "1px solid #bbf7d0", borderRadius: 6, padding: 12, marginBottom: 12 },
  input: { marginRight: 8, marginBottom: 6, padding: "6px 10px", borderRadius: 4, border: "1px solid #86efac", width: 200 },
  btn: { padding: "6px 14px", borderRadius: 4, background: "#16a34a", color: "#fff", border: "none", cursor: "pointer" },
  success: { color: "#16a34a", fontFamily: "monospace", fontSize: 13 },
  error: { color: "#dc2626", marginTop: 8 },
  table: { borderCollapse: "collapse", marginTop: 8, width: "100%", fontSize: 13 },
  idCell: { fontFamily: "monospace", fontSize: 11, color: "#6b7280" },
};
