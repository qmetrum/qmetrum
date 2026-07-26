#!/usr/bin/env bash
# qsight.sh — turn the Qsight backend on/off to save idle Fargate cost.
#
#   ./scripts/qsight.sh up       # start the backend (~2-3 min to healthy)
#   ./scripts/qsight.sh down     # stop it (saves ~$45/mo idle; DB/domain stay)
#   ./scripts/qsight.sh status   # desired/running count + live health
#
# Notes:
# - RDS, the ALB, and qsight.qmetrum.io stay up; only the compute stops.
# - While down, the frontend loads but API calls fail — expected.
# - A push to master while down still builds+pushes the image; no task starts
#   until you run `up`, which then boots the newest image.
set -euo pipefail

CLUSTER="qsight-cluster"
SERVICE="qsight-backend"
HEALTH_URL="https://qsight-api.qmetrum.io/healthz"

case "${1:-status}" in
  up)
    aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" \
      --desired-count 1 --no-cli-pager --query 'service.desiredCount' --output text
    echo "Starting… waiting for service to stabilise (usually 2-3 min)"
    aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"
    for i in $(seq 1 30); do
      if curl -sf -o /dev/null --max-time 5 "$HEALTH_URL"; then
        echo "UP — $HEALTH_URL is healthy."
        exit 0
      fi
      sleep 5
    done
    echo "Service is stable but $HEALTH_URL not healthy yet — give it a minute." >&2
    exit 1
    ;;
  down)
    aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" \
      --desired-count 0 --no-cli-pager --query 'service.desiredCount' --output text
    echo "DOWN — compute stopped (~\$45/mo saved while idle). './scripts/qsight.sh up' to restart."
    ;;
  status)
    aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" --no-cli-pager \
      --query 'services[0].{desired:desiredCount,running:runningCount,rollout:deployments[0].rolloutState}'
    if curl -sf -o /dev/null --max-time 5 "$HEALTH_URL"; then
      echo "health: UP ($HEALTH_URL)"
    else
      echo "health: DOWN ($HEALTH_URL not responding)"
    fi
    ;;
  *)
    echo "usage: $0 up|down|status" >&2
    exit 2
    ;;
esac
