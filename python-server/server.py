import json
import logging
import uuid
from concurrent import futures

import grpc
import psycopg
import redis
from grpc_reflection.v1alpha import reflection

from gen import notes_pb2, notes_pb2_grpc

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

DSN = "host=localhost port=5432 user=grpc password=grpc dbname=grpcpoc"
REDIS_HOST = "localhost"
CACHE_TTL = 60


class NotesServicer(notes_pb2_grpc.NotesServiceServicer):
    def __init__(self):
        self.conn = psycopg.connect(DSN)
        self.rdb = redis.Redis(host=REDIS_HOST, decode_responses=True)
        log.info("Connected to Postgres and Redis")

    def CreateNote(self, request, context):
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notes (title, body) VALUES (%s, %s) RETURNING id",
                (request.title, request.body),
            )
            note_id = str(cur.fetchone()[0])
            self.conn.commit()
        log.info("CreateNote: id=%s title=%s", note_id, request.title)
        return notes_pb2.CreateNoteResponse(id=note_id)

    def GetNote(self, request, context):
        cache_key = f"note:{request.id}"
        cached = self.rdb.get(cache_key)
        if cached:
            log.info("GetNote cache HIT: id=%s", request.id)
            data = json.loads(cached)
            return notes_pb2.Note(**data)

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, body FROM notes WHERE id=%s", (request.id,)
            )
            row = cur.fetchone()

        if not row:
            context.abort(grpc.StatusCode.NOT_FOUND, f"note {request.id} not found")

        note = notes_pb2.Note(id=str(row[0]), title=row[1], body=row[2])
        log.info("GetNote cache MISS: id=%s", request.id)
        self.rdb.set(cache_key, json.dumps({"id": note.id, "title": note.title, "body": note.body}), ex=CACHE_TTL)
        return note

    def StreamNotes(self, request, context):
        with self.conn.cursor() as cur:
            cur.execute("SELECT id, title, body FROM notes")
            for row in cur.fetchall():
                yield notes_pb2.Note(id=str(row[0]), title=row[1], body=row[2])


def serve():
    servicer = NotesServicer()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    notes_pb2_grpc.add_NotesServiceServicer_to_server(servicer, server)
    reflection.enable_server_reflection(
        [notes_pb2.DESCRIPTOR.services_by_name["NotesService"].full_name, reflection.SERVICE_NAME],
        server,
    )
    server.add_insecure_port("[::]:50052")
    server.start()
    log.info("NotesService listening on :50052")
    server.wait_for_termination()
