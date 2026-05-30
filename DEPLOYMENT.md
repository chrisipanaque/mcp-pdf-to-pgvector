# Deployment Guide: Customer Support AI Agent on AWS

## Architecture Overview

```
                           ┌──────────────────────────────┐
                           │     CloudFront / Route 53     │
                           └──────────────┬───────────────┘
                                          │
                           ┌──────────────▼───────────────┐
                           │     Application Load Balancer │
                           │     (HTTPS, ACM certificate)  │
                           └──────────────┬───────────────┘
                                          │
                     ┌────────────────────┼────────────────────┐
                     │                    │                    │
              ┌──────▼──────┐     ┌───────▼───────┐     ┌─────▼──────┐
              │  ECS Fargate │     │  ECS Fargate  │     │ ECS Fargate│
              │   (API +     │     │   (API +      │     │  (API +    │
              │   LangGraph) │     │   LangGraph)  │     │ LangGraph) │
              │   (az-a)     │     │   (az-b)      │     │  (az-c)    │
              └──────┬───────┘     └───────┬───────┘     └─────┬──────┘
                     │                    │                    │
                     └────────────────────┼────────────────────┘
                                          │
              ┌───────────────────────────▼───────────────────────────┐
              │            RDS Aurora PostgreSQL (pgvector)            │
              │             Writer + 2 Readers (Multi-AZ)              │
              │     Automated backups, point-in-time recovery          │
              └───────────────────────────────────────────────────────┘
                                          │
              ┌───────────────────────────▼───────────────────────────┐
              │         ElastiCache Redis (optional, recommended)      │
              │    - Embedding cache (TTL: 24h)                        │
              │    - Rate limiting token buckets                       │
              │    - Webhook delivery queue                            │
              └───────────────────────────────────────────────────────┘

VPC Layout:
┌──────────────────────────────────────────────────────────────────┐
│                         VPC (10.0.0.0/16)                        │
│                                                                  │
│  ┌─────────────────────┐  ┌─────────────────────┐               │
│  │  Public Subnets     │  │  Private Subnets     │               │
│  │  (3 AZs)            │  │  (3 AZs)             │               │
│  │                     │  │                      │               │
│  │  • ALB              │  │  • ECS Fargate tasks │               │
│  │  • NAT Gateway      │  │  • RDS Aurora        │               │
│  │                     │  │  • ElastiCache Redis │               │
│  └─────────────────────┘  └──────────────────────┘               │
│                                                                  │
│  VPC Endpoints (PrivateLink):                                    │
│  • com.amazonaws.region.ecr.dkr                                 │
│  • com.amazonaws.region.ecr.api                                 │
│  • com.amazonaws.region.secretsmanager                          │
│  • com.amazonaws.region.logs                                    │
└──────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

- **AWS CLI** installed and configured (`aws configure`)
- **Docker** installed
- **OpenAI API key** (with billing enabled)
- **Domain name** (optional, for HTTPS via ACM)
- **PostgreSQL 15+** compatible client (for pgvector verification)

---

## Step 1: RDS Aurora PostgreSQL with pgvector

Aurora PostgreSQL 15+ supports pgvector natively. Use Serverless v2 for automatic scaling.

### Create the cluster

**Option A: AWS CLI**

```bash
aws rds create-db-cluster \
  --db-cluster-identifier support-agent-db \
  --engine aurora-postgresql \
  --engine-version 15.5 \
  --serverless-v2-scaling-configuration MinCapacity=1,MaxCapacity=4 \
  --master-username support_user \
  --manage-master-user-password \
  --db-subnet-group-name my-private-subnet-group \
  --vpc-security-group-ids sg-xxxxxxxx \
  --backup-retention-period 7 \
  --storage-encrypted

aws rds create-db-instance \
  --db-instance-identifier support-agent-db-writer \
  --db-cluster-identifier support-agent-db \
  --db-instance-class db.serverless \
  --engine aurora-postgresql
