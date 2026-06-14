"""
grpc_clients_v2.py — pure reflection-based dynamic client

No generated stubs. On startup, connects to each server, queries the gRPC
reflection API to fetch the full schema, and loads it into a DescriptorPool.
All RPC calls go through dynamically-built message classes derived from that pool.

gen_proto.sh does not need to run for the gateway when using this module.
The api-gateway/gen/ directory is not imported here.

Public API:
    await init_clients()             — call once in FastAPI lifespan startup
    await close_clients()            — call once in FastAPI lifespan shutdown
    await call_unary(...)            — make a unary RPC, returns dict
    call_server_stream(...)          — async generator for server-streaming RPCs
"""

import logging

import grpc
import grpc.aio
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.json_format import MessageToDict
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

log = logging.getLogger(__name__)

NOTES_ADDRESS    = "localhost:50052"
PRODUCTS_ADDRESS = "localhost:50051"

# { "notes": { "channel": ..., "pool": ..., "service_names": [...] }, ... }
_services: dict = {}


# ---------- reflection helpers ----------

async def _list_services(channel) -> list[str]:
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)

    async def _req():
        yield reflection_pb2.ServerReflectionRequest(list_services="")

    names = []
    async for resp in stub.ServerReflectionInfo(_req()):
        if resp.HasField("list_services_response"):
            for svc in resp.list_services_response.service:
                if svc.name != "grpc.reflection.v1alpha.ServerReflection":
                    names.append(svc.name)
    return names


async def _fetch_file_descriptors(channel, service_name: str) -> list[bytes]:
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)

    async def _req():
        yield reflection_pb2.ServerReflectionRequest(file_containing_symbol=service_name)

    fd_bytes_list = []
    async for resp in stub.ServerReflectionInfo(_req()):
        if resp.HasField("file_descriptor_response"):
            fd_bytes_list.extend(resp.file_descriptor_response.file_descriptor_proto)
    return fd_bytes_list


def _build_pool(all_fd_bytes: list[bytes]) -> descriptor_pool.DescriptorPool:
    pool = descriptor_pool.DescriptorPool()
    added = set()
    for fd_bytes in all_fd_bytes:
        fd = descriptor_pb2.FileDescriptorProto.FromString(fd_bytes)
        if fd.name not in added:
            pool.Add(fd)
            added.add(fd.name)
    return pool


# ---------- startup / shutdown ----------

async def _register(alias: str, address: str):
    channel = grpc.aio.insecure_channel(address)
    service_names = await _list_services(channel)

    all_fd_bytes: list[bytes] = []
    for svc_name in service_names:
        all_fd_bytes.extend(await _fetch_file_descriptors(channel, svc_name))

    pool = _build_pool(all_fd_bytes)

    _services[alias] = {
        "address":       address,
        "channel":       channel,
        "pool":          pool,
        "service_names": service_names,
    }
    log.info("registered %s @ %s → %s", alias, address, service_names)


async def init_clients():
    await _register("notes",    NOTES_ADDRESS)
    await _register("products", PRODUCTS_ADDRESS)


async def close_clients():
    for svc in _services.values():
        await svc["channel"].close()


# ---------- dynamic call helpers ----------

def _resolve_method(alias: str, service_name: str, method_name: str):
    pool    = _services[alias]["pool"]
    svc_desc = pool.FindServiceByName(service_name)
    mth_desc = svc_desc.FindMethodByName(method_name)
    ReqClass  = message_factory.GetMessageClass(mth_desc.input_type)
    RespClass = message_factory.GetMessageClass(mth_desc.output_type)
    return mth_desc, ReqClass, RespClass


async def call_unary(alias: str, service_name: str, method_name: str, data: dict) -> dict:
    mth_desc, ReqClass, RespClass = _resolve_method(alias, service_name, method_name)
    channel = _services[alias]["channel"]

    rpc = channel.unary_unary(
        f"/{service_name}/{method_name}",
        request_serializer=ReqClass.SerializeToString,
        response_deserializer=RespClass.FromString,
    )
    response = await rpc(ReqClass(**data))
    return MessageToDict(response, preserving_proto_field_name=True,
                         including_default_value_fields=True)


async def call_server_stream(alias: str, service_name: str, method_name: str, data: dict):
    mth_desc, ReqClass, RespClass = _resolve_method(alias, service_name, method_name)
    channel = _services[alias]["channel"]

    rpc = channel.unary_stream(
        f"/{service_name}/{method_name}",
        request_serializer=ReqClass.SerializeToString,
        response_deserializer=RespClass.FromString,
    )
    async for response in rpc(ReqClass(**data)):
        yield MessageToDict(response, preserving_proto_field_name=True,
                            including_default_value_fields=True)
