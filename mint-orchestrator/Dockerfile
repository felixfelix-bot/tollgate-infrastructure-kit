FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY protos/ protos/
COPY src/ src/

RUN pip install --no-cache-dir grpcio-tools

RUN python -m grpc_tools.protoc \
    -I protos \
    --python_out=src/tollgate_mint_orchestrator \
    --grpc_python_out=src/tollgate_mint_orchestrator \
    protos/cdk-mint-rpc.proto

RUN sed -i 's/^import cdk_mint_rpc_pb2 as/from tollgate_mint_orchestrator import cdk_mint_rpc_pb2 as/' \
    src/tollgate_mint_orchestrator/cdk_mint_rpc_pb2_grpc.py

RUN pip install --no-cache-dir .

EXPOSE 8090

CMD ["tollgate-mint-orchestrator"]