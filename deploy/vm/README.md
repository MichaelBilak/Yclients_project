# VM Deploy

The VM treats GitHub `main` as the source of truth. Vercel deploys frontend from
GitHub. Backend deploy is triggered by GitHub Actions on every push to `main`.
The VM timer can stay enabled as a fallback poller.

## GitHub Actions

The workflow is `.github/workflows/deploy-vm.yml`. It runs tests, then connects
to the VM over SSH and starts `yclients-auto-deploy.service`.

Add repository secrets in GitHub:

```text
VM_HOST=185.207.65.14
VM_USER=root
VM_SSH_KEY=<private SSH key allowed to connect to the VM>
VM_SSH_PORT=22
```

`VM_SSH_PORT` is optional; it defaults to `22`.

If `VM_USER` is not `root`, it must be able to run these commands without a
password:

```bash
sudo systemctl start yclients-auto-deploy.service
sudo journalctl -u yclients-auto-deploy.service -n 120 --no-pager
```

Manual GitHub run: Actions -> Test and Deploy VM -> Run workflow.

## VM Timer Fallback

Install once on the VM:

```bash
sudo cp deploy/vm/yclients-auto-deploy.service /etc/systemd/system/
sudo cp deploy/vm/yclients-auto-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yclients-auto-deploy.timer
```

Manual run:

```bash
sudo systemctl start yclients-auto-deploy.service
```

Deployment flow:

```bash
git add .
git commit -m "..."
git push origin main
```

Vercel updates the frontend from GitHub. GitHub Actions starts the VM deploy,
which runs migrations and restarts `api` and `worker`. If Actions is unavailable,
the VM timer fallback catches the change within 5 minutes.
