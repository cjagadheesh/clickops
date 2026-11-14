#!/usr/bin/env bash
# Store the Slack Incoming Webhook URL in SSM Parameter Store (SecureString). Run this yourself:
# the URL is read from the terminal without echo, so it never appears in chat, shell history or git.
#
#   AWS_PROFILE=clickops-admin scripts/store_slack_webhook.sh
#
# The equivalent single command is:
#   aws ssm put-parameter --name /clickops/slack-webhook --type SecureString --value '<paste URL>'
set -euo pipefail

NAME=${CLICKOPS_SLACK_PARAM:-/clickops/slack-webhook}
REGION=ap-south-1

read -r -s -p "Paste the Slack webhook URL (input is hidden): " URL
echo
case "$URL" in
  https://hooks.slack.com/*) ;;
  *) echo "That does not look like a Slack webhook URL (https://hooks.slack.com/...)." >&2; exit 1 ;;
esac

# SSM does not allow tags together with --overwrite, so tag only on first creation.
if aws ssm get-parameter --region "$REGION" --name "$NAME" > /dev/null 2>&1; then
  aws ssm put-parameter --region "$REGION" --name "$NAME" --type SecureString \
    --overwrite --value "$URL" > /dev/null
else
  aws ssm put-parameter --region "$REGION" --name "$NAME" --type SecureString \
    --tags Key=project,Value=clickops Key=owner,Value=agent --value "$URL" > /dev/null
fi
echo "Stored $NAME. Test it with: scripts/invoke_fixture.sh ec2/AuthorizeSecurityGroupIngress"