```

**Option B: CloudFormation** (see Appendix A for full template)

```yaml
Resources:
  RDSCluster:
    Type: AWS::RDS::DBCluster
    Properties:
      Engine: aurora-postgresql
      EngineVersion: "15.5"
      ServerlessV2ScalingConfiguration:
        MinCapacity: 1
        MaxCapacity: 4
      MasterUsername: support_user
      ManageMasterUserPassword: true
      DBSubnetGroupName: !Ref DBSubnetGroup
      VpcSecurityGroupIds: [!Ref DBSecurityGroup]
      BackupRetentionPeriod: 7
      StorageEncrypted: true
```

### Enable pgvector

Connect to the database and run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

If the extension fails to create, ensure the DB parameter group has `shared_preload_libraries` including `pgvector`:

```sql
-- Verify
SELECT * FROM pg_available_extensions WHERE name = 'vector';
```

### Connection string

```
postgresql+asyncpg://support_user:{password}@{writer-endpoint}:5432/support_db
postgresql://support_user:{password}@{writer-endpoint}:5432/support_db    (for Alembic)
```

Store the writer endpoint in Secrets Manager (see Step 3).

---

## Step 2: ECR — Push Docker Image

### Create repository

```bash
aws ecr create-repository --repository-name support-agent-api --image-tag-mutability MUTABLE
```

### Build and push

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
ECR_URI=$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/support-agent-api

aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ECR_URI

docker build -t support-agent-api:latest .
docker tag support-agent-api:latest $ECR_URI:latest
docker push $ECR_URI:latest
```

### Multi-environment tagging

```bash
docker tag support-agent-api:latest $ECR_URI:prod-$(git rev-parse --short HEAD)
docker push $ECR_URI:prod-$(git rev-parse --short HEAD)
```

---

## Step 3: Secrets Manager — Store Credentials

Never hardcode secrets. Use AWS Secrets Manager.

```bash
aws secretsmanager create-secret \
  --name support-agent/db-credentials \
  --secret-string '{"password":"auto-generated-by-RDS"}'

aws secretsmanager create-secret \
  --name support-agent/openai \
  --secret-string '{"api-key":"sk-..."}'

aws secretsmanager create-secret \
  --name support-agent/config \
  --secret-string '{
    "DATABASE_URL":"postgresql+asyncpg://support_user:{password}@{writer-endpoint}:5432/support_db",
    "DATABASE_URL_SYNC":"postgresql://support_user:{password}@{writer-endpoint}:5432/support_db",
    "OPENAI_MODEL":"gpt-4o-mini",
    "EMBEDDING_MODEL":"text-embedding-3-small",
    "CHUNK_SIZE":"800",
    "CHUNK_OVERLAP":"150",
    "TOP_K":"8",
    "LOG_LEVEL":"INFO"
  }'
```

The ECS task definition will reference these secrets — they are injected as environment variables at runtime, never stored in the container image.

---

## Step 4: ECS Fargate — Deploy the API

### Task Definition

```json
{
  "family": "support-agent-api",
  "taskRoleArn": "arn:aws:iam::ACCOUNT_ID:role/ecsTaskRole",
  "executionRoleArn": "arn:aws:iam::ACCOUNT_ID:role/ecsTaskExecutionRole",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "containerDefinitions": [
    {
      "name": "api",
      "image": "ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/support-agent-api:latest",
      "portMappings": [{ "containerPort": 8000, "protocol": "tcp" }],
      "environment": [
        { "name": "LOG_LEVEL", "value": "INFO" }
      ],
      "secrets": [
        {
          "name": "OPENAI_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:support-agent/openai-xxxxx:api-key::"
        },
        {
          "name": "DATABASE_URL",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:support-agent/config-xxxxx:DATABASE_URL::"
        },
        {
          "name": "DATABASE_URL_SYNC",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:support-agent/config-xxxxx:DATABASE_URL_SYNC::"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/support-agent-api",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      },
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"],
        "interval": 10,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 30
      }
    }
  ]
}
```

