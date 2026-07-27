# Alert email delivery (AWS SES) — activation checklist

The code is shipped and OFF by default. Alert emails start flowing only after
these one-time steps. Until then, alerts behave exactly as before (in-app only).

## 1. Verify a sender identity in SES (console, eu-north-1)
- SES → Verified identities → Create identity → Email address (e.g.
  `alerts@qmetrum.io`) or the whole `qmetrum.io` domain (domain is better:
  DKIM, no per-address verification).
- Click the verification link (email) or add the DNS records (domain).

## 2. Leave the SES sandbox (console → Account dashboard → Request production access)
- In the sandbox, SES only sends to *verified* recipient addresses. Fine for
  testing to your own inbox; required to email real users.

## 3. Grant the ECS task role SES send permission
The app sends as the `qsight-ecs-task` role, which currently has no SES rights.
Add (needs an IAM edit — qmetrum-ops may lack iam:PutRolePolicy, so use a
temporary root key or the console):

    {
      "Effect": "Allow",
      "Action": ["ses:SendEmail", "ses:SendRawEmail"],
      "Resource": "*"
    }

## 4. Set env / SSM on the ECS task
- `EMAIL_ALERTS_ENABLED=true`
- `ALERT_EMAIL_SENDER=alerts@qmetrum.io`   (must match the verified identity)
- `APP_BASE_URL=https://qsight.qmetrum.io` (optional, adds a link in the email)
- `AWS_REGION` already set for the task; SES uses it (falls back to eu-north-1).

## Behavior once on
- The alert scheduler emails the rule's owner (`User.email`) on a FRESH trigger
  only; the existing per-rule cooldown (default 900s) is what prevents repeats,
  so no extra throttle is needed.
- Delivery is best-effort: a send failure logs a warning and never affects
  alert evaluation or the persisted AlertEvent.

## Known limitation (interacts with scale-to-zero)
The scheduler is an in-process daemon thread, so evaluation (and therefore
emails) only happen while the backend task is running. With the app scaled to
zero when idle, alerts are not evaluated until it is up. For always-on
monitoring, move evaluation to an external trigger (EventBridge schedule -> a
small `POST /alerts/evaluate` task) independent of the web service.
