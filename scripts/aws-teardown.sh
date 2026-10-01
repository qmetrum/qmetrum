#!/usr/bin/env bash
# Full teardown of the Qsight AWS footprint (eu-north-1), cost-driven, 2026-10-01.
#
# Prerequisite: credentials with admin-ish rights. The daily-driver `qmetrum-ops`
# user is read-only for every destructive call below (verified by probe), so this
# needs either AdministratorAccess attached to it or a temporary admin credential.
#
# Data safety: assumes ~/Documents/qmetrum-aws-final-backup{,.tar.gz} already
# holds the verified logical dump (365,811 rows / 32 tables, alembic 20260810_0016).
# This script does NOT back anything up. It deletes with no final snapshot.
#
# Usage:
#   bash scripts/aws-teardown.sh --dry-run    # print what would happen
#   bash scripts/aws-teardown.sh --yes-really # actually delete

set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
R="--region eu-north-1"
CLUSTER=qsight-cluster
SERVICE=qsight-backend
DB=qmetrum-dev
POOL=eu-north-1_ghOcVAcf7

MODE="${1:-}"
case "$MODE" in
  --dry-run)     DRY=1 ;;
  --yes-really)  DRY=0 ;;
  *) echo "refusing to run without an explicit mode."; echo "  --dry-run | --yes-really"; exit 2 ;;
esac

run() {
  if [ "$DRY" = 1 ]; then printf '  [dry-run] %s\n' "$*"
  else printf '  + %s\n' "$*"; "$@" >/tmp/qm_td_out 2>&1 || { echo "    ! failed: $(head -2 /tmp/qm_td_out | tr '\n' ' ')"; return 1; }
  fi
}

step() { printf '\n=== %s ===\n' "$1"; }

BACKUP=~/Documents/qmetrum-aws-final-backup.tar.gz
if [ ! -f "$BACKUP" ]; then
  echo "ABORT: backup archive not found at $BACKUP"; exit 1
fi
echo "backup present: $(du -h "$BACKUP" | cut -f1)  $BACKUP"
echo "mode: $MODE"

# ---------------------------------------------------------------- ECS
step "ECS: scale to 0, delete service, delete cluster"
run aws ecs update-service --cluster $CLUSTER --service $SERVICE --desired-count 0 $R
for t in $(aws ecs list-tasks --cluster $CLUSTER $R --query 'taskArns[]' --output text 2>/dev/null); do
  run aws ecs stop-task --cluster $CLUSTER --task "$t" --reason teardown $R
done
run aws ecs delete-service --cluster $CLUSTER --service $SERVICE --force $R
for td in $(aws ecs list-task-definitions $R --query 'taskDefinitionArns[]' --output text 2>/dev/null); do
  run aws ecs deregister-task-definition --task-definition "$td" $R
done
run aws ecs delete-cluster --cluster $CLUSTER $R

# ---------------------------------------------------------------- ALB
step "ELB: delete listeners, load balancer, target group (frees 3 public IPv4)"
ALB=$(aws elbv2 describe-load-balancers --names qsight-alb $R --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null)
if [ -n "${ALB:-}" ] && [ "$ALB" != "None" ]; then
  for l in $(aws elbv2 describe-listeners --load-balancer-arn "$ALB" $R --query 'Listeners[].ListenerArn' --output text 2>/dev/null); do
    run aws elbv2 delete-listener --listener-arn "$l" $R
  done
  run aws elbv2 delete-load-balancer --load-balancer-arn "$ALB" $R
fi
TG=$(aws elbv2 describe-target-groups --names qsight-backend-tg $R --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null)
if [ -n "${TG:-}" ] && [ "$TG" != "None" ]; then
  [ "$DRY" = 0 ] && sleep 20   # TG delete fails while still associated
  run aws elbv2 delete-target-group --target-group-arn "$TG" $R
fi

# ---------------------------------------------------------------- RDS
step "RDS: delete instance, no final snapshot, drop automated backups"
run aws rds delete-db-instance --db-instance-identifier $DB \
  --skip-final-snapshot --delete-automated-backups $R

# ---------------------------------------------------------------- ECR
step "ECR: delete both repos and all 249 GB of images"
for repo in qsight-backend qsight-risk; do
  run aws ecr delete-repository --repository-name "$repo" --force $R
done

# ---------------------------------------------------------------- Cognito
step "Cognito: delete user pool domain + pool"
DOMAIN=$(aws cognito-idp describe-user-pool --user-pool-id $POOL $R --query 'UserPool.Domain' --output text 2>/dev/null)
if [ -n "${DOMAIN:-}" ] && [ "$DOMAIN" != "None" ]; then
  run aws cognito-idp delete-user-pool-domain --user-pool-id $POOL --domain "$DOMAIN" $R
  [ "$DRY" = 0 ] && sleep 10
fi
run aws cognito-idp delete-user-pool --user-pool-id $POOL $R

# ---------------------------------------------------------------- Amplify
step "Amplify: delete app qsight-frontend"
APP=$(aws amplify list-apps $R --query "apps[?name=='qsight-frontend'].appId | [0]" --output text 2>/dev/null)
if [ -n "${APP:-}" ] && [ "$APP" != "None" ]; then
  run aws amplify delete-app --app-id "$APP" $R
else
  echo "  (app not found or amplify:ListApps denied — check console)"
fi

# ---------------------------------------------------------------- ACM
step "ACM: delete certs (must come after ALB + Amplify release them)"
[ "$DRY" = 0 ] && sleep 15
for c in $(aws acm list-certificates $R --query 'CertificateSummaryList[].CertificateArn' --output text 2>/dev/null); do
  run aws acm delete-certificate --certificate-arn "$c" $R
done
# Amplify's cert lives in us-east-1 and is removed with the app; check manually:
echo "  note: also check us-east-1 for Amplify-managed certs"

# ---------------------------------------------------------------- Logs
step "CloudWatch Logs: delete log groups"
for g in /ecs/qsight-backend /aws/amplify/d2ww1t8ydrpb46 RDSOSMetrics; do
  run aws logs delete-log-group --log-group-name "$g" $R
done

# ---------------------------------------------------------------- SSM
step "SSM: delete /qsight/prod/* parameters (backed up in config/ssm-qsight-params.json)"
for p in $(aws ssm get-parameters-by-path --path /qsight/ --recursive $R --query 'Parameters[].Name' --output text 2>/dev/null); do
  run aws ssm delete-parameter --name "$p" $R
done

step "DONE"
echo "Remaining by design: VPC/subnets/SGs (free), IAM roles & users (free),"
echo "GitHub OIDC provider (free). Delete those by hand if you want a bare account."
echo
echo "Verify in 24h:  aws ce get-cost-and-usage --time-period Start=\$(date +%Y-%m-%d),End=... "
