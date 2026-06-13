package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"time"

	pb "github.com/moulimohann/grpc-poc/go-server/gen"
	"github.com/redis/go-redis/v9"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	_ "github.com/lib/pq"
)

const (
	dsn      = "host=localhost port=5432 user=grpc password=grpc dbname=grpcpoc sslmode=disable"
	redisAddr = "localhost:6379"
	cacheTTL  = 60 * time.Second
)

type server struct {
	pb.UnimplementedProductsServiceServer
	db  *sql.DB
	rdb *redis.Client
}

func newServer() *server {
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		log.Fatalf("postgres connect: %v", err)
	}
	if err := db.Ping(); err != nil {
		log.Fatalf("postgres ping: %v", err)
	}

	rdb := redis.NewClient(&redis.Options{Addr: redisAddr})
	if _, err := rdb.Ping(context.Background()).Result(); err != nil {
		log.Fatalf("redis ping: %v", err)
	}

	log.Println("Connected to Postgres and Redis")
	return &server{db: db, rdb: rdb}
}

func (s *server) close() {
	s.db.Close()
	s.rdb.Close()
}

func registerProductsServer(g *grpc.Server, s *server) {
	pb.RegisterProductsServiceServer(g, s)
}

func (s *server) CreateProduct(ctx context.Context, req *pb.CreateProductRequest) (*pb.CreateProductResponse, error) {
	var id string
	err := s.db.QueryRowContext(ctx,
		`INSERT INTO products (name, category, price) VALUES ($1, $2, $3) RETURNING id`,
		req.Name, req.Category, req.Price,
	).Scan(&id)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "insert failed: %v", err)
	}
	log.Printf("CreateProduct: id=%s name=%s", id, req.Name)
	return &pb.CreateProductResponse{Id: id}, nil
}

func (s *server) GetProduct(ctx context.Context, req *pb.GetProductRequest) (*pb.Product, error) {
	cacheKey := fmt.Sprintf("product:%s", req.Id)

	cached, err := s.rdb.Get(ctx, cacheKey).Result()
	if err == nil {
		var p pb.Product
		if json.Unmarshal([]byte(cached), &p) == nil {
			log.Printf("GetProduct cache HIT: id=%s", req.Id)
			return &p, nil
		}
	}

	var p pb.Product
	err = s.db.QueryRowContext(ctx,
		`SELECT id, name, category, price FROM products WHERE id=$1`, req.Id,
	).Scan(&p.Id, &p.Name, &p.Category, &p.Price)
	if err == sql.ErrNoRows {
		return nil, status.Errorf(codes.NotFound, "product %s not found", req.Id)
	}
	if err != nil {
		return nil, status.Errorf(codes.Internal, "query failed: %v", err)
	}

	log.Printf("GetProduct cache MISS: id=%s", req.Id)
	if b, err := json.Marshal(&p); err == nil {
		s.rdb.Set(ctx, cacheKey, b, cacheTTL)
	}
	return &p, nil
}

func (s *server) StreamProducts(req *pb.StreamProductsRequest, stream pb.ProductsService_StreamProductsServer) error {
	var (
		rows *sql.Rows
		err  error
	)
	if req.Category != "" {
		rows, err = s.db.QueryContext(stream.Context(),
			`SELECT id, name, category, price FROM products WHERE category=$1`, req.Category)
	} else {
		rows, err = s.db.QueryContext(stream.Context(),
			`SELECT id, name, category, price FROM products`)
	}
	if err != nil {
		return status.Errorf(codes.Internal, "query failed: %v", err)
	}
	defer rows.Close()

	for rows.Next() {
		var p pb.Product
		if err := rows.Scan(&p.Id, &p.Name, &p.Category, &p.Price); err != nil {
			return status.Errorf(codes.Internal, "scan failed: %v", err)
		}
		if err := stream.Send(&p); err != nil {
			return err
		}
	}
	return rows.Err()
}
