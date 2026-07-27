#!/usr/bin/env bash
# ============================================================================
# deploy-ecs-fargate.sh
# ----------------------------------------------------------------------------
# One-shot AWS setup that turns your existing ECR image + RDS + SSM params
# into a running, public-URL backend on ECS Fargate.
#
# Idempotent — re-running it skips anything already in place.
#
# Prereqs (all already done from earlier in the chat):
#   • AWS CLI configured with creds (`aws configure` once).
#   • ECR repo `qsight-backend` in eu-north-1 with a `:latest` image.
#   • SSM params under /qsight/prod/* in eu-north-1.
#   • IAM role `qsight-github-deploy` exists.
#
# What this script creates / configures:
#   1. Replaces the App Runner inline policy on `qsight-github-deploy`
#      with the ECS deploy permissions.
#   2. Creates IAM roles `qsight-ecs-execution` and `qsight-ecs-task`.
#   3. Creates ECS cluster `qsight-cluster`.
#   4. Creates two security groups (ALB-facing + task-facing).
#   5. Creates ALB `qsight-alb` + target group + HTTP:80 listener.
#   6. Creates CloudWatch log group `/ecs/qsight-backend`.
#   7. Registers task definition `qsight-backend` (Fargate, 1 vCPU/2 GB,
#      env vars wired to SSM, port 8000).
#   8. Creates ECS service `qsight-backend` (1 desired, behind the ALB).
#   9. Waits for the service to stabilize, then prints the ALB DNS.
#
# Usage:
#   bash scripts/deploy-ecs-fargate.sh           # run it
#   bash scripts/deploy-ecs-fargate.sh --plan    # print what it would do
# ============================================================================

set -euo pipefail

REGION="eu-north-1"
CLUSTER_NAME="qsight-cluster"
SERVICE_NAME="qsight-backend"
TASK_FAMILY="qsight-backend"
ECR_REPO="qsight-backend"
IMAGE_TAG="latest"
ALB_NAME="qsight-alb"
TG_NAME="qsight-backend-tg"
ALB_SG_NAME="qsight-alb-sg"
TASK_SG_NAME="qsight-backend-sg"
EXEC_ROLE="qsight-ecs-execution"
TASK_ROLE="qsight-ecs-task"
LOG_GROUP="/ecs/qsight-backend"
GH_DEPLOY_ROLE="qsight-github-deploy"

DRY_RUN=0
if [[ "${1:-}" == "--plan" ]]; then
  DRY_RUN=1
fi

c_blue()  { printf '\033[1;34m%s\033[0m\n' "$*"; }
c_green() { printf '\033[1;32m%s\033[0m\n' "$*"; }
c_yel()   { printf '\033[1;33m%s\033[0m\n' "$*"; }
c_red()   { printf '\033[1;31m%s\033[0m\n' "$*" >&2; }

step()    { c_blue ">>> $*"; }
done_msg(){ c_green "    ✓ $*"; }
note()    { c_yel  "    – $*"; }

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "    [PLAN] $*"
  else
    eval "$@"
  fi
}

# ------------------------------------------------------------------ preflight

step "Preflight: checking AWS CLI auth + region"
if ! aws sts get-caller-identity > /dev/null 2>&1; then
  c_red "AWS CLI is not authenticated. Run 'aws configure' first."
  exit 1
fi
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
done_msg "AWS account: $ACCOUNT_ID, region: $REGION"

step "Preflight: looking up default VPC and subnets"
VPC_ID=$(aws ec2 describe-vpcs \
  --region "$REGION" \
  --filters Name=is-default,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
if [[ -z "$VPC_ID" || "$VPC_ID" == "None" ]]; then
  c_red "No default VPC found in $REGION."
  exit 1
fi

# Public subnets only (those with auto-assign public IP). For default VPC,
# all subnets are public — we just take all subnets in the VPC.
SUBNET_IDS=$(aws ec2 describe-subnets \
  --region "$REGION" \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[*].SubnetId' --output text)
SUBNET_CSV=$(echo "$SUBNET_IDS" | tr '[:space:]' ',' | sed 's/,$//')
done_msg "VPC: $VPC_ID, subnets: $SUBNET_CSV"

# ------------------------------------------------------------ phase A: deploy role

step "Phase A: updating $GH_DEPLOY_ROLE inline policy (App Runner -> ECS)"

# Remove any previous app-runner-flavored inline policy if present
for old_policy in qsight-apprunner-deploy qsight-app-runner-deploy ; do
  if aws iam get-role-policy --role-name "$GH_DEPLOY_ROLE" \
        --policy-name "$old_policy" > /dev/null 2>&1; then
    note "Removing old inline policy: $old_policy"
    run "aws iam delete-role-policy --role-name $GH_DEPLOY_ROLE --policy-name $old_policy"
  fi
done

cat > /tmp/qsight-ecs-deploy.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecs:UpdateService",
        "ecs:DescribeServices",
        "ecs:DescribeTasks"
      ],
      "Resource": "*"
    }
  ]
}
JSON