Register the task definition:

```bash
aws ecs register-task-definition --cli-input-json file://task-definition.json
```

### ECS Cluster and Service

```bash
aws ecs create-cluster --cluster-name support-agent

aws ecs create-service \
  --cluster support-agent \
  --service-name api \
  --task-definition support-agent-api:1 \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration \
    "awsvpcConfiguration={subnets=[subnet-xxx,subnet-yyy,subnet-zzz],securityGroups=[sg-api],assignPublicIp=DISABLED}" \
  --load-balancers \
    "targetGroupArn=arn:aws:elasticloadbalancing:us-east-1:ACCOUNT_ID:targetgroup/support-agent/xxx,containerName=api,containerPort=8000" \
  --health-check-grace-period-seconds 60
```

### Auto-Scaling

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id "service/support-agent/api" \
  --scalable-dimension "ecs:service:DesiredCount" \
  --min-capacity 1 \
  --max-capacity 5

aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --resource-id "service/support-agent/api" \
  --scalable-dimension "ecs:service:DesiredCount" \
  --policy-name cpu-target \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration \
    "TargetValue=70.0,PredefinedMetricSpecification={PredefinedMetricType=ECSServiceAverageCPUUtilization}"
```

---

## Step 5: ALB — Load Balancer

### Create target group

```bash
aws elbv2 create-target-group \
  --name support-agent-tg \
  --protocol HTTP \
  --port 8000 \
  --vpc-id vpc-xxxxxxxx \
  --target-type ip \
  --health-check-path /health \
  --health-check-interval-seconds 30 \
  --health-check-timeout-seconds 5 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3
```

### Create ALB

```bash
aws elbv2 create-load-balancer \
  --name support-agent-alb \
  --subnets subnet-public-a subnet-public-b subnet-public-c \
  --security-groups sg-alb \
  --scheme internet-facing \
  --type application \
  --ip-address-type ipv4
```

### HTTPS listener (with ACM certificate)

```bash
aws elbv2 create-listener \
  --load-balancer-arn arn:aws:elasticloadbalancing:...:loadbalancer/app/support-agent-alb/xxx \
  --protocol HTTPS \
  --port 443 \
  --certificates CertificateArn=arn:aws:acm:us-east-1:ACCOUNT_ID:certificate/xxx \
  --default-actions Type=forward,TargetGroupArn=arn:aws:elasticloadbalancing:...:targetgroup/support-agent-tg/xxx
```

### Optional: HTTP → HTTPS redirect

```bash
aws elbv2 create-listener \
  --load-balancer-arn arn:aws:elasticloadbalancing:...:loadbalancer/app/support-agent-alb/xxx \
  --protocol HTTP \
  --port 80 \
  --default-actions Type=redirect,RedirectConfig="{Protocol=HTTPS,Port=443,StatusCode=HTTP_301}"
```

---

## Step 6: Networking

### VPC layout

| Component | CIDR | Type |
|---|---|---|
| VPC | 10.0.0.0/16 | — |
| Public subnet A | 10.0.1.0/24 | Public |
| Public subnet B | 10.0.2.0/24 | Public |
| Public subnet C | 10.0.3.0/24 | Public |
| Private subnet A | 10.0.10.0/24 | Private |
| Private subnet B | 10.0.11.0/24 | Private |
| Private subnet C | 10.0.12.0/24 | Private |

### NAT Gateway

A single NAT Gateway in one public subnet (~$35/mo). For production across 3 AZs, use one per AZ for fault tolerance (~$105/mo).

### VPC Endpoints (cost saving)

VPC Endpoints keep traffic to ECR, Secrets Manager, and CloudWatch Logs within the AWS network, avoiding NAT data processing charges (~$0.045/GB).

```bash
# ECR Docker registry endpoint
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-xxxxxxxx \
  --service-name com.amazonaws.region.ecr.dkr \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-private-a subnet-private-b subnet-private-c \
  --security-group-ids sg-vpc-endpoint

