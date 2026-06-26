# Deployment Guide

AutoWeave Library is designed to be embedded into applications, but it requires several backing services to operate reliably in a production or local development environment.

## Backing Services

To run AutoWeave, you must provision:
1. **PostgreSQL** (with pgvector extension) - Canonical state and vector search.
2. **Redis** - Celery broker, distributed locks, heartbeats.
3. **Neo4j** (Optional) - For complex graph queries and memory associations.
4. **Artifact Storage** - A filesystem volume, AWS S3, or GCS for binary artifacts.
5. **OpenHands Agent Server** - The remote worker execution environment.

## Docker Compose (Local & Testing)

For local development, we provide a `docker-compose.yml` file that provisions the entire stack.

```bash
docker compose up -d
```

This stack includes:
- `redis:7.4-alpine`
- `artifact-store` (Alpine container mapping `./var/artifacts` to `/data`)
- `autoweave-runtime` (The library CLI/runner)
- `openhands-agent-server`

## Production Deployment Considerations

When deploying AutoWeave to a production environment (e.g., Kubernetes), consider the following:

### 1. Worker Isolation (Sandboxing)
AutoWeave delegates execution to OpenHands. OpenHands must run in a secure, isolated sandbox environment (e.g., Docker-in-Docker or gVisor) because it executes AI-generated code. Do not run OpenHands as root on the host machine.

### 2. High Availability
- **PostgreSQL**: Deploy in a highly available configuration (e.g., AWS RDS Multi-AZ, Cloud SQL HA).
- **Redis**: Use Redis Sentinel or a managed service (e.g., AWS ElastiCache) for failover.
- **AutoWeave Orchestrator**: The library is stateless and can be scaled horizontally.

### 3. Scaling Celery Workers
Task attempts are queued via Celery. To increase throughput:
- Increase the number of Celery worker processes.
- Ensure the Redis broker has sufficient connection limits and memory.

### 4. Storage Scaling
- Artifacts should be stored in cloud object storage (S3/GCS) rather than a local disk volume to ensure they are accessible across all nodes. Update `ARTIFACT_STORE_URL` accordingly.

### 5. Secrets Management
- Do not hardcode credentials in `.env` files for production.
- Inject `VERTEXAI_SERVICE_ACCOUNT_FILE`, `POSTGRES_URL`, and other secrets via a secrets manager (e.g., HashiCorp Vault, AWS Secrets Manager, Kubernetes Secrets).
