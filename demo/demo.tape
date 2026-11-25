# Re-runnable demo for the README. Needs VHS (https://github.com/charmbracelet/vhs), a real
# clickops.yaml, AWS credentials and Terraform 1.10+. Regenerate with:
#
#   AWS_PROFILE=clickops-admin vhs demo/demo.tape
#
# demo/prepare.sh makes one scratch bucket first and demo/cleanup.sh deletes it afterwards.
Output demo/demo.gif

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 700
Set Padding 16
Set TypingSpeed 40ms

Hide
Type "export CLICKOPS_DEMO_BUCKET=$(demo/prepare.sh) && clear" Enter
Show

Type "# 1. Resources in AWS that no Terraform state knows about" Enter
Type "clickops scan" Enter
Sleep 6s

Type "# 2. Turn the scratch bucket into Terraform code" Enter
Type "clickops import --only $CLICKOPS_DEMO_BUCKET" Enter
Sleep 20s

Type "# 3. What clickops saw in the last hour" Enter
Type "clickops events --since 1h" Enter
Sleep 6s

Hide
Type "demo/cleanup.sh" Enter
Show