run "aws iam put-role-policy \
  --role-name $GH_DEPLOY_ROLE \
  --policy-name qsight-ecs-deploy \
  --policy-document file:///tmp/qsight-ecs-deploy.json"
done_msg "$GH_DEPLOY_ROLE now has ecs:UpdateService"

# -------------------------------------------------------- phase B: ECS roles

cat > /tmp/ecs-trust.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "ecs-tasks.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
JSON

cat > /tmp/qsight-ssm-read.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ssm:GetParameters", "ssm:GetParameter"],
      "Resource": "arn:aws:ssm:${REGION}:*:parameter/qsight/prod/*"
    },
    {
      "Effect": "Allow",
      "Action": ["kms:Decrypt"],
      "Resource": "*"
    }
  ]
}
JSON

ensure_role() {
  local role="$1"
  if aws iam get-role --role-name "$role" > /dev/null 2>&1; then
    note "Role $role already exists"
  else
    run "aws iam create-role --role-name $role \
      --assume-role-policy-document file:///tmp/ecs-trust.json"
    done_msg "Created role $role"
  fi
}

step "Phase B1: $EXEC_ROLE (task execution role)"
ensure_role "$EXEC_ROLE"
run "aws iam attach-role-policy --role-name $EXEC_ROLE \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy" || true
run "aws iam put-role-policy --role-name $EXEC_ROLE \
  --policy-name qsight-ssm-read --policy-document file:///tmp/qsight-ssm-read.json"
done_msg "$EXEC_ROLE has ECS exec policy + SSM read"

step "Phase B2: $TASK_ROLE (task role / running container's identity)"
ensure_role "$TASK_ROLE"
run "aws iam put-role-policy --role-name $TASK_ROLE \
  --policy-name qsight-ssm-read --policy-document file:///tmp/qsight-ssm-read.json"
done_msg "$TASK_ROLE has SSM read"

EXEC_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${EXEC_ROLE}"
TASK_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${TASK_ROLE}"

# Wait briefly for IAM eventual consistency before ECS tries to assume them.
sleep 8

# -------------------------------------------------------- phase C: ECS cluster

step "Phase C: ECS cluster $CLUSTER_NAME"
if aws ecs describe-clusters --region "$REGION" --clusters "$CLUSTER_NAME" \
      --query 'clusters[?status==`ACTIVE`].clusterName' --output text \
      | grep -q "$CLUSTER_NAME"; then
  note "Cluster $CLUSTER_NAME already exists"
else
  run "aws ecs create-cluster --region $REGION --cluster-name $CLUSTER_NAME"
  done_msg "Created cluster $CLUSTER_NAME"
fi

# -------------------------------------------------------- phase D: networking

get_sg_by_name() {
  local name="$1"
  aws ec2 describe-security-groups --region "$REGION" \
    --filters "Name=group-name,Values=$name" "Name=vpc-id,Values=$VPC_ID" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null
}

