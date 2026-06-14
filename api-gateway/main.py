import logging
from contextlib import asynccontextmanager

import grpc
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import grpc_clients_v2 as grpc_clients

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await grpc_clients.init_clients()
    yield
    await grpc_clients.close_clients()


app = FastAPI(title="gRPC POC Gateway", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- request models ----------

class CreateNoteRequest(BaseModel):
    title: str
    body: str


class CreateProductRequest(BaseModel):
    name: str
    category: str
    price: float


# ---------- notes routes ----------

@app.post("/notes", status_code=201)
async def create_note(req: CreateNoteRequest):
    return await grpc_clients.call_unary(
        "notes", "notes.NotesService", "CreateNote",
        {"title": req.title, "body": req.body},
    )


@app.get("/notes/{note_id}")
async def get_note(note_id: str):
    try:
        return await grpc_clients.call_unary(
            "notes", "notes.NotesService", "GetNote",
            {"id": note_id},
        )
    except grpc.aio.AioRpcError as e:
        if e.code() == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail=str(e.details()))
        raise HTTPException(status_code=500, detail=str(e.details()))


@app.get("/notes")
async def list_notes():
    notes = []
    async for note in grpc_clients.call_server_stream(
        "notes", "notes.NotesService", "StreamNotes", {}
    ):
        notes.append(note)
    return notes


@app.delete("/notes")
async def delete_all_notes():
    return await grpc_clients.call_unary(
        "notes", "notes.NotesService", "DeleteAllNotes", {}
    )


# ---------- products routes ----------

@app.post("/products", status_code=201)
async def create_product(req: CreateProductRequest):
    return await grpc_clients.call_unary(
        "products", "products.ProductsService", "CreateProduct",
        {"name": req.name, "category": req.category, "price": req.price},
    )


@app.get("/products/{product_id}")
async def get_product(product_id: str):
    try:
        return await grpc_clients.call_unary(
            "products", "products.ProductsService", "GetProduct",
            {"id": product_id},
        )
    except grpc.aio.AioRpcError as e:
        if e.code() == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail=str(e.details()))
        raise HTTPException(status_code=500, detail=str(e.details()))


@app.get("/products")
async def list_products(category: str = ""):
    products = []
    async for p in grpc_clients.call_server_stream(
        "products", "products.ProductsService", "StreamProducts",
        {"category": category},
    ):
        products.append(p)
    return products
