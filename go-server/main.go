package main

import (
	"log"
	"net"

	"google.golang.org/grpc"
	"google.golang.org/grpc/reflection"
)

func main() {
	lis, err := net.Listen("tcp", ":50051")
	if err != nil {
		log.Fatalf("failed to listen: %v", err)
	}

	srv := newServer()
	defer srv.close()

	grpcServer := grpc.NewServer()
	registerProductsServer(grpcServer, srv)
	reflection.Register(grpcServer)

	log.Println("ProductsService listening on :50051")
	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("failed to serve: %v", err)
	}
}