# ECR API endpoint
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-xxxxxxxx \
  --service-name com.amazonaws.region.ecr.api \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-private-a subnet-private-b subnet-private-c \
  --security-group-ids sg-vpc-endpoint

# Secrets Manager endpoint
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-xxxxxxxx \
  --service-name com.amazonaws.region.secretsmanager \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-private-a subnet-private-b subnet-private-c \
  --security-group-ids sg-vpc-endpoint

# CloudWatch Logs endpoint
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-xxxxxxxx \
  --service-name com.amazonaws.region.logs \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-private-a subnet-private-b subnet-private-c \
  --security-group-ids sg-vpc-endpoint
```

### Security Groups

| Security Group | Rule |
|---|---|
| `sg-alb` | Inbound: HTTPS (443) from 0.0.0.0/0 |
| `sg-alb` | Inbound: HTTP (80) from 0.0.0.0/0 (redirect) |
| `sg-api` | Inbound: HTTP (8000) from sg-alb |
| `sg-db` | Inbound: PostgreSQL (5432) from sg-api |
| `sg-redis` | Inbound: Redis (6379) from sg-api |
| `sg-vpc-endpoint` | Inbound: HTTPS (443) from sg-api |

---

## Step 7: ElastiCache Redis (Optional)

Recommended when you reach ~1,000 tickets/day or notice embedding latency.

### Create serverless cache

```bash
aws elasticache create-serverless-cache \
  --serverless-cache-name support-agent-cache \
  --engine redis \
  --major-engine-version 7 \
  --security-group-ids sg-redis \
  --subnet-ids subnet-private-a subnet-private-b subnet-private-c
```

### Endpoint format

```
support-agent-cache-xxx.serverless.use1.cache.amazonaws.com:6379
```

### Embedding cache pattern

```python
import json
import hashlib

CACHE_TTL = 86400  # 24 hours

async def embed_text_cached(text: str, redis) -> list[float]:
    key = f"embed:{hashlib.sha256(text.encode()).hexdigest()}"
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)
    vector = embed_text(text)
    await redis.setex(key, CACHE_TTL, json.dumps(vector))
    return vector
```

---

## Step 8: Observability

### CloudWatch Log Group

```bash
aws logs create-log-group --log-group-name /ecs/support-agent-api
aws logs put-retention-policy --log-group-name /ecs/support-agent-api --retention-in-days 30
```

### CloudWatch Container Insights

Enable on the ECS cluster:

```bash
aws ecs update-cluster-settings \
  --cluster support-agent \
  --settings name=containerInsights,value=enabled
```

### CloudWatch Dashboard

```bash
aws cloudwatch put-dashboard \
  --dashboard-name support-agent \
  --dashboard-body '{
    "widgets": [
      {
        "type": "metric",
        "properties": {
          "metrics": [
            ["ECS/ContainerInsights", "CpuUtilized", {"stat": "Average"}],
            ["ECS/ContainerInsights", "MemoryUtilized", {"stat": "Average"}]
          ],
          "period": 300,
          "stat": "Average",
          "region": "us-east-1",
          "title": "Fargate CPU/Memory"
        }
      },
      {
        "type": "metric",
        "properties": {
          "metrics": [
            ["AWS/ApplicationELB", "TargetResponseTime", {"stat": "p95"}],
            ["AWS/ApplicationELB", "RequestCount", {"stat": "Sum"}],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", {"stat": "Sum"}]
          ],
          "period": 300,
          "stat": "Sum",
          "region": "us-east-1",
          "title": "ALB Metrics"
        }
      }
    ]
  }'