step "Phase D1: ALB security group ($ALB_SG_NAME)"
ALB_SG_ID=$(get_sg_by_name "$ALB_SG_NAME")
if [[ -z "$ALB_SG_ID" || "$ALB_SG_ID" == "None" ]]; then
  ALB_SG_ID=$(aws ec2 create-security-group --region "$REGION" \
    --group-name "$ALB_SG_NAME" \
    --description "qsight ALB inbound 80/443" \
    --vpc-id "$VPC_ID" \
    --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --region "$REGION" \
    --group-id "$ALB_SG_ID" --protocol tcp --port 80 --cidr 0.0.0.0/0 > /dev/null
  done_msg "Created $ALB_SG_NAME ($ALB_SG_ID), allow 80 from 0.0.0.0/0"
else
  note "$ALB_SG_NAME already exists ($ALB_SG_ID)"
fi

step "Phase D2: task security group ($TASK_SG_NAME)"
TASK_SG_ID=$(get_sg_by_name "$TASK_SG_NAME")
if [[ -z "$TASK_SG_ID" || "$TASK_SG_ID" == "None" ]]; then
  TASK_SG_ID=$(aws ec2 create-security-group --region "$REGION" \
    --group-name "$TASK_SG_NAME" \
    --description "qsight backend tasks (port 8000 from ALB)" \
    --vpc-id "$VPC_ID" \
    --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --region "$REGION" \
    --group-id "$TASK_SG_ID" --protocol tcp --port 8000 \
    --source-group "$ALB_SG_ID" > /dev/null
  done_msg "Created $TASK_SG_NAME ($TASK_SG_ID), allow 8000 from ALB SG"
else
  note "$TASK_SG_NAME already exists ($TASK_SG_ID)"
fi

step "Phase D3: target group $TG_NAME"
TG_ARN=$(aws elbv2 describe-target-groups --region "$REGION" \
  --names "$TG_NAME" --query 'TargetGroups[0].TargetGroupArn' \
  --output text 2>/dev/null || true)
if [[ -z "$TG_ARN" || "$TG_ARN" == "None" ]]; then
  TG_ARN=$(aws elbv2 create-target-group --region "$REGION" \
    --name "$TG_NAME" \
    --protocol HTTP --port 8000 \
    --vpc-id "$VPC_ID" \
    --target-type ip \
    --health-check-protocol HTTP \
    --health-check-path /healthz \
    --health-check-interval-seconds 15 \
    --health-check-timeout-seconds 5 \
    --healthy-threshold-count 2 \
    --unhealthy-threshold-count 3 \
    --query 'TargetGroups[0].TargetGroupArn' --output text)
  done_msg "Created target group ($TG_ARN)"
else
  note "Target group $TG_NAME already exists ($TG_ARN)"
fi

step "Phase D4: ALB $ALB_NAME"
ALB_ARN=$(aws elbv2 describe-load-balancers --region "$REGION" \
  --names "$ALB_NAME" --query 'LoadBalancers[0].LoadBalancerArn' \
  --output text 2>/dev/null || true)
if [[ -z "$ALB_ARN" || "$ALB_ARN" == "None" ]]; then
  # subnets need to be space-separated for create-load-balancer
  ALB_ARN=$(aws elbv2 create-load-balancer --region "$REGION" \
    --name "$ALB_NAME" \
    --subnets $SUBNET_IDS \
    --security-groups "$ALB_SG_ID" \
    --scheme internet-facing \
    --type application \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text)
  done_msg "Created ALB ($ALB_ARN)"
else
  note "ALB $ALB_NAME already exists ($ALB_ARN)"
fi

ALB_DNS=$(aws elbv2 describe-load-balancers --region "$REGION" \
  --load-balancer-arns "$ALB_ARN" \
  --query 'LoadBalancers[0].DNSName' --output text)

step "Phase D5: ALB HTTP:80 listener -> target group"
LISTENER_ARN=$(aws elbv2 describe-listeners --region "$REGION" \
  --load-balancer-arn "$ALB_ARN" \
  --query 'Listeners[?Port==`80`].ListenerArn | [0]' \
  --output text 2>/dev/null || true)
if [[ -z "$LISTENER_ARN" || "$LISTENER_ARN" == "None" ]]; then
  aws elbv2 create-listener --region "$REGION" \
    --load-balancer-arn "$ALB_ARN" \
    --protocol HTTP --port 80 \
    --default-actions "Type=forward,TargetGroupArn=$TG_ARN" > /dev/null
  done_msg "Created HTTP:80 listener forwarding to $TG_NAME"
else
  note "Listener on :80 already exists"
fi

# -------------------------------------------------------- phase E: task def + service

step "Phase E1: CloudWatch log group $LOG_GROUP"
if aws logs describe-log-groups --region "$REGION" \
      --log-group-name-prefix "$LOG_GROUP" \
      --query 'logGroups[?logGroupName==`'"$LOG_GROUP"'`].logGroupName' \
      --output text | grep -q "$LOG_GROUP"; then
  note "Log group already exists"
else
  run "aws logs create-log-group --region $REGION --log-group-name $LOG_GROUP"
  run "aws logs put-retention-policy --region $REGION \
        --log-group-name $LOG_GROUP --retention-in-days 14"
  done_msg "Created log group with 14-day retention"
fi

step "Phase E2: registering task definition $TASK_FAMILY"

IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}"
SSM_BASE="arn:aws:ssm:${REGION}:${ACCOUNT_ID}:parameter/qsight/prod"

cat > /tmp/qsight-taskdef.json <<JSON
{
  "family": "${TASK_FAMILY}",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "executionRoleArn": "${EXEC_ROLE_ARN}",
  "taskRoleArn": "${TASK_ROLE_ARN}",
  "containerDefinitions": [
    {
      "name": "qsight-backend",
      "image": "${IMAGE_URI}",
      "essential": true,
      "portMappings": [
        { "containerPort": 8000, "protocol": "tcp", "name": "http", "appProtocol": "http" }
      ],
      "secrets": [
        { "name": "DATABASE_URL",         "valueFrom": "${SSM_BASE}/DATABASE_URL" },
        { "name": "GOOGLE_API_KEY",       "valueFrom": "${SSM_BASE}/GOOGLE_API_KEY" },
        { "name": "COGNITO_REGION",       "valueFrom": "${SSM_BASE}/COGNITO_REGION" },
        { "name": "COGNITO_USER_POOL_ID", "valueFrom": "${SSM_BASE}/COGNITO_USER_POOL_ID" },
        { "name": "COGNITO_APP_CLIENT_ID","valueFrom": "${SSM_BASE}/COGNITO_APP_CLIENT_ID" },
        { "name": "CORS_ALLOW_ALL",       "valueFrom": "${SSM_BASE}/CORS_ALLOW_ALL" },
        { "name": "CORS_ALLOW_ORIGINS",   "valueFrom": "${SSM_BASE}/CORS_ALLOW_ORIGINS" },
        { "name": "QPULSE_INGEST_KEY",    "valueFrom": "${SSM_BASE}/QPULSE_INGEST_KEY" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group":         "${LOG_GROUP}",
          "awslogs-region":        "${REGION}",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
JSON

run "aws ecs register-task-definition --region $REGION \
  --cli-input-json file:///tmp/qsight-taskdef.json \
  --query 'taskDefinition.taskDefinitionArn' --output text"
done_msg "Registered new task definition revision"

step "Phase E3: ECS service $SERVICE_NAME"
SERVICE_STATUS=$(aws ecs describe-services --region "$REGION" \
  --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
  --query 'services[0].status' --output text 2>/dev/null || true)

NETWORK_CONF="awsvpcConfiguration={subnets=[${SUBNET_CSV}],securityGroups=[${TASK_SG_ID}],assignPublicIp=ENABLED}"
LB_CONF="targetGroupArn=${TG_ARN},containerName=qsight-backend,containerPort=8000"

if [[ "$SERVICE_STATUS" == "ACTIVE" ]]; then
  note "Service exists — forcing redeploy with new task definition"
  run "aws ecs update-service --region $REGION \
    --cluster $CLUSTER_NAME --service $SERVICE_NAME \
    --task-definition $TASK_FAMILY --force-new-deployment > /dev/null"
elif [[ "$SERVICE_STATUS" == "DRAINING" || "$SERVICE_STATUS" == "INACTIVE" ]]; then
  c_red "Service is in $SERVICE_STATUS state — delete it manually then re-run"
  exit 1
else
  run "aws ecs create-service --region $REGION \
    --cluster $CLUSTER_NAME \
    --service-name $SERVICE_NAME \
    --task-definition $TASK_FAMILY \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration \"$NETWORK_CONF\" \
    --load-balancers \"$LB_CONF\" \
    --health-check-grace-period-seconds 60 > /dev/null"
  done_msg "Created service $SERVICE_NAME"
fi

step "Phase E4: waiting for service to stabilize (up to ~10 min)…"
if [[ $DRY_RUN -eq 0 ]]; then
  aws ecs wait services-stable --region "$REGION" \
    --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME"
  done_msg "Service is stable"
fi

# -------------------------------------------------------- summary

c_green ""
c_green "============================================================"
c_green " ✓ Deploy complete"
c_green "============================================================"
echo ""
echo "  ALB DNS:        http://$ALB_DNS"
echo "  Health check:   curl http://$ALB_DNS/healthz"
echo "  Cluster:        $CLUSTER_NAME"
echo "  Service:        $SERVICE_NAME"
echo "  Task family:    $TASK_FAMILY"
echo ""
echo "  Next steps:"
echo "    1. curl http://$ALB_DNS/healthz   # should print {\"status\":\"ok\"}"
echo "    2. Add to GitHub repo secrets:"
echo "         ECS_CLUSTER = $CLUSTER_NAME"
echo "         ECS_SERVICE = $SERVICE_NAME"
echo "         (delete the old APP_RUNNER_SERVICE_ARN if present)"
echo "    3. Push the updated workflow file:"
echo "         git push"
echo "    4. Move on to Amplify (frontend) when ready."
echo ""
