import { NotesSection } from "./components/NotesSection";
import { ProductsSection } from "./components/ProductsSection";

export default function App() {
  return (
    <div style={{ maxWidth: 900, margin: "40px auto", padding: "0 20px", fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ borderBottom: "2px solid #e5e7eb", paddingBottom: 12, marginBottom: 24 }}>
        gRPC POC Dashboard
      </h1>
      <p style={{ color: "#6b7280", marginBottom: 28, fontSize: 14 }}>
        React → REST → FastAPI gateway → gRPC → Go server (Products) / Python server (Notes)
      </p>
      <ProductsSection />
      <NotesSection />
    </div>
  );
}