```

### CloudWatch Alarms

```bash
# Alert on 5xx errors
aws cloudwatch put-metric-alarm \
  --alarm-name support-agent-5xx \
  --alarm-description "5xx errors > 1% in 5 minutes" \
  --metric-name HTTPCode_Target_5XX_Count \
  --namespace AWS/ApplicationELB \
  --statistic Sum \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 3 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions arn:aws:sns:us-east-1:ACCOUNT_ID:support-agent-alerts

# Alert on high latency
aws cloudwatch put-metric-alarm \
  --alarm-name support-agent-latency \
  --alarm-description "p95 latency > 5s" \
  --metric-name TargetResponseTime \
  --namespace AWS/ApplicationELB \
  --statistic p95 \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 5000 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions arn:aws:sns:us-east-1:ACCOUNT_ID:support-agent-alerts
```

### AWS X-Ray (Distributed Tracing)

Instrument FastAPI with `aws-xray-sdk`:

```python
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.ext.fastapi import instrument

app = FastAPI()
instrument(app)  # auto-traces all requests + SQL + HTTP clients
```

Enable tracing on the ECS service:

```bash
aws ecs update-service \
  --cluster support-agent \
  --service api \
  --enable-execute-command \
  --enable-tracing
```

---

## Step 9: CI/CD with GitHub Actions

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

env:
  AWS_REGION: us-east-1
  ECR_REPOSITORY: support-agent-api
  ECS_CLUSTER: support-agent
  ECS_SERVICE: api

permissions:
  id-token: write
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Lint
        run: |
          pip install ruff
          ruff check app/

      - name: Test
        run: |
          pip install -r requirements.txt
          pytest tests/ -v

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::${{ secrets.AWS_ACCOUNT_ID }}:role/github-actions-role
          aws-region: ${{ env.AWS_REGION }}

      - name: Build and push Docker image
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_REGISTRY
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG

      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster $ECS_CLUSTER \
            --service $ECS_SERVICE \
            --force-new-deployment
```

---

## Cost Breakdown

| Service | Config | Monthly Cost |
|---|---|---|
| **ECS Fargate** | 1 task × 0.25 vCPU × 0.5GB (always on) | ~$15 |
| **RDS Aurora** | Serverless v2, 1–4 ACU, 20GB storage | ~$30 |
| **ALB** | 1 ALB, 1 target group, minimal traffic | ~$20 |
| **NAT Gateway** | 1 × single AZ | ~$35 |
| **VPC Endpoints** | 4 endpoints × ~$7 | ~$28 |
| **ECR** | 1 image, ~500MB storage | ~$1 |
| **Secrets Manager** | 3 secrets | ~$2 |
| **CloudWatch Logs** | ~1GB ingestion | ~$3 |
| **CloudWatch Container Insights** | Per-task metric | ~$5 |
| **ACM** | Public certificate | Free |
| **Route 53** | 1 hosted zone | $0.50 |
| **Total** | | **~$140/mo** |

---

## Scaling Plan

| Tickets/Day | Fargate Tasks | Task Spec | RDS ACU | Redis | Est. Monthly Cost |
|---|---|---|---|---|---|
| 100 | 1 | 0.25 vCPU / 0.5GB | 1 ACU | Skip | ~$140 |
| 1,000 | 2 | 0.5 vCPU / 1GB | 2 ACU | Add (serverless) | ~$220 |
| 10,000 | 4 | 1 vCPU / 2GB | 4 ACU + reader | Yes | ~$500 |
| 100,000 | 10 | 2 vCPU / 4GB | 8 ACU + 2 readers | Yes + PgBouncer | ~$1,800 |

---

## Key Gotchas

### 1. pgvector on RDS

Aurora PostgreSQL 15+ supports pgvector. If using an older version, you must use a custom DB cluster parameter group:

```sql
-- Verify version and extension support
SELECT version();
SELECT * FROM pg_available_extensions WHERE name = 'vector';
```

If the extension isn't available, upgrade the cluster engine or switch to RDS for PostgreSQL (not Aurora) with the `pgvector` parameter group.

