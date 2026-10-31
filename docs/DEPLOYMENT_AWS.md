# AWS Deployment (ca-central-1)

**Nothing has been provisioned.** Creating AWS resources incurs charges and needs the owner's explicit go-ahead.

## Recommended for the demo: one EC2 host + Docker Compose

Cheapest reliable path: one instance runs Postgres, the API/agents, the web app, and Caddy (automatic HTTPS).

| Resource | Choice | Approx. cost |
|---|---|---|
| EC2 | `t3.small` (2 vCPU, 2 GB), Amazon Linux 2023, 20 GB gp3, in `ca-central-1` | ~US$17/month |
| Elastic IP | 1 | free while attached |
| DNS | an A record on a domain you already own | — |
| CloudWatch Logs | `awslogs` driver, group `carebridge` | low at demo volume |
| Secrets | SSM Parameter Store SecureString for `MODEL_API_KEY`, `JWT_SECRET`, `POSTGRES_PASSWORD` | free tier |

Steps (run by the owner):

1. Launch the instance with an IAM role allowing `logs:CreateLogGroup/CreateLogStream/PutLogEvents` and
   `ssm:GetParameters` on `/carebridge/*`. Security group: 80 and 443 open; 22 restricted to your IP.
2. Install Docker and the compose plugin, clone the repo.
3. Write `.env` from SSM:
   ```bash
   aws ssm get-parameters --region ca-central-1 --with-decryption --names /carebridge/MODEL_API_KEY /carebridge/JWT_SECRET /carebridge/POSTGRES_PASSWORD
   ```
   then fill `.env` (see `.env.example`) and `chmod 600 .env`.
4. Point the DNS A record at the Elastic IP, then:
   ```bash
   DOMAIN=demo.example.ca docker compose -f docker-compose.prod.yml --env-file .env up -d --build
   ```
5. Seed synthetic data: `docker compose -f docker-compose.prod.yml exec backend python -m app.seed`
6. Verify Meta inference: `docker compose -f docker-compose.prod.yml exec backend python -m app.verify_meta`

## Production path

- Web: AWS Amplify Hosting or ECS Fargate. API/agents: ECS Fargate behind an ALB with ACM certificates.
- Database: RDS for PostgreSQL (Multi-AZ, encrypted, automated backups).
- Documents: private S3 bucket, SSE-KMS, Block Public Access, presigned GETs. `app/storage.py` keys already use
  the `cases/<case_id>/<uuid>.pdf` layout; swapping in boto3 is a ~30-line change.
- Background work: SQS + a worker task instead of in-process background tasks.
- Secrets Manager with rotation; CloudWatch alarms on `model_calls.status != ok` rates and processing failures.
