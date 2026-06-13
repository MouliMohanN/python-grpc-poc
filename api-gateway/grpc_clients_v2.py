"""
grpc_clients_v2.py — generated stubs + reflection-based startup verification

Differences from grpc_clients.py:
- Server addresses read from env vars (NOTES_SERVICE_ADDRESS, PRODUCTS_SERVICE_ADDRESS)
  so no code change is needed when deploying to Docker Compose or Kubernetes.
- verify_via_reflection() queries both servers via the gRPC reflection protocol on
  startup, logging which services they expose. The actual RPC calls still go through
  the generated stubs — reflection is used only for validation and observability.

To use this version instead of grpc_clients.py, swap the import in main.py:
    import grpc_clients_v2 as grpc_clients
"""

import logging
import os

import grpc
import grpc.aio
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

from gen import notes_pb2_grpc, products_pb2_grpc

log = logging.getLogger(__name__)

NOTES_ADDRESS    = os.environ.get("NOTES_SERVICE_ADDRESS", "localhost:50052")
PRODUCTS_ADDRESS = os.environ.get("PRODUCTS_SERVICE_ADDRESS", "localhost:50051")

_notes_channel    = None
_products_channel = None
notes_stub    = None
products_stub = None


def init_clients():
    global _notes_channel, _products_channel, notes_stub, products_stub
    _notes_channel    = grpc.aio.insecure_channel(NOTES_ADDRESS)
    _products_channel = grpc.aio.insecure_channel(PRODUCTS_ADDRESS)
    notes_stub    = notes_pb2_grpc.NotesServiceStub(_notes_channel)
    products_stub = products_pb2_grpc.ProductsServiceStub(_products_channel)
    log.info("gRPC channels opened — notes=%s products=%s", NOTES_ADDRESS, PRODUCTS_ADDRESS)


async def _list_services(channel) -> list[str]:
    """Query the reflection service on a channel and return non-reflection service names."""
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)

    async def _requests():
        yield reflection_pb2.ServerReflectionRequest(list_services="")

    names = []
    async for resp in stub.ServerReflectionInfo(_requests()):
        if resp.HasField("list_services_response"):
            for svc in resp.list_services_response.service:
                if svc.name != "grpc.reflection.v1alpha.ServerReflection":
                    names.append(svc.name)
    return names


async def verify_via_reflection():
    """
    Query reflection on both servers at startup. Logs discovered services.
    Does not affect routing — stubs created in init_clients() handle all RPCs.
    """
    notes_svcs    = await _list_services(_notes_channel)
    products_svcs = await _list_services(_products_channel)
    log.info("reflection — notes    @ %s → %s", NOTES_ADDRESS,    notes_svcs)
    log.info("reflection — products @ %s → %s", PRODUCTS_ADDRESS, products_svcs)


async def close_clients():
    if _notes_channel:
        await _notes_channel.close()
    if _products_channel:
        await _products_channel.close()