### 2. NAT Gateway Costs

A single NAT Gateway costs ~$35/mo regardless of traffic. To reduce cost:
- Use VPC Endpoints for ECR, Secrets Manager, and CloudWatch (avoids NAT data processing fees)
- Consider a **NAT Instance** instead (~$8/mo for t4g.nano) but with lower reliability

### 3. OpenAI Rate Limits

At 100 tickets/day (~5/hr), you are well within default Tier 1 limits:

| Model | RPM | TPM | Your usage at 100/day |
|---|---|---|---|
| gpt-4o-mini | 10,000 | 200,000 | ~5 RPM (classification + generation) |
| text-embedding-3-small | 5,000 | 250,000 | ~1 RPM |

No throttling concern until ~10,000+ tickets/day, at which point request a Tier 2+ quota increase from OpenAI.

### 4. Connection Pooling

For 1–2 Fargate tasks, asyncpg's built-in pool (`pool_size=20`) is sufficient. For 10+ tasks, add **PgBouncer** as a sidecar in the same task definition:

```json
{
  "name": "pgbouncer",
  "image": "bitnami/pgbouncer:latest",
  "environment": [
    {"name": "POSTGRESQL_HOST", "value": "writer-endpoint"},
    {"name": "POSTGRESQL_PORT", "value": "5432"},
    {"name": "POOL_MODE", "value": "transaction"}
  ],
  "secrets": [
    {"name": "POSTGRESQL_USERNAME", ...},
    {"name": "POSTGRESQL_PASSWORD", ...}
  ]
}
```

Or use **RDS Proxy** (~$15/mo) instead of PgBouncer.

### 5. LangGraph Checkpointing

`PostgresSaver` writes checkpoints to PostgreSQL. The connection string **must** point to the **writer endpoint**, not a reader:

```python
# CORRECT — writer endpoint
DATABASE_URL=postgresql+asyncpg://user:pass@support-agent-db.cluster-xxx.us-east-1.rds.amazonaws.com:5432/support_db

# WRONG — reader endpoint will fail on writes
DATABASE_URL=postgresql+asyncpg://user:pass@support-agent-db.cluster-ro-xxx.us-east-1.rds.amazonaws.com:5432/support_db
```

### 6. Alembic Migrations

Run migrations as a one-off task before the first deployment:

```bash
aws ecs run-task \
  --cluster support-agent \
  --task-definition support-agent-api:1 \
  --overrides '{
    "containerOverrides": [{
      "name": "api",
      "command": ["alembic", "upgrade", "head"]
    }]
  }' \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[...],securityGroups=[...]}"
```

---

## Quick Deploy Checklist

```
□  1. RDS Aurora cluster created with pgvector enabled
□  2. Database migration run (alembic upgrade head)
□  3. ECR repository created, Docker image pushed
□  4. Secrets Manager secrets created (DB, OpenAI, config)
□  5. ECS task definition registered with secrets references
□  6. ALB created with HTTPS listener (ACM certificate)
□  7. VPC, subnets, NAT Gateway, VPC Endpoints configured
□  8. Security groups created (ALB → API → DB → Redis)
□  9. ECS service created, Fargate tasks running
□ 10. Health check passes (GET /health returns 200)
□ 11. Test ticket created (POST /api/v1/tickets returns 201)
□ 12. CloudWatch alarms configured (5xx, latency)
□ 13. GitHub Actions deploy workflow committed
□ 14. (Optional) ElastiCache Redis created
□ 15. (Optional) Domain pointed to ALB via Route 53
```

---

## Appendix A: Minimal CloudFormation Template

