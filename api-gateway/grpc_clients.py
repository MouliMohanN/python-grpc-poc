import grpc
from gen import notes_pb2_grpc, products_pb2_grpc

_notes_channel = None
_products_channel = None
notes_stub = None
products_stub = None


def init_clients():
    global _notes_channel, _products_channel, notes_stub, products_stub
    _notes_channel = grpc.aio.insecure_channel("localhost:50052")
    _products_channel = grpc.aio.insecure_channel("localhost:50051")
    notes_stub = notes_pb2_grpc.NotesServiceStub(_notes_channel)
    products_stub = products_pb2_grpc.ProductsServiceStub(_products_channel)


async def close_clients():
    if _notes_channel:
        await _notes_channel.close()
    if _products_channel:
        await _products_channel.close()
