# VM Auto Deploy

The VM treats GitHub `main` as the source of truth. Vercel deploys frontend from
GitHub, and the VM polls GitHub every 5 minutes for backend/API changes.

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

Vercel updates the frontend from GitHub. The VM updates itself within 5 minutes,
runs migrations, and restarts `api` and `worker`.