```yaml
AWSTemplateFormatVersion: "2010-09-09"
Description: "Customer Support AI Agent — Infrastructure"

Parameters:
  VpcId:
    Type: AWS::EC2::VPC::Id
  PrivateSubnetIds:
    Type: List<AWS::EC2::Subnet::Id>
  PublicSubnetIds:
    Type: List<AWS::EC2::Subnet::Id>

Resources:
  # ECR Repository
  ECRRepository:
    Type: AWS::ECR::Repository
    Properties:
      RepositoryName: support-agent-api

  # RDS Aurora Serverless v2
  DBCluster:
    Type: AWS::RDS::DBCluster
    Properties:
      Engine: aurora-postgresql
      EngineVersion: "15.5"
      ServerlessV2ScalingConfiguration:
        MinCapacity: 1
        MaxCapacity: 4
      MasterUsername: support_user
      ManageMasterUserPassword: true
      DBSubnetGroupName: !Ref DBSubnetGroup
      VpcSecurityGroupIds: [!Ref DBSecurityGroup]
      BackupRetentionPeriod: 7
      StorageEncrypted: true

  DBInstance:
    Type: AWS::RDS::DBInstance
    Properties:
      DBClusterIdentifier: !Ref DBCluster
      DBInstanceClass: db.serverless
      Engine: aurora-postgresql

  DBSubnetGroup:
    Type: AWS::RDS::DBSubnetGroup
    Properties:
      SubnetIds: !Ref PrivateSubnetIds

  DBSecurityGroup:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: RDS access
      VpcId: !Ref VpcId
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: 5432
          ToPort: 5432
          SourceSecurityGroupId: !Ref APISecurityGroup

  # ECS Fargate
  ECSCluster:
    Type: AWS::ECS::Cluster
    Properties:
      ClusterSettings:
        - Name: containerInsights
          Value: enabled

  TaskDefinition:
    Type: AWS::ECS::TaskDefinition
    Properties:
      Family: support-agent-api
      Cpu: "256"
      Memory: "512"
      NetworkMode: awsvpc
      RequiresCompatibilities: [FARGATE]
      ExecutionRoleArn: !GetAtt ExecutionRole.Arn
      TaskRoleArn: !GetAtt TaskRole.Arn
      ContainerDefinitions:
        - Name: api
          Image: !Sub "${AWS::AccountId}.dkr.ecr.${AWS::Region}.amazonaws.com/support-agent-api:latest"
          PortMappings:
            - ContainerPort: 8000
          Secrets:
            - Name: OPENAI_API_KEY
              ValueFrom: !Sub "arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:support-agent/openai-xxxxx"
          LogConfiguration:
            LogDriver: awslogs
            Options:
              awslogs-group: /ecs/support-agent-api
              awslogs-region: !Ref AWS::Region

  # ALB
  LoadBalancer:
    Type: AWS::ElasticLoadBalancingV2::LoadBalancer
    Properties:
      Subnets: !Ref PublicSubnetIds
      SecurityGroups: [!Ref ALBSecurityGroup]
      Type: application

  TargetGroup:
    Type: AWS::ElasticLoadBalancingV2::TargetGroup
    Properties:
      Port: 8000
      Protocol: HTTP
      TargetType: ip
      VpcId: !Ref VpcId
      HealthCheckPath: /health

  Listener:
    Type: AWS::ElasticLoadBalancingV2::Listener
    Properties:
      LoadBalancerArn: !Ref LoadBalancer
      Port: 443
      Protocol: HTTPS
      Certificates:
        - CertificateArn: !Ref Certificate
      DefaultActions:
        - Type: forward
          TargetGroupArn: !Ref TargetGroup

  ECSService:
    Type: AWS::ECS::Service
    Properties:
      Cluster: !Ref ECSCluster
      TaskDefinition: !Ref TaskDefinition
      DesiredCount: 1
      LaunchType: FARGATE
      NetworkConfiguration:
        AwsvpcConfiguration:
          Subnets: !Ref PrivateSubnetIds
          SecurityGroups: [!Ref APISecurityGroup]
          AssignPublicIp: DISABLED
      LoadBalancers:
        - ContainerName: api
          ContainerPort: 8000
          TargetGroupArn: !Ref TargetGroup
```
