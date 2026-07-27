#!/usr/bin/env bash
# enable-alert-email.sh — wire the alert-email SSM params into the ECS task
# definition and roll it out. Run this ONCE, only AFTER:
#   1. the alert-email code is deployed (committed + pushed),
#   2. SES sender identity is verified in eu-north-1,
#   3. the qsight-ecs-task role has ses:SendEmail,
#   4. you have flipped the flag on:
#        aws ssm put-parameter --region eu-north-1 --overwrite \
#          --name /qsight/prod/EMAIL_ALERTS_ENABLED --type String --value true
#
# It clones the CURRENT task definition, appends three `secrets` entries
# (mapping the SSM params to env vars the app reads), registers a new revision,
# and points the service at it. Idempotent: re-running just registers another
# revision with the same result. Requires jq.
set -euo pipefail

REGION=eu-north-1
CLUSTER=qsight-cluster
SERVICE=qsight-backend
CONTAINER=qsight-backend
ACCOUNT=536114535539
SSM_PREFIX="arn:aws:ssm:${REGION}:${ACCOUNT}:parameter/qsight/prod"

command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

TD_ARN=$(aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
  --region "$REGION" --query 'services[0].taskDefinition' --output text)
echo "Cloning task definition: $TD_ARN"

aws ecs describe-task-definition --task-definition "$TD_ARN" --region "$REGION" \
  --query 'taskDefinition' --output json > /tmp/qsight-td.json

# Append the three secrets to the app container (skip any already present),
# then strip the read-only fields register-task-definition rejects.
jq --arg c "$CONTAINER" --arg p "$SSM_PREFIX" '
  (.containerDefinitions[] | select(.name==$c) | .secrets) |=
    ( . + [
        {name:"EMAIL_ALERTS_ENABLED", valueFrom:($p+"/EMAIL_ALERTS_ENABLED")},
        {name:"ALERT_EMAIL_SENDER",   valueFrom:($p+"/ALERT_EMAIL_SENDER")},
        {name:"APP_BASE_URL",         valueFrom:($p+"/APP_BASE_URL")}
      ]
      | unique_by(.name) )
  | del(.taskDefinitionArn,.revision,.status,.requiresAttributes,
        .compatibilities,.registeredAt,.registeredBy)
' /tmp/qsight-td.json > /tmp/qsight-td-new.json

NEW_ARN=$(aws ecs register-task-definition --region "$REGION" \
  --cli-input-json file:///tmp/qsight-td-new.json \
  --query 'taskDefinition.taskDefinitionArn' --output text)
echo "Registered: $NEW_ARN"

aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" \
  --task-definition "$NEW_ARN" --region "$REGION" --no-cli-pager >/dev/null
echo "Service updated. Waiting for stable…"
aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE" --region "$REGION"
echo "Done. Alert emails active once EMAIL_ALERTS_ENABLED=true and SES is out of sandbox."
