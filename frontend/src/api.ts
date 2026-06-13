const BASE = "http://localhost:8000";

export interface Note {
  id: string;
  title: string;
  body: string;
}

export interface Product {
  id: string;
  name: string;
  category: string;
  price: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? res.statusText);
  }
  return res.json();
}

export const api = {
  notes: {
    create: (title: string, body: string) =>
      request<{ id: string }>("/notes", {
        method: "POST",
        body: JSON.stringify({ title, body }),
      }),
    get: (id: string) => request<Note>(`/notes/${id}`),
    list: () => request<Note[]>("/notes"),
  },
  products: {
    create: (name: string, category: string, price: number) =>
      request<{ id: string }>("/products", {
        method: "POST",
        body: JSON.stringify({ name, category, price }),
      }),
    get: (id: string) => request<Product>(`/products/${id}`),
    list: (category?: string) =>
      request<Product[]>(`/products${category ? `?category=${category}` : ""}`),
  },
};
