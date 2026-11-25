# Demo

`demo.tape` is a [VHS](https://github.com/charmbracelet/vhs) script that records `demo.gif`: it runs
`clickops scan`, `clickops import` on a scratch bucket and `clickops events`.

```
AWS_PROFILE=clickops-admin vhs demo/demo.tape
```

It needs the detector applied (for `events`), a real `clickops.yaml`, Terraform 1.10 or newer and
VHS. `prepare.sh` creates one empty, tagged S3 bucket (free) and `cleanup.sh` deletes it and the
`imports/` folder. The GIF is not committed until someone records it.
