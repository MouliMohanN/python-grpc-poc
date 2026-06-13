import logging
from contextlib import asynccontextmanager

import grpc
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from gen import notes_pb2, products_pb2
from grpc_clients_v2 import close_clients, init_clients, verify_via_reflection
import grpc_clients_v2 as grpc_clients

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_clients()
    await verify_via_reflection()
    yield
    await close_clients()


app = FastAPI(title="gRPC POC Gateway", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- request / response models ----------

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
    resp = await grpc_clients.notes_stub.CreateNote(
        notes_pb2.CreateNoteRequest(title=req.title, body=req.body)
    )
    return {"id": resp.id}


@app.get("/notes/{note_id}")
async def get_note(note_id: str):
    try:
        note = await grpc_clients.notes_stub.GetNote(
            notes_pb2.GetNoteRequest(id=note_id)
        )
        return {"id": note.id, "title": note.title, "body": note.body}
    except grpc.aio.AioRpcError as e:
        if e.code() == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail=str(e.details()))
        raise HTTPException(status_code=500, detail=str(e.details()))


@app.get("/notes")
async def list_notes():
    notes = []
    async for note in grpc_clients.notes_stub.StreamNotes(notes_pb2.StreamNotesRequest()):
        notes.append({"id": note.id, "title": note.title, "body": note.body})
    return notes


# ---------- products routes ----------

@app.post("/products", status_code=201)
async def create_product(req: CreateProductRequest):
    resp = await grpc_clients.products_stub.CreateProduct(
        products_pb2.CreateProductRequest(name=req.name, category=req.category, price=req.price)
    )
    return {"id": resp.id}


@app.get("/products/{product_id}")
async def get_product(product_id: str):
    try:
        product = await grpc_clients.products_stub.GetProduct(
            products_pb2.GetProductRequest(id=product_id)
        )
        return {"id": product.id, "name": product.name, "category": product.category, "price": product.price}
    except grpc.aio.AioRpcError as e:
        if e.code() == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail=str(e.details()))
        raise HTTPException(status_code=500, detail=str(e.details()))


@app.get("/products")
async def list_products(category: str = ""):
    products = []
    async for p in grpc_clients.products_stub.StreamProducts(
        products_pb2.StreamProductsRequest(category=category)
    ):
        products.append({"id": p.id, "name": p.name, "category": p.category, "price": p.price})
    return products
